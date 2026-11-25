"""Unified Tool Gateway: schema checks, side-effect confirmations, and secret-safe execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import re
from time import monotonic, perf_counter
from typing import Any
from uuid import UUID, uuid4

from .audit_store import redact_value
from .llm import ProviderError

_CONFIRM_RE = re.compile(
    r"^(?:(?:好[的呀啦]?|嗯|行|是[的啊呀]?|可以)[，,、\s]*)?"
    r"(?:好[的呀啦]?|是[的啊呀]?|对|没错|确定|确认|可以|行|没问题|执行|继续|就这么[办定]|准)"
    r"(?:[，,、\s]*(?:确认|执行|操作))?[吧呀啊啦呢]?[。！!，,\s]*$",
)
_DENY_RE = re.compile(
    r"(?:取消|算了|别执行|不要执行|不用了|不是|不对|先别|停止执行|放弃)",
)


class SideEffectConfirmationRequired(Exception):
    def __init__(
        self,
        tool_name: str,
        summary: str,
        *,
        approval_id: str = "",
        permission: str = "write",
        arguments_preview: dict | None = None,
    ):
        self.code = "confirmation_required"
        self.tool_name = tool_name
        self.summary = summary
        self.approval_id = approval_id
        self.permission = permission
        self.arguments_preview = arguments_preview or {}
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


def _preview_arguments(arguments: Any, secrets=()) -> Any:
    redacted = redact_value(arguments, secrets)
    if isinstance(redacted, dict):
        preview = {}
        for k, v in list(redacted.items())[:12]:
            if isinstance(v, str) and len(v) > 120:
                preview[k] = v[:117] + "..."
            else:
                preview[k] = v
        return preview
    return redacted


@dataclass
class _PendingAction:
    approval_id: str
    session_id: UUID
    tool_name: str
    args_digest: str
    turn_id: UUID
    summary: str
    permission: str = "write"
    arguments_preview: dict = field(default_factory=dict)
    created_at: float = field(default_factory=monotonic)
    expires_at: float = field(default_factory=lambda: monotonic() + 300.0)
    status: str = "pending"  # pending | approved | denied | expired | consumed | superseded

    def to_public(self) -> dict:
        remaining = max(0, int(self.expires_at - monotonic()))
        return {
            "approval_id": self.approval_id,
            "session_id": str(self.session_id),
            "turn_id": str(self.turn_id),
            "tool_name": self.tool_name,
            "permission": self.permission,
            "summary": self.summary,
            "arguments": self.arguments_preview,
            "status": self.status,
            "expires_in_seconds": remaining,
        }


@dataclass
class _SessionConfirmationState:
    pending: _PendingAction | None = None
    confirmed_for_turn: UUID | None = None
    confirmed_tool: str = ""
    confirmed_digest: str = ""
    confirmed_summary: str = ""
    denied_for_turn: UUID | None = None
    denied_tool: str = ""
    desktop_lease_until: float = 0.0


DESKTOP_LEASE_TOOLS = frozenset({"desktop_open", "desktop_gui_action", "desktop_set_clipboard"})


class SideEffectConfirmationStore:
    """Tracks generic write/paid tool confirmation per session."""

    def __init__(self, ttl_seconds: float = 300.0):
        self.ttl_seconds = max(5.0, float(ttl_seconds))
        self._sessions: dict[UUID, _SessionConfirmationState] = {}
        self._approvals: dict[str, _PendingAction] = {}

    def _prune_approvals(self) -> None:
        now = monotonic()
        for item in self._approvals.values():
            if item.status == "pending" and now > item.expires_at:
                item.status = "expired"
                state = self._sessions.get(item.session_id)
                if state is not None and state.pending is item:
                    state.pending = None
        if len(self._approvals) > 512:
            for key in list(self._approvals)[: len(self._approvals) - 256]:
                self._approvals.pop(key, None)

    def begin_turn(self, session_id: UUID, turn_id: UUID, question: str) -> None:
        self._prune_approvals()
        state = self._sessions.get(session_id)
        if state is None or state.pending is None:
            return
        pending = state.pending
        if pending.turn_id == turn_id:
            return
        if monotonic() > pending.expires_at:
            pending.status = "expired"
            state.pending = None
            return
        text = (question or "").strip()
        if not text:
            return
        if _DENY_RE.search(text):
            pending.status = "denied"
            state.denied_for_turn = turn_id
            state.denied_tool = pending.tool_name
            state.pending = None
            return
        if pending.status == "approved" or _CONFIRM_RE.match(text):
            was_pending = pending.status == "pending"
            pending.status = "consumed"
            state.confirmed_for_turn = turn_id
            state.confirmed_tool = pending.tool_name
            state.confirmed_digest = pending.args_digest
            state.confirmed_summary = pending.summary
            # Voice/text confirmation of an interactive desktop tool also grants the 3-minute
            # desktop lease so multi-step GUI follow-ups don't prompt on every single click.
            if was_pending and pending.tool_name in DESKTOP_LEASE_TOOLS:
                state.desktop_lease_until = monotonic() + 180.0
            state.pending = None
            return
        # New unrelated question clears stale pending confirmation safely.
        pending.status = "expired"
        state.pending = None

    def authorize(
        self,
        session_id: UUID,
        turn_id: UUID,
        tool_name: str,
        arguments: dict,
        *,
        permission: str = "write",
        secrets=(),
    ) -> str:
        self._prune_approvals()
        state = self._sessions.setdefault(session_id, _SessionConfirmationState())
        digest = _args_digest(arguments)
        if (state.confirmed_for_turn == turn_id
                and state.confirmed_tool == tool_name
                and state.confirmed_digest == digest):
            return "execute"
        if state.denied_for_turn == turn_id and state.denied_tool == tool_name:
            return "denied"
        if tool_name in DESKTOP_LEASE_TOOLS and monotonic() < state.desktop_lease_until:
            return "execute"
        if state.pending is not None and state.pending.status == "pending":
            state.pending.status = "superseded"
        preview = _preview_arguments(arguments, secrets)
        summary = json.dumps(preview, ensure_ascii=False)
        if len(summary) > 200:
            summary = summary[:197] + "..."
        action = _PendingAction(
            approval_id=uuid4().hex[:16],
            session_id=session_id,
            tool_name=tool_name,
            args_digest=digest,
            turn_id=turn_id,
            summary=summary,
            permission=permission,
            arguments_preview=preview if isinstance(preview, dict) else {},
            expires_at=monotonic() + self.ttl_seconds,
        )
        state.pending = action
        self._approvals[action.approval_id] = action
        return "ask"

    def latest_for_turn(self, session_id: UUID, turn_id: UUID) -> dict | None:
        self._prune_approvals()
        state = self._sessions.get(session_id)
        if state is None or state.pending is None or state.pending.turn_id != turn_id:
            return None
        return state.pending.to_public()

    def confirmed_action(self, session_id: UUID, turn_id: UUID) -> dict | None:
        state = self._sessions.get(session_id)
        if state is None or state.confirmed_for_turn != turn_id or not state.confirmed_tool:
            return None
        return {"tool_name": state.confirmed_tool, "summary": state.confirmed_summary}

    def denied_action(self, session_id: UUID, turn_id: UUID) -> dict | None:
        state = self._sessions.get(session_id)
        if state is None or state.denied_for_turn != turn_id or not state.denied_tool:
            return None
        return {"tool_name": state.denied_tool}

    def has_desktop_lease(self, session_id: UUID) -> bool:
        state = self._sessions.get(session_id)
        return state is not None and monotonic() < state.desktop_lease_until

    def approval_status(self, approval_id: str) -> str | None:
        self._prune_approvals()
        action = self._approvals.get(approval_id)
        return action.status if action is not None else None

    def get(self, approval_id: str) -> dict | None:
        self._prune_approvals()
        action = self._approvals.get(approval_id)
        return action.to_public() if action is not None else None

    def decide(self, approval_id: str, decision: str, session_id: UUID | None = None) -> dict:
        self._prune_approvals()
        action = self._approvals.get(approval_id)
        if action is None:
            raise ProviderError(404, "approval_not_found", "待确认操作不存在或已过期。")
        if session_id is not None and action.session_id != session_id:
            raise ProviderError(403, "approval_session_mismatch", "该确认请求不属于当前会话。")
        if action.status == "expired":
            raise ProviderError(409, "approval_expired", "该确认请求已超时，请重新发起请求。")
        if action.status != "pending":
            raise ProviderError(409, "approval_closed", f"该操作已处于 {action.status} 状态，不能重复确认。")
        state = self._sessions.setdefault(action.session_id, _SessionConfirmationState())
        if decision == "deny":
            action.status = "denied"
            state.desktop_lease_until = 0.0
            if state.pending is action:
                state.pending = None
        elif decision == "approve":
            action.status = "approved"
            state.pending = action
        elif decision == "approve_desktop_lease":
            if action.tool_name not in DESKTOP_LEASE_TOOLS:
                raise ProviderError(422, "lease_not_allowed", "该操作风险较高，只允许逐次确认，不支持连续托管。")
            action.status = "approved"
            state.pending = action
            state.desktop_lease_until = monotonic() + 180.0
        else:
            raise ProviderError(422, "invalid_decision", "仅支持 approve、approve_desktop_lease 或 deny。")
        return action.to_public()

    def revoke_all_desktop_leases(self) -> None:
        for state in self._sessions.values():
            state.desktop_lease_until = 0.0
            state.pending = None

    def clear_session(self, session_id: UUID) -> None:
        self._sessions.pop(session_id, None)
        for key, item in list(self._approvals.items()):
            if item.session_id == session_id:
                self._approvals.pop(key, None)


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
            decision = self.confirmations.authorize(
                session_id, turn_id, name, arguments,
                permission=tool.spec.permission, secrets=secrets,
            )
            if decision == "denied":
                raise SideEffectConfirmationDenied(name)
            if decision == "ask":
                pending = self.confirmations.latest_for_turn(session_id, turn_id)
                summary = pending["summary"] if pending else json.dumps(arguments, ensure_ascii=False)[:200]
                raise SideEffectConfirmationRequired(
                    name, summary,
                    approval_id=pending["approval_id"] if pending else "",
                    permission=tool.spec.permission,
                    arguments_preview=pending.get("arguments") if pending else None,
                )
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
