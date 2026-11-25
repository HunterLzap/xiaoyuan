import asyncio
import json
import logging
import re
from urllib.parse import urlencode
from uuid import uuid4

from websockets.exceptions import WebSocketException

from .audit_store import _redact_text, redact_value
from .llm import Completion, OpenAICompatibleProvider, ProviderError
from .realtime import DirectConnect, is_qwen_audio_realtime
from .schemas import TokenUsage
from .speech_text import function_call_output_payload
from .prompt_builder import build_system_prompt
from .text_tool_selection import TextToolSelection
from .tool_dialogue import TOOL_LOADING_NAME

logger = logging.getLogger(__name__)
_NATIVE_SEARCH_STUB_RE = re.compile(r"(?:这就|马上|立刻|帮你|给你|先去|去).{0,8}(?:查|搜|看)|稍等")


def _upstream_error_detail(event: dict, secrets: tuple | list = ()) -> str:
    err = event.get("error") if isinstance(event.get("error"), dict) else None
    if err is None:
        status_details = (event.get("response") or {}).get("status_details")
        if isinstance(status_details, dict) and isinstance(status_details.get("error"), dict):
            err = status_details["error"]
    if not err:
        resp_status = (event.get("response") or {}).get("status")
        if resp_status and resp_status != "completed":
            return _redact_text(f"status={resp_status}", secrets)
        return ""
    code = str(err.get("code") or "").strip()
    message = str(err.get("message") or "").strip()
    parts = [part for part in (code, message) if part]
    detail = " - ".join(parts) if parts else json.dumps(err, ensure_ascii=False)
    return _redact_text(detail, secrets)[:260]


class RealtimeTextProvider:
    def __init__(self, settings):
        self.settings = settings

    native_tool_continuation = True

    async def complete_stream(self, messages, *, tool_context=None, results=None):
        settings = self.settings
        if settings.rt_provider == "compatible":
            address = settings.rt_endpoint
        elif settings.rt_workspace:
            address = f"wss://{settings.rt_workspace}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime"
        else:
            address = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
        endpoint = address + "?" + urlencode({"model": settings.rt_model})
        request_pending = False
        round_results = results if results is not None else []
        from .tool_dialogue import DESKTOP_TOOL_NAMES, combine_usage, turn_limits
        allowed = getattr(tool_context, "allowed", set()) or set()
        use_native_search = (
            settings.rt_provider == "bailian"
            and is_qwen_audio_realtime(settings.rt_model)
            and "web_search" in allowed
        )
        excluded_tools = {"web_search", "get_weather"} if use_native_search else set()
        assistant_content_type = (
            "output_text"
            if settings.rt_provider == "bailian" and is_qwen_audio_realtime(settings.rt_model)
            else "text"
        )
        secrets = [settings.rt_api_key.get_secret_value(), *(getattr(tool_context, "secrets", None) or ())]

        def raise_upstream(event: dict):
            detail = _upstream_error_detail(event, secrets)
            logger.warning(
                "realtime_text upstream error event=%s detail=%s",
                event.get("type"),
                detail or json.dumps(redact_value(event, secrets), ensure_ascii=False)[:400],
            )
            raise ProviderError(
                502,
                "realtime_text_failed",
                f"实时模型文字请求失败：{detail}" if detail else "实时模型文字请求失败，请检查接入配置。",
            )

        max_rounds, _ = turn_limits(allowed)
        timeout_budget = max(float(settings.timeout_seconds), 120.0) if (allowed & DESKTOP_TOOL_NAMES) else float(settings.timeout_seconds)
        try:
            async with asyncio.timeout(timeout_budget):
                async with DirectConnect(
                    endpoint, proxy=None, close_timeout=2, max_size=4 * 1024 * 1024,
                    additional_headers={"Authorization": "Bearer " + settings.rt_api_key.get_secret_value()},
                ) as socket:
                    async def send(kind, **fields):
                        await socket.send(json.dumps({"type": kind, "event_id": uuid4().hex, **fields}))

                    created = json.loads(await socket.recv())
                    if created.get("type") != "session.created":
                        raise_upstream(created)
                    joined = "\n".join(message["content"] for message in messages if message["role"] == "system")
                    eligible_defs = (
                        [item for item in tool_context.definitions(compact=True)
                         if item.get("function", item).get("name") not in excluded_tools]
                        if tool_context is not None else []
                    )
                    selection = (
                        TextToolSelection(tool_context, exclude=excluded_tools)
                        if (tool_context is not None
                            and getattr(tool_context, "registry", None) is not None
                            and getattr(settings, "rt_lazy_tools", True)
                            and len(eligible_defs) > 5)
                        else None
                    )
                    turn_state = (tool_context.order_state_text()
                                  if tool_context is not None and hasattr(tool_context, "order_state_text") else "")

                    def selected_config():
                        nested = settings.rt_provider == "bailian"
                        if selection is not None:
                            active_names = [
                                n for n in selection.active_names()
                                if n not in excluded_tools
                            ]
                            defs = selection.definitions(nested=nested)
                        elif tool_context is not None:
                            defs = tool_context.definitions(nested=nested, compact=True)
                            active_names = [
                                item.get("function", item).get("name") for item in defs
                                if item.get("function", item).get("name")
                                and item.get("function", item).get("name") not in excluded_tools
                            ]
                        else:
                            active_names, defs = [], []
                        if excluded_tools:
                            defs = [item for item in defs if item.get("function", item).get("name") not in excluded_tools]
                        instructions = build_system_prompt(
                            settings, "text", active_names,
                            turn_state or None, assistant_prompt=joined, compact=True,
                            native_search=use_native_search)
                        if selection is not None:
                            instructions += selection.instructions()
                        return {"instructions": instructions, "tools": defs}

                    session_config: dict = {"modalities": ["text"], "turn_detection": None, **selected_config()}
                    if use_native_search:
                        session_config["enable_search"] = True
                        session_config["search_options"] = {"enable_source": True}
                    await send("session.update", session=session_config)
                    while True:
                        event = json.loads(await socket.recv())
                        if event.get("type") == "session.updated":
                            break
                        if event.get("type") == "error":
                            raise_upstream(event)
                    for message in messages:
                        if message["role"] == "system":
                            continue
                        content_text = str(message.get("content") or "")
                        if not content_text:
                            continue
                        await send("conversation.item.create", item={
                            "type": "message", "role": message["role"],
                            "content": [{"type": "input_text" if message["role"] == "user" else assistant_content_type,
                                         "text": content_text}],
                        })
                    request_pending = True
                    await send("response.create")
                    function_calls, round_index = {}, 0
                    response_text, native_search_nudged = "", False
                    while True:
                        event = json.loads(await socket.recv())
                        kind = event.get("type")
                        if kind == "response.created" and tool_context is not None:
                            tool_context.mark_sent(list(tool_context.outputs))
                        if kind in ("response.text.delta", "response.output_text.delta"):
                            delta = event.get("delta") or ""
                            if delta:
                                response_text += delta
                                yield delta
                        elif kind == "error":
                            raise_upstream(event)
                        elif kind == "response.output_item.done" and event.get("item", {}).get("type") == "function_call":
                            item = event["item"]
                            function_calls[item["call_id"]] = item
                        elif kind == "response.function_call_arguments.done":
                            function_calls.setdefault(event["call_id"], {}).update(event)
                        elif kind == "response.done":
                            response = event["response"]
                            if response.get("status") != "completed":
                                raise_upstream(event)
                            from dataclasses import replace
                            usage = response.get("usage") or {}
                            search_results = (response.get("search_info") or {}).get("search_results") or []
                            search_count = ((usage.get("plugins") or {}).get("search") or {}).get("count") or 0
                            for item in response.get("output", []):
                                if item.get("type") == "function_call":
                                    function_calls[item["call_id"]] = item
                            result = Completion(None, TokenUsage.from_provider(usage) if usage else None,
                                                "tool_calls" if function_calls else "stop")
                            round_results.append(result)
                            request_pending = False
                            if not function_calls:
                                stub_text = response_text.strip()
                                if (use_native_search and not native_search_nudged
                                        and search_count == 0 and not search_results
                                        and 0 < len(stub_text) <= 32
                                        and _NATIVE_SEARCH_STUB_RE.search(stub_text)):
                                    native_search_nudged = True
                                    logger.info("realtime_text native_search stub detected, nudging once")
                                    yield "\n\n"
                                    response_text = ""
                                    await send("conversation.item.create", item={
                                        "type": "message",
                                        "role": "user",
                                        "content": [{"type": "input_text", "text": "请直接联网搜索并一次性给出具体查询结果与数据时间，不要只说正在查询。"}],
                                    })
                                    request_pending = True
                                    await send("response.create")
                                    continue
                                yield replace(result, usage=combine_usage(round_results))
                                return
                            if tool_context is None:
                                raise ProviderError(502, "tool_not_configured", "模型请求了未配置的工具。")
                            if round_index >= max_rounds:
                                raise ProviderError(502, "tool_limit", "本轮工具调用已达上限，未继续执行。")
                            loading_only = True
                            active_before = selection.active_names() if selection is not None else ()
                            for call_id, call in function_calls.items():
                                output = await tool_context.execute(call.get("name", ""), call.get("arguments", "{}"), call_id)
                                if call.get("name") != TOOL_LOADING_NAME or output.get("error"):
                                    loading_only = False
                                await send("conversation.item.create", item={"type": "function_call_output",
                                    "call_id": call_id, "output": function_call_output_payload(output)})
                                tool_context.mark_sent([call_id])
                            function_calls = {}
                            if not loading_only:
                                round_index += 1
                            if round_index == max_rounds or (selection is not None and selection.active_names() != active_before):
                                await send("session.update", session=(
                                    {"tools": []} if round_index == max_rounds else selected_config()))
                                while True:
                                    update = json.loads(await socket.recv())
                                    if update.get("type") == "error":
                                        raise_upstream(update)
                                    if update.get("type") == "session.updated":
                                        break
                            response_text = ""
                            request_pending = True
                            await send("response.create")
        except ProviderError:
            raise
        except TimeoutError:
            raise ProviderError(504, "realtime_text_timeout", "实时模型文字回答超时。") from None
        except (WebSocketException, OSError, ValueError, KeyError) as exc:
            logger.warning("realtime_text connection/protocol error: %s", type(exc).__name__)
            raise ProviderError(502, "realtime_text_failed", f"实时模型文字请求失败：{type(exc).__name__}") from None
        finally:
            if request_pending:
                round_results.append(Completion(None, None, None))

    async def complete(self, messages):
        reply = ""
        result = None
        async for item in self.complete_stream(messages):
            if isinstance(item, str):
                reply += item
            else:
                result = item
        result = result or Completion(None, None, None)
        result.reply = reply
        return result

    async def close(self):
        pass


def build_chat_provider(settings):
    return RealtimeTextProvider(settings) if settings.voice_mode == "realtime" else OpenAICompatibleProvider(settings)
