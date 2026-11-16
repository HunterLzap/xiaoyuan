"""Unified Tool Gateway: schema checks, side-effect confirmations, and secret-safe execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import re
from time import perf_counter
from typing import Any
from uuid import UUID

from .audit_store import redact_value
from .llm import ProviderError

_CONFIRM_RE = re.compile(
    r"^(?:好[的呀啦]?|是[的啊呀]?|对|没错|确定|确认|可以|行|没问题|执行吧?|继续|就这么[办定]|准)[。！!，,\s]*$",
)
_DENY_RE = re.compile(
    r"(?:取消|算了|别执行|不要执行|不用了|不是|不对|先别|停止执行|放弃)",
)


class SideEffectConfirmationRequired(Exception):
    def __init__(self, tool_name: str, summary: str):
        self.code = "confirmation_required"
        self.tool_name = tool_name
        self.summary = summary
        self.message = f"该操作（{tool_name}）会修改外部状态或产生费用，参数：{summary}。确认执行吗？"
        super().__init__(self.message)


class SideEffectConfirmationDenied(Exception):
    def __init__(self, tool_name: str):
        self.code = "confirmation_denied"
        self.tool_name = tool_name
        self.message = f"你已取消执行 {tool_name}。"
        super().__init__(self.message)


def _args_digest(arguments: dict) -> str:
    canonical = json.dumps(arguments, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass
class _PendingAction:
    tool_name: str
    args_digest: str
    turn_id: UUID
    summary: str


@dataclass
class _SessionConfirmationState:
    pending: _PendingAction | None = None
    confirmed_for_turn: UUID | None = None
    confirmed_tool: str = ""
    confirmed_digest: str = ""
    denied_for_turn: UUID | None = None
    denied_tool: str = ""


class SideEffectConfirmationStore:
    """Tracks generic write/paid tool confirmation per session."""

    def __init__(self):
        self._sessions: dict[UUID, _SessionConfirmationState] = {}

    def begin_turn(self, session_id: UUID, turn_id: UUID, question: str) -> None:
        state = self._sessions.get(session_id)
        if state is None or state.pending is None:
            return
        pending = state.pending
        if pending.turn_id == turn_id:
            return
        text = (question or "").strip()
        if not text:
            return
        if _DENY_RE.search(text):
            state.denied_for_turn = turn_id
            state.denied_tool = pending.tool_name
            state.pending = None
            return
        if _CONFIRM_RE.match(text):
            state.confirmed_for_turn = turn_id
            state.confirmed_tool = pending.tool_name
            state.confirmed_digest = pending.args_digest
            state.pending = None
            return
        # New unrelated question clears stale pending confirmation safely.
        state.pending = None

    def authorize(self, session_id: UUID, turn_id: UUID, tool_name: str, arguments: dict) -> str:
        state = self._sessions.setdefault(session_id, _SessionConfirmationState())
        digest = _args_digest(arguments)
        if (state.confirmed_for_turn == turn_id
                and state.confirmed_tool == tool_name
                and state.confirmed_digest == digest):
            return "execute"
        if state.denied_for_turn == turn_id and state.denied_tool == tool_name:
            return "denied"
        summary = json.dumps(arguments, ensure_ascii=False)
        if len(summary) > 200:
            summary = summary[:197] + "..."
        state.pending = _PendingAction(
            tool_name=tool_name,
            args_digest=digest,
            turn_id=turn_id,
            summary=summary,
        )
        return "ask"

    def clear_session(self, session_id: UUID) -> None:
        self._sessions.pop(session_id, None)


class ToolGateway:
    """Single validation, confirmation, execution, and redaction boundary for all tools."""

    def __init__(self, confirmation_store: SideEffectConfirmationStore | None = None):
        self.confirmations = confirmation_store or SideEffectConfirmationStore()

    @staticmethod
    def definitions(registry, *, nested: bool = False, include_side_effects: bool = False) -> list[dict]:
        if registry is None:
            return []
        return registry.definitions(nested=nested, include_side_effects=include_side_effects)

    async def execute_manual(
        self,
        registry,
        name: str,
        arguments: dict,
        *,
        confirmed: bool = False,
        secrets=(),
        trace_out: dict | None = None,
    ) -> dict:
        if registry is None:
            raise ProviderError(404, "tool_not_found", "工具不存在或未启用。")
        tool = registry.get(name)
        if tool is None:
            raise ProviderError(404, "tool_not_found", "工具不存在或未启用。")
        permission = tool.spec.permission
        trace = trace_out if trace_out is not None else {}
        trace.clear()
        started = perf_counter()
        status, error_code = "error", None
        result = None
        if hasattr(tool, "last_exchange"):
            tool.last_exchange = None
        try:
            result = await registry.call(name, arguments, confirmed=confirmed, trace=trace)
            status = "ok"
            return {
                "result": redact_value(result, secrets),
                "permission": permission,
                "status": status,
                "error_code": None,
                "elapsed_ms": int((perf_counter() - started) * 1000),
                "trace": redact_value(trace, secrets),
            }
        except ProviderError as error:
            error_code = error.code
            raise
        except Exception as error:
            error_code = getattr(error, "code", None) or type(error).__name__
            raise
        finally:
            if status != "ok":
                exchange = getattr(tool, "last_exchange", None) or {}
                if exchange and not trace:
                    trace.update(exchange)
            trace["_gateway"] = {
                "permission": permission,
                "status": status,
                "error_code": error_code,
                "elapsed_ms": int((perf_counter() - started) * 1000),
            }

    async def execute_conversational(
        self,
        registry,
        *,
        name: str,
        arguments: dict,
        session_id: UUID,
        turn_id: UUID,
        secrets=(),
        trace: dict | None = None,
    ) -> Any:
        if registry is None:
            raise ProviderError(403, "tool_not_allowed", "工具已被取消选用或停用，未执行。")
        tool = registry.get(name)
        if tool is None:
            raise ProviderError(403, "tool_not_allowed", "工具已被取消选用或停用，未执行。")
        confirmed = True
        if tool.spec.permission in ("write", "paid"):
            decision = self.confirmations.authorize(session_id, turn_id, name, arguments)
            if decision == "denied":
                raise SideEffectConfirmationDenied(name)
            if decision == "ask":
                summary = json.dumps(arguments, ensure_ascii=False)[:200]
                raise SideEffectConfirmationRequired(name, summary)
            confirmed = True
        result = await registry.call(name, arguments, confirmed=confirmed, trace=trace)
        return redact_value(result, secrets)


@dataclass
class TurnTraceSummary:
    trace_id: str
    session_id: str
    source: str
    voice_mode: str
    provider: str
    model: str
    user_text: str
    reply_text: str
    status: str
    audio_status: str | None = None
    error_code: str | None = None
    elapsed_ms: int = 0
    first_audio_ms: int | None = None
    asr_provider: str | None = None
    tts_provider: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost: str | None = None
    currency: str | None = None
    tool_calls: list[dict] = field(default_factory=list)
