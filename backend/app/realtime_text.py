import asyncio
import json
from urllib.parse import urlencode
from uuid import uuid4

from websockets.exceptions import WebSocketException

from .llm import Completion, OpenAICompatibleProvider, ProviderError
from .realtime import DirectConnect
from .schemas import TokenUsage
from .speech_text import function_call_output_payload
from .prompt_builder import build_system_prompt
from .text_tool_selection import TextToolSelection
from .tool_dialogue import TOOL_LOADING_NAME


class RealtimeTextProvider:
    def __init__(self, settings):
        self.settings = settings

    native_tool_continuation = True

    async def complete_stream(self, messages, *, tool_context=None, results=None):
        settings = self.settings
        address = settings.rt_endpoint if settings.rt_provider == "compatible" else (
            f"wss://{settings.rt_workspace}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime")
        endpoint = address + "?" + urlencode({"model": settings.rt_model})
        request_pending = False
        round_results = results if results is not None else []
        try:
            async with asyncio.timeout(settings.timeout_seconds):
                async with DirectConnect(
                    endpoint, proxy=None, close_timeout=2, max_size=4 * 1024 * 1024,
                    additional_headers={"Authorization": "Bearer " + settings.rt_api_key.get_secret_value()},
                ) as socket:
                    async def send(kind, **fields):
                        await socket.send(json.dumps({"type": kind, "event_id": uuid4().hex, **fields}))

                    if json.loads(await socket.recv()).get("type") != "session.created":
                        raise ValueError()
                    joined = "\n".join(message["content"] for message in messages if message["role"] == "system")
                    selection = TextToolSelection(tool_context) if tool_context is not None else None
                    turn_state = (tool_context.order_state_text()
                                  if tool_context is not None and hasattr(tool_context, "order_state_text") else "")
                    def selected_config():
                        instructions = build_system_prompt(
                            settings, "text", selection.active_names() if selection else [],
                            turn_state or None, assistant_prompt=joined, compact=True)
                        if selection:
                            instructions += selection.instructions()
                        return {"instructions": instructions,
                                "tools": selection.definitions(nested=settings.rt_provider == "bailian") if selection else []}

                    session_config = {"modalities": ["text"], "turn_detection": None, **selected_config()}
                    await send("session.update", session=session_config)
                    while True:
                        event = json.loads(await socket.recv())
                        if event.get("type") == "session.updated":
                            break
                        if event.get("type") == "error":
                            raise ValueError()
                    for message in messages:
                        if message["role"] == "system":
                            continue
                        await send("conversation.item.create", item={
                            "type": "message", "role": message["role"],
                            "content": [{"type": "input_text" if message["role"] == "user" else "text",
                                         "text": message["content"]}],
                        })
                    request_pending = True
                    await send("response.create")
                    function_calls, round_index = {}, 0
                    while True:
                        event = json.loads(await socket.recv())
                        kind = event.get("type")
                        if kind == "response.created" and tool_context is not None:
                            tool_context.mark_sent(list(tool_context.outputs))
                        if kind == "response.text.delta":
                            yield event["delta"]
                        elif kind == "error":
                            raise ValueError()
                        elif kind == "response.output_item.done" and event.get("item", {}).get("type") == "function_call":
                            item = event["item"]
                            function_calls[item["call_id"]] = item
                        elif kind == "response.function_call_arguments.done":
                            function_calls.setdefault(event["call_id"], {}).update(event)
                        elif kind == "response.done":
                            response = event["response"]
                            if response.get("status") != "completed":
                                raise ValueError()
                            from dataclasses import replace
                            from .tool_dialogue import combine_usage, MAX_TOOL_ROUNDS
                            usage = response.get("usage") or {}
                            for item in response.get("output", []):
                                if item.get("type") == "function_call":
                                    function_calls[item["call_id"]] = item
                            result = Completion(None, TokenUsage.from_provider(usage) if usage else None,
                                                "tool_calls" if function_calls else "stop")
                            round_results.append(result)
                            request_pending = False
                            if not function_calls:
                                yield replace(result, usage=combine_usage(round_results))
                                return
                            if tool_context is None or selection is None:
                                raise ProviderError(502, "tool_not_configured", "模型请求了未配置的工具。")
                            if round_index >= MAX_TOOL_ROUNDS:
                                raise ProviderError(502, "tool_limit", "本轮工具调用已达上限，未继续执行。")
                            loading_only = True
                            active_before = selection.active_names()
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
                            if round_index == MAX_TOOL_ROUNDS or selection.active_names() != active_before:
                                await send("session.update", session=(
                                    {"tools": []} if round_index == MAX_TOOL_ROUNDS else selected_config()))
                                while True:
                                    update = json.loads(await socket.recv())
                                    if update.get("type") == "error":
                                        raise ValueError()
                                    if update.get("type") == "session.updated":
                                        break
                            request_pending = True
                            await send("response.create")
        except TimeoutError:
            raise ProviderError(504, "realtime_text_timeout", "实时模型文字回答超时。") from None
        except (WebSocketException, OSError, ValueError, KeyError):
            raise ProviderError(502, "realtime_text_failed", "实时模型文字请求失败，请检查接入配置。") from None
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
