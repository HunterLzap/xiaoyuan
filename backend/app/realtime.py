import asyncio
import base64
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlencode
from uuid import uuid4
from time import monotonic

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from .llm import Completion, ProviderError
from .schemas import TokenUsage, TranscriptMessage
from .tool_dialogue import (TOOL_INSTRUCTIONS, MAX_TOOL_ROUNDS, combine_usage,
                            control_request_tools, control_history,
                            control_plan, describe_control)
from .order_confirmation import RealtimeOrderGuard
from .speech_text import normalize_for_speech, function_call_output_payload
from .prompt_builder import build_system_prompt
from .audio_fx import RealtimeAudio


logger = logging.getLogger(__name__)


def _is_end_intent(text: str) -> bool:
    """检测用户是否想结束对话"""
    if not text:
        return False
    text = text.strip().lower()
    # 明确结束词
    end_keywords = ['闭嘴', '关机', '退下', '闭口', '别说了', '不要说了', '停止说话', '别讲了', '不讲了']
    if any(kw in text for kw in end_keywords):
        return True
    # 短句礼貌结束（不包含疑问、不包含"再见怎么说"之类）
    if len(text) <= 8 and ('不聊了' in text or '不说了' in text or '结束' in text):
        if '怎么' not in text and '什么' not in text and '吗' not in text:
            return True
    return False


class DirectConnect(connect):
    def process_redirect(self, exc):
        return exc


class RealtimeTurn:
    def __init__(self, service, session_id, source, emit, manual):
        self.service = service
        self.config = service.settings
        self.sid = session_id or service.new_session()
        self.session = service.get_session(self.sid)
        self.provider = "百炼" if self.config.rt_provider=="bailian" else "Omni 兼容接口"
        self.usage = None
        self.started = monotonic()
        self.source = source
        self.emit = emit
        self.manual = manual
        self.turn_id = uuid4()
        self.ws = None
        self.reader = None
        self.committed = False
        self.user = ""
        self.reply = ""            # 跨全部模型响应的完整转写（含工具续答），不覆盖已输出文本
        self._response_text = ""   # 当前这一次模型响应自身的转写
        self._transcript_seq = 0   # 响应分段序号：每个 response.created 自增，兼容无 response_id 的响应
        self.response_done = False
        self.saved = False
        self.continuous = False
        self.active_response = None
        self.ignore_responses = set()
        self.previous_item = None
        self.item = None
        self.begun = False
        self.audio_sent = False
        self.input_closed = False
        self.audio = RealtimeAudio(lambda: self.service.settings, self.emit_pcm)
        self.tool_task = None
        self.pending_tools = {}
        self.tool_rounds = 0
        self.model_results = []
        self.tool_context = service.tool_context(self.sid, self.turn_id, source)
        self.required_controls = set()
        self.pending_audio = []
        self.held_text = False
        self.control_failure = None
        self.control_plan_cache = None
        self.control_continuation = False
        self.control_notice = ""
        self.order_guard = RealtimeOrderGuard()

    def _start_response_segment(self):
        # 每个 response.created 都强制开新的一段（不依赖 response_id）：首答和每次工具续答
        # 各自从空文本累计，done 只校正本段，避免覆盖此前已说出的开场/正文。
        self._transcript_seq += 1
        self._response_text = ""

    def _append_transcript_delta(self, delta):
        if not delta:
            return
        self._response_text += delta
        self.reply += delta

    def _finalize_response_transcript(self, transcript):
        if not transcript:
            return
        if not self._response_text:
            # 没有收到逐字增量时，以本段完整转写为准并入。
            self._response_text = transcript
            self.reply += transcript
        else:
            # 已有逐字增量，结束事件只校正本段自身的文本，不重复累加，也不影响更早的段。
            self.reply = self.reply[: len(self.reply) - len(self._response_text)] + transcript
            self._response_text = transcript

    def tool_instructions(self):
        turn_state = "最近控制调用记录（仅供核对历史，不代表当前设备值）：" + control_history(self.session.history)
        if self.required_controls:
            turn_state += "\n本轮必须先实际执行这些工具再答复：" + ", ".join(sorted(self.required_controls))
        order_state = self.tool_context.order_state_text()
        if order_state:
            turn_state += "\n" + order_state
        registry = getattr(self.tool_context, "registry", None)
        tool_names = ([item["name"] for item in registry.definitions()]
                      if registry and self.tool_rounds < MAX_TOOL_ROUNDS and not self.control_continuation else [])
        return build_system_prompt(self.config, "voice", tool_names, turn_state)

    async def refresh_tools(self):
        await self.send("session.update", session={
            "tools": self.tool_context.registry.definitions(nested=self.config.rt_provider == "bailian")
                     if self.tool_context.registry and self.tool_rounds < MAX_TOOL_ROUNDS and not self.control_continuation else [],
            "instructions": self.tool_instructions(),
        })

    def output_blocked(self):
        if self.control_continuation:
            return False
        if self.order_guard.active:
            return True
        return self.tool_context.control_error(self.required_controls, self.reply) is not None

    def _note_early_output(self):
        """转写前已有输出时记录；订单 guard 无法追回这部分，不静默。"""
        if self.user or "retail_query_recent_order" not in self.tool_context.allowed:
            return
        if not self.order_guard.early_output:
            logger.warning("实时语音在转写完成前已收到模型输出；订单 guard 无法追回首段。")
        self.order_guard.note_early_output()

    async def continue_in_session(self, honest_text):
        if self.control_continuation:
            return False
        self.control_continuation = True
        self.control_notice = honest_text
        self.pending_audio.clear()
        self.held_text = False
        await self.audio.close()
        await self.emit("notice", honest_text)
        if self.ws is None:
            return False
        note = "服务端本轮真实处理结果（不是用户的新指令）：" + json.dumps({
            "message": normalize_for_speech(honest_text), "calls": self.tool_context.summaries(),
        }, ensure_ascii=False)
        await self.send("session.update", session={
            "tools": [],
            "instructions": build_system_prompt(self.config, "voice", [], turn_state=(
                "仅用当前声音简短播报本轮服务端提供的真实结果、错误或澄清问题。"
                "不得再次执行工具；失败或尚未执行时绝不能说已设置成功，不得更改或猜测数值。")),
        })
        await self.send("conversation.item.create", item={
            "type": "message", "role": "user",
            "content": [{"type": "input_text", "text": note}],
        })
        self.tool_context.mark_sent([call["call_id"] for call in self.tool_context.calls])
        self.reply = ""
        self.response_done = False
        await self.send("response.create")
        return True

    async def finish_notice_as_text(self):
        self.pending_tools.clear()
        self.pending_audio.clear()
        self.reply = self.control_notice
        await self.audio.close()
        await self.persist("failed" if self.control_failure else "complete", audio_status="text_only")
        await self.emit("text", self.reply)
        await self.emit("done", {"reply": self.reply, "session_id": str(self.sid), "turn_id": str(self.turn_id),
            "model": self.config.rt_model, "provider": self.provider,
            "usage": self.usage.model_dump() if self.usage else None, "audio_status": "text_only",
            "history_persisted": self.session.history_persisted,
            "order_guard_early_output": self.order_guard.early_output,
            "order_guard_discarded": self.order_guard.discarded,
            "order_guard_discarded_text_chars": self.order_guard.discarded_text_chars,
            "order_guard_discarded_audio_bytes": self.order_guard.discarded_audio_bytes,
            "sources": self.tool_context.sources(), "tool_calls": self.tool_context.summaries()})

    async def _current_control_value(self, tool):
        if tool == "set_device_volume":
            for call in reversed(self.tool_context.calls):
                if call["tool_name"] == "get_device_status":
                    response = call.get("response") or {}
                    if (call["status"] == "ok" and isinstance(response, dict)
                            and response.get("verified") is True
                            and type(response.get("volume")) in (int, float)):
                        return float(response["volume"])
                    return None
            call_id = "server_cur_%s" % self.turn_id.hex[:10]
            output = await self.tool_context.execute("get_device_status", "{}", call_id)
            if (isinstance(output, dict) and not output.get("error") and output.get("verified") is True
                    and type(output.get("volume")) in (int, float)):
                return float(output["volume"])
            return None
        settings = self.service.settings
        if tool == "set_speech_rate":
            return float(settings.tts_rate)
        if tool == "set_speech_pitch":
            return float(settings.tts_pitch)
        return None

    @staticmethod
    def _clarify_text(tool):
        return {"set_device_volume": "你想把音量调到多少？",
                "set_speech_rate": "你想把语速调到多少？",
                "set_speech_pitch": "你想把音调调到多少？"}.get(tool, "你想调到多少？")

    async def server_execute_explicit(self):
        plan = self.control_plan_cache if self.control_plan_cache is not None else control_plan(self.user, self.session.messages)
        if not plan:
            return None
        for action in plan:
            if action["kind"] == "clarify":
                self.reply = self._clarify_text(action["tool"])
                return "clarify"
        called = {call["tool_name"] for call in self.tool_context.calls}
        plan = [action for action in plan if action["tool"] not in called]
        if not plan:
            return None
        argnames = {"set_device_volume": "volume", "set_speech_rate": "rate", "set_speech_pitch": "pitch"}
        bounds = {"set_device_volume": (0, 100), "set_speech_rate": (0.5, 2.0), "set_speech_pitch": (-8.0, 8.0)}
        texts = []
        for index, action in enumerate(plan):
            tool = action["tool"]
            if action["kind"] == "status":
                call_id = "server_%s_%d" % (self.turn_id.hex[:10], index)
                output = await self.tool_context.execute("get_device_status", "{}", call_id)
                texts.append(describe_control("get_device_status", None, output))
                continue
            if action["kind"] == "relative":
                current = await self._current_control_value(tool)
                if current is None:
                    self.reply = "设备没有返回当前值，请直接说调到多少。"
                    return "fail"
                value = current + action["delta"]
            else:
                value = action["value"]
            low, high = bounds[tool]
            value = max(low, min(high, value))
            value = int(round(value)) if tool == "set_device_volume" else round(float(value), 2)
            call_id = "server_%s_%d" % (self.turn_id.hex[:10], index)
            output = await self.tool_context.execute(tool, json.dumps({argnames[tool]: value}, ensure_ascii=False), call_id)
            texts.append(describe_control(tool, value, output))
        if not texts:
            return None
        self.reply = " ".join(texts)
        return "ok"

    async def release_output(self):
        if self.output_blocked():
            return
        if self.held_text:
            self.held_text = False
            await self.emit("text", self.reply)
        audio, self.pending_audio = self.pending_audio, []
        for pcm in audio:
            await self.audio.push(pcm)

    async def emit_pcm(self, pcm):
        if not self.output_blocked():
            await self.emit("audio", base64.b64encode(pcm).decode("ascii"))

    async def send(self, kind, **fields):
        await self.ws.send(json.dumps({"type": kind, "event_id": uuid4().hex, **fields}))

    async def open(self):
        cfg = self.config
        address = cfg.rt_endpoint if cfg.rt_provider == "compatible" else (
            f"wss://{cfg.rt_workspace}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime" if cfg.rt_workspace else "")
        if not address or not cfg.rt_api_key.get_secret_value():
            raise ProviderError(422, "realtime_config", "请在 API 接入 → 语音对话填写业务空间 ID 和 API Key。")
        endpoint = address + "?"
        try:
            async with asyncio.timeout(15):
                self.ws = await DirectConnect(endpoint + urlencode({"model": cfg.rt_model}),
                    additional_headers={"Authorization": "Bearer " + cfg.rt_api_key.get_secret_value()},
                    proxy=None, close_timeout=2, max_size=4*1024*1024)
                if json.loads(await self.ws.recv()).get("type") != "session.created":
                    raise ValueError()
                session_config = {
                    "modalities": ["text","audio"], "voice": cfg.rt_voice, "instructions": build_system_prompt(cfg, "voice", [], None),
                    "audio": {"input": {"format": {"type":"pcm","sample_rate":16000}},
                              "output": {"format": {"type":"pcm","sample_rate":24000}}},
                    "input_audio_transcription": {"model":"qwen3-asr-flash-realtime"},
                    "turn_detection": None if self.manual else {"type":"server_vad"}}
                if cfg.rt_model == "qwen3.8-omni-flash-realtime":
                    session_config["audio"]["output"]["voice"] = session_config.pop("voice")
                if self.tool_context.allowed:
                    session_config["tools"] = self.tool_context.registry.definitions(nested=cfg.rt_provider == "bailian")
                    session_config["instructions"] = self.tool_instructions()
                await self.send("session.update", session=session_config)
                if json.loads(await self.ws.recv()).get("type") != "session.updated":
                    raise ValueError()
                self.service.rebuild_context(self.session, cfg.history_turns)
                for message in self.session.messages:
                    role = message["role"]
                    await self.send("conversation.item.create", item={"type":"message","role":role,
                        "content":[{"type":"input_text" if role=="user" else "text","text":message["content"]}]})
        except Exception:
            await self.close()
            raise ProviderError(502,"realtime_connect","百炼连接失败，请检查北京业务空间、密钥、模型和音色。") from None
        if self.session.lock.locked() or self.session.active_task or self.service.sessions.get(self.sid) is not self.session:
            await self.close()
            raise ProviderError(409,"session_busy","该会话正在使用中。")
        self.reader = asyncio.create_task(self.receive())
        self.session.active_task = self.reader
        self.session.active_turn_id = self.turn_id
        await self.emit("ready", {"session_id":str(self.sid),"turn_id":str(self.turn_id)})

    async def append(self, pcm):
        if self.ws and not self.input_closed and not self.reader.done():
            self.audio_sent = True
            await self.send("input_audio_buffer.append", audio=base64.b64encode(pcm).decode())

    async def finish(self):
        if self.input_closed or not self.audio_sent or self.reader.done():
            return
        self.input_closed = True
        if self.manual:
            await self.send("input_audio_buffer.commit")
            await self.send("response.create")
        else:
            await self.send("input_audio_buffer.append", audio=base64.b64encode(bytes(32000)).decode())

    async def receive(self):
        kind = "awaiting_event"
        try:
            while True:
                try:
                    kind = "awaiting_event"
                    event = json.loads(await asyncio.wait_for(self.ws.recv(), 30 if self.saved else 150))
                except TimeoutError:
                    if self.saved:
                        await self.emit("idle", {})
                        return
                    raise
                kind = event.get("type")
                if kind == "input_audio_buffer.speech_started":
                    if self.begun and self.continuous:
                        await self.audio.close()
                        if self.tool_task:
                            self.tool_task.cancel()
                            await asyncio.gather(self.tool_task, return_exceptions=True)
                            self.tool_task = None
                        self.pending_tools.clear()
                        if self.active_response:
                            self.ignore_responses.add(self.active_response)
                        await self.persist("interrupted")
                        self.turn_id = uuid4()
                        self.tool_context = self.service.tool_context(self.sid, self.turn_id, self.source)
                        self.required_controls.clear()
                        self.pending_audio.clear()
                        self.held_text = False
                        self.control_failure = None
                        self.control_plan_cache = None
                        self.control_continuation = False
                        self.control_notice = ""
                        self.order_guard.reset_turn()
                        self.tool_rounds = 0
                        self.model_results = []
                        self.usage = None
                        await self.refresh_tools()
                        self.started = monotonic()
                        self.session.active_turn_id = self.turn_id
                        self.previous_item = self.item
                        self.reply = self.user = ""
                        self._response_text = ""
                        self._transcript_seq = 0
                        self.saved = self.response_done = False
                        self.active_response = None
                        await self.emit("next", {"session_id":str(self.sid),"turn_id":str(self.turn_id)})
                    self.item = event.get("item_id")
                    self.begun = True
                rid = event.get("response_id") or (event.get("response") or {}).get("id")
                if (rid and rid in self.ignore_responses) or (self.previous_item and event.get("item_id")==self.previous_item):
                    continue
                if kind == "response.created":
                    self.active_response = rid
                    self._start_response_segment()
                if kind == "error":
                    raise ValueError()
                if kind in {"input_audio_buffer.speech_stopped","input_audio_buffer.committed"}:
                    if not self.continuous:
                        self.input_closed = True
                    await self.emit("thinking", {})
                elif kind == "conversation.item.input_audio_transcription.completed":
                    self.user = event.get("transcript","")
                    self.tool_context.question = self.user
                    self.tool_context.begin_order_turn(self.user, self.session.history)
                    self.order_guard.begin(self.user, self.tool_context.allowed)
                    self.control_plan_cache = control_plan(self.user, self.session.messages)
                    self.required_controls = {action["tool"] for action in self.control_plan_cache}

                    # Check for conversation end intent
                    if _is_end_intent(self.user):
                        if self.active_response:
                            self.ignore_responses.add(self.active_response)
                        await self.audio.close()
                        await self.send("session.update", session={"turn_detection": None})
                        await self.emit("notice", "好的，我先休息了")
                        await self.emit("idle", {"reason": "end_intent"})
                        return

                    await self.refresh_tools()
                    await self.emit("user",self.user)
                    await self.release_output()
                elif kind == "conversation.item.input_audio_transcription.failed":
                    raise ValueError()
                elif kind == "response.audio_transcript.delta":
                    self._note_early_output()
                    self._append_transcript_delta(event["delta"])
                    if self.output_blocked():
                        self.held_text = True
                    else:
                        await self.release_output()
                        await self.emit("text",self.reply)
                elif kind == "response.audio_transcript.done":
                    self._finalize_response_transcript(event.get("transcript") or "")
                    if self.output_blocked():
                        self.held_text = True
                elif kind == "response.audio.delta":
                    self._note_early_output()
                    pcm = base64.b64decode(event["delta"])
                    if self.output_blocked():
                        self.pending_audio.append(pcm)
                    else:
                        await self.audio.push(pcm)
                elif kind == "response.output_item.done" and event.get("item", {}).get("type") == "function_call":
                    item = event["item"]
                    self.pending_tools[item["call_id"]] = item
                elif kind == "response.function_call_arguments.done":
                    self.pending_tools.setdefault(event["call_id"], {}).update(event)
                elif kind == "response.done":
                    if self.continuous and event["response"].get("status") == "cancelled":
                        continue
                    if event["response"].get("status") != "completed":
                        raise ValueError()
                    for item in event["response"].get("output", []):
                        if item.get("type") == "function_call":
                            self.pending_tools[item["call_id"]] = item
                    usage = event["response"].get("usage") or {}
                    counts = TokenUsage(prompt_tokens=usage.get("input_tokens"),completion_tokens=usage.get("output_tokens"),
                                        total_tokens=usage.get("total_tokens")) if usage else None
                    result = Completion(self.reply or None, counts, "tool_calls" if self.pending_tools else "stop")
                    self.model_results.append(result)
                    self.usage = combine_usage(self.model_results)
                    cfg = self.config.model_copy(update={"model":self.config.rt_model,"provider":self.provider,"max_tokens":None})
                    self.service.record(self.session,self.sid,counts,None,True,None,monotonic()-self.started,cfg,result)
                    if self.pending_tools:
                        if self.control_continuation:
                            for call_id in self.pending_tools:
                                await self.send("conversation.item.create", item={"type": "function_call_output",
                                    "call_id": call_id, "output": json.dumps({"error": "control_continuation_no_tools",
                                    "message": "本次仅播报真实结果，未执行工具。", "executed": False}, ensure_ascii=False)})
                            await self.finish_notice_as_text()
                            if not self.continuous or self.input_closed:
                                return
                            continue
                        clarification = next((action for action in self.control_plan_cache or ()
                                              if action["kind"] == "clarify"), None)
                        if clarification:
                            honest = self._clarify_text(clarification["tool"])
                            for call_id in self.pending_tools:
                                await self.send("conversation.item.create", item={"type": "function_call_output",
                                    "call_id": call_id, "output": json.dumps({"error": "control_clarification_required",
                                    "message": honest, "executed": False}, ensure_ascii=False)})
                            self.pending_tools.clear()
                            if await self.continue_in_session(honest):
                                continue
                            await self.finish_notice_as_text()
                            if not self.continuous or self.input_closed:
                                return
                            continue
                        if self.tool_rounds >= MAX_TOOL_ROUNDS:
                            raise ValueError("tool_limit")
                        self.tool_rounds += 1
                        items = list(self.pending_tools.values())
                        self.pending_tools.clear()
                        self.tool_task = asyncio.create_task(self.run_tools(items, self.turn_id, self.tool_context))
                        continue
                    self.order_guard.finish_without_tools()
                    self.response_done = True
                if self.response_done and self.user and not self.saved:
                    error = None if self.control_continuation else self.tool_context.control_error(self.required_controls, self.reply)
                    if error:
                        status = None
                        if self.required_controls and error.code == "control_not_executed":
                            status = await self.server_execute_explicit()
                        if status == "clarify":
                            error = None
                            honest = self.reply
                        elif status == "fail":
                            honest = self.reply
                        elif status == "ok":
                            error = self.tool_context.control_error(self.required_controls, self.reply)
                            honest = error.message if error else self.reply
                        else:
                            honest = error.message
                        self.control_failure = error.code if error else None
                        if await self.continue_in_session(honest):
                            continue
                        await self.finish_notice_as_text()
                    else:
                        await self.release_output()
                        await self.audio.finish()
                        await self.persist("failed" if self.control_failure else "complete", audio_status="streamed")
                        await self.emit("done",{"reply":self.reply,"session_id":str(self.sid),"turn_id":str(self.turn_id),
                            "model":self.config.rt_model,"provider":self.provider,"usage":self.usage.model_dump() if self.usage else None,"audio_status":"streamed",
                            "history_persisted":self.session.history_persisted,
                            "order_guard_early_output": self.order_guard.early_output,
                            "order_guard_discarded": self.order_guard.discarded,
                            "order_guard_discarded_text_chars": self.order_guard.discarded_text_chars,
                            "order_guard_discarded_audio_bytes": self.order_guard.discarded_audio_bytes,
                            "sources":self.tool_context.sources(),"tool_calls":self.tool_context.summaries()})
                    if not self.continuous or self.input_closed:
                        return
        except asyncio.CancelledError:
            logger.info("realtime_receive_cancelled event=%s turn_id=%s", kind, self.turn_id, exc_info=True)
            raise
        except Exception as error:
            self.input_closed = True
            logger.exception("realtime_receive_failed event=%s error_type=%s turn_id=%s",
                             kind, type(error).__name__, self.turn_id)
            if self.control_continuation and self.control_notice and not self.saved:
                await self.finish_notice_as_text()
            else:
                message = ("百炼实时连接中断，请重新发起对话。"
                           if isinstance(error, (ConnectionClosed, TimeoutError, OSError))
                           else "服务端实时语音处理失败，请重新发起对话；具体原因已记录到后端日志。")
                await self.emit("error", message)
        finally:
            # Stop new appends before cleanup awaits: the device may still be streaming.
            self.input_closed = True
            if self.tool_task:
                self.tool_task.cancel()
                await asyncio.gather(self.tool_task, return_exceptions=True)
            self.pending_audio.clear()
            await self.audio.close()
            if self.session.active_task is asyncio.current_task():
                self.session.active_task = self.session.active_turn_id = None
            await self.ws.close()
            if not self.saved:
                await self.persist("interrupted")

    async def run_tools(self, items, turn_id, context):
        try:
            if self.control_continuation:
                return
            if self.required_controls or self.held_text:
                await self.audio.finish()
            outputs = []
            for item in items:
                if self.turn_id != turn_id:
                    return
                output = await context.execute(item.get("name", ""), item.get("arguments", "{}"), item["call_id"])
                outputs.append(output)
                if self.turn_id != turn_id:
                    return
                await self.send("conversation.item.create", item={
                    "type": "function_call_output", "call_id": item["call_id"],
                    "output": function_call_output_payload(output),
                })
                context.mark_sent([item["call_id"]])
            if self.turn_id != turn_id:
                return
            guard_result = self.order_guard.finish_tool_outputs(outputs)
            if guard_result == "discard":
                # 订单编号未确认：首响应里的“这就去查/错误编号”不播；确认问句由后续响应生成。
                self.order_guard.mark_discarded(len(self.reply or ""), sum(len(item) for item in self.pending_audio))
                self.pending_audio.clear()
                self.held_text = False
                self.reply = ""
                self._response_text = ""
            elif guard_result == "release":
                await self.release_output()
            await self.refresh_tools()
            self.pending_audio.clear()
            if self.required_controls or self.held_text:
                self.reply = ""
                self.held_text = False
            await self.audio.finish()
            if self.turn_id != turn_id:
                return
            await self.send("response.create")
        except (ConnectionClosed, OSError, ValueError, RuntimeError):
            if self.reader and self.reader is not asyncio.current_task():
                self.reader.cancel()

    async def persist(self,status, audio_status=None):
        if self.saved or not (self.user or self.reply):
            return
        async with self.session.lock:
            if self.service.sessions.get(self.sid) is not self.session:
                return
            if not self.session.history:
                self.session.title = self.user[:40] or "语音对话"
            for role,content in (("user",self.user),("assistant",self.reply)):
                if content:
                    self.session.history.append(TranscriptMessage(role=role,content=content,source=self.source,
                        turn_id=self.turn_id,model=self.config.rt_model,provider=self.provider,usage=self.usage if role=="assistant" else None,
                        status="complete" if role=="user" else status,
                        sources=self.tool_context.sources() if role=="assistant" else [],
                        tool_calls=self.tool_context.summaries() if role=="assistant" else [],
                        audio_status=(audio_status or ("streamed" if status=="complete" else "interrupted")) if role=="assistant" else None))
            self.session.updated_at = datetime.now(timezone.utc)
            self.service.rebuild_context(self.session,self.config.history_turns)
            self.service.persist(self.sid)
            self.saved = True
        self.tool_context.question = self.user
        if self.tool_context.calls or self.required_controls or self.control_failure:
            self.service.queue_tool_audit(self.tool_context, self.reply, status,
                                          self.control_failure or (None if status == "complete" else "interrupted"))

    async def close(self):
        if self.reader and self.reader is not asyncio.current_task():
            self.reader.cancel()
            await asyncio.gather(self.reader,return_exceptions=True)
        if self.ws:
            await self.ws.close()
