import asyncio
import base64
from collections import deque
from contextlib import suppress
import json
import logging
import re
from urllib.parse import urlencode
from uuid import UUID, uuid4
from time import monotonic

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from .ack_cache import pick_ack_pcm
from .audio_codec import resample_pcm16_mono
from .llm import Completion, ProviderError
from .schemas import TokenUsage
from .text_tool_selection import TextToolSelection
from .tool_dialogue import (MUTATING_CONTROL_TOOLS, combine_usage,
                            control_history,
                            control_plan, describe_control, turn_limits)
from .order_confirmation import RealtimeOrderGuard
from .speech_text import normalize_for_speech, function_call_output_payload
from .prompt_builder import build_system_prompt
from .audio_fx import RealtimeAudio
from .audit_store import redact_value


logger = logging.getLogger(__name__)

_ACK_TRIGGER_TOOLS = frozenset({
    "web_search", "search_personal_knowledge", "search_m5stack", "desktop_inspect_screen",
    "desktop_open", "desktop_gui_action", "desktop_run_command",
})

_WAKE_PREFIX = re.compile(r"^(?:(?:小?(?:塔|太)[菲妃]|小?菲|taffy)[，,、\s]*)+", re.I)
_TRAILING_PUNCT = re.compile(r"[。！!？?~～，,、.\s]+$")
_POLITE_PREFIX = re.compile(r"^(?:(?:好[的啦呀了]?|行[的啦呀了]?|先去?|请|你|那|快去?|赶紧|麻烦|可以了?)[，,、\s]*)+")
_POLITE_SUFFIX = re.compile(r"(?:[吧啦呀啊哦嘛了]|一下|好了|行吗|好吗)+$")
_EXACT_STOP_COMMANDS = {
    "闭嘴", "关机", "关闭", "关闭对话", "关闭聊天", "关闭语音", "关闭连接",
    "退下", "先退下", "退下休息", "闭口", "别说了", "不要说了", "停止说话", "别讲了", "不讲了",
    "别念了", "停止播报", "停下", "先休息吧", "去休息吧", "你先休息",
    "退出", "退出对话", "退出聊天", "待机", "进入待机", "去待机", "先待机",
    "休息", "去休息", "先休息", "休眠", "结束",
}
_POLITE_GOODBYE_COMMANDS = {"再见", "拜拜", "不聊了", "不说了", "先这样", "结束对话", "结束聊天"}
_QUESTION_MARKERS = re.compile(r"[吗？?]|怎么|什么|为什么|哪个|几|意思")


def _is_end_intent(text: str) -> bool:
    """仅识别明确指向结束本轮对话的短指令，避免误伤包含“结束/不用”的正常句子。"""
    if not text:
        return False
    raw = text.strip().lower()
    if _QUESTION_MARKERS.search(raw):
        return False
    cleaned = _TRAILING_PUNCT.sub("", raw)
    cleaned = _WAKE_PREFIX.sub("", cleaned).strip()
    cleaned = _POLITE_PREFIX.sub("", cleaned).strip()
    cleaned_no_suffix = _TRAILING_PUNCT.sub("", _POLITE_SUFFIX.sub("", cleaned)).strip()
    if cleaned in _EXACT_STOP_COMMANDS or cleaned_no_suffix in _EXACT_STOP_COMMANDS:
        return True
    if len(cleaned_no_suffix) <= 8 and (cleaned in _POLITE_GOODBYE_COMMANDS or cleaned_no_suffix in _POLITE_GOODBYE_COMMANDS):
        return True
    return False


def is_qwen_audio_realtime(model: str) -> bool:
    return (model or "").strip().lower().startswith("qwen-audio-")


class DirectConnect(connect):
    def process_redirect(self, exc):
        return exc


class RealtimeTurn:
    def __init__(self, service, session_id, source, emit, manual, *, config=None):
        self.service = service
        self.config = service.settings if config is None else config
        self.sid = session_id or service.new_session()
        self.session = service.get_session(self.sid)
        self.provider = "百炼" if self.config.rt_provider=="bailian" else "Omni 兼容接口"
        self.usage = None
        self.started = monotonic()
        self.first_audio_ms: int | None = None
        self.source = source
        self.emit = emit
        self.manual = manual
        self.ws_opened_at: float = monotonic()
        self.turns_in_ws: int = 0
        self._defer_response: bool = bool(getattr(self.config, "rt_defer_response_until_transcript", False)) and not self.manual
        self._voice_tool_selection: TextToolSelection | None = None
        self._awaiting_session_update_turn_id: UUID | None = None
        self._session_update_acks: deque[UUID | None] = deque()
        self.turn_id = uuid4()
        self.ws = None
        self.reader = None
        self.committed = False
        self.user = ""
        self.transcription_done = False
        self.transcription_ready = asyncio.Event()
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
        self._compatible_ga = False

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

    def _uses_native_web_search(self) -> bool:
        allowed = getattr(getattr(self, "tool_context", None), "allowed", None) or set()
        return (
            self.config.rt_provider == "bailian"
            and is_qwen_audio_realtime(self.config.rt_model)
            and "web_search" in allowed
        )

    def _realtime_tool_definitions(self, nested=False):
        if self._voice_tool_selection is not None:
            defs = self._voice_tool_selection.definitions(nested=nested)
        else:
            registry = getattr(self.tool_context, "registry", None)
            if registry is None:
                return []
            gateway = getattr(self.tool_context, "tool_gateway", None)
            defs = (gateway.definitions(registry, nested=nested, include_side_effects=True)
                    if gateway is not None else registry.definitions(nested=nested))
        if self._uses_native_web_search():
            defs = [item for item in defs if item.get("function", item).get("name") != "web_search"]
        return defs

    def tool_instructions(self):
        turn_state = "最近控制调用记录（仅供核对历史，不代表当前设备值）：" + control_history(self.session.history)
        if self.required_controls:
            turn_state += "\n本轮必须先实际执行这些工具再答复：" + ", ".join(sorted(self.required_controls))
        order_state = self.tool_context.order_state_text()
        if order_state:
            turn_state += "\n" + order_state
        if self._voice_tool_selection is not None:
            turn_state += self._voice_tool_selection.instructions()
        max_rounds, _ = turn_limits(getattr(self.tool_context, "allowed", None))
        tool_names = ([item.get("function", item)["name"] for item in self._realtime_tool_definitions()]
                      if getattr(self.tool_context, "registry", None)
                      and self.tool_rounds < max_rounds and not self.control_continuation else [])
        return build_system_prompt(
            self.config, "voice", tool_names, turn_state,
            native_search=self._uses_native_web_search(),
        )

    async def refresh_tools(self, *, response_turn_id: UUID | None = None):
        max_rounds, _ = turn_limits(getattr(self.tool_context, "allowed", None))
        session_patch: dict = {
            "tools": self._realtime_tool_definitions(nested=self.config.rt_provider == "bailian")
                     if getattr(self.tool_context, "registry", None)
                     and self.tool_rounds < max_rounds and not self.control_continuation else [],
            "instructions": self.tool_instructions(),
        }
        if self._compatible_ga:
            session_patch["type"] = "realtime"
        await self.send("session.update", session=session_patch, response_turn_id=response_turn_id)

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
        self._awaiting_session_update_turn_id = None
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
        session_patch: dict = {
            "tools": [],
            "instructions": build_system_prompt(self.config, "voice", [], turn_state=(
                "仅用当前声音简短播报本轮服务端提供的真实结果、错误或澄清问题。"
                "不得再次执行工具；失败或尚未执行时绝不能说已设置成功，不得更改或猜测数值。")),
        }
        if self._compatible_ga:
            session_patch["type"] = "realtime"
        await self.send("session.update", session=session_patch)
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
            "elapsed_ms": int(max(0.0, monotonic() - self.started) * 1000) if getattr(self, "started", None) is not None else None,
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

    async def send(self, kind, *, response_turn_id: UUID | None = None, **fields):
        if self._defer_response and kind == "session.update":
            # Acknowledgments arrive in send order, including updates that do not start a response.
            self._session_update_acks.append(response_turn_id)
        await self.ws.send(json.dumps({"type": kind, "event_id": uuid4().hex, **fields}))

    def _build_session_config(self, created_session: dict | None = None) -> dict:
        cfg = self.config
        instructions = build_system_prompt(cfg, "voice", [], None)
        turn_detection: dict[str, str | bool] | None = None if self.manual else {"type": "server_vad"}
        if turn_detection is not None and self._defer_response:
            turn_detection.update({"create_response": False, "interrupt_response": True})
        if cfg.rt_provider == "bailian":
            asr_model = cfg.rt_asr_model.strip() if hasattr(cfg, "rt_asr_model") else ""
            if is_qwen_audio_realtime(cfg.rt_model):
                if not asr_model or asr_model in {"whisper-1", "qwen3-asr-flash-realtime"}:
                    asr_model = "fun-asr"
                session_config: dict = {
                    "modalities": ["text", "audio"],
                    "voice": (cfg.rt_voice or "").strip() or "longanqian_v3.1",
                    "input_audio_format": "pcm",
                    "output_audio_format": "pcm",
                    "instructions": instructions,
                    "input_audio_transcription": {"model": asr_model, "language": "zh"},
                    "turn_detection": turn_detection,
                }
                if self._uses_native_web_search():
                    session_config["enable_search"] = True
                    session_config["search_options"] = {"enable_source": True}
                return session_config
            if not asr_model or asr_model == "whisper-1":
                asr_model = "qwen3-asr-flash-realtime"
            session_config = {
                "modalities": ["text", "audio"],
                "voice": cfg.rt_voice,
                "instructions": instructions,
                "audio": {
                    "input": {"format": {"type": "pcm", "sample_rate": 16000}},
                    "output": {"format": {"type": "pcm", "sample_rate": 24000}},
                },
                "input_audio_transcription": {"model": asr_model},
                "turn_detection": turn_detection,
            }
            if cfg.rt_model == "qwen3.8-omni-flash-realtime":
                session_config["audio"]["output"]["voice"] = session_config.pop("voice")
            return session_config

        is_ga = isinstance(created_session, dict) and "audio" in created_session and "input_audio_format" not in created_session
        self._compatible_ga = is_ga
        asr_model = (getattr(cfg, "rt_asr_model", "") or "whisper-1").strip()
        if is_ga:
            input_cfg: dict = {
                "format": {"type": "audio/pcm", "rate": 24000},
                "turn_detection": turn_detection,
            }
            if asr_model:
                input_cfg["transcription"] = {"model": asr_model}
            return {
                "type": "realtime",
                "instructions": instructions,
                "audio": {
                    "input": input_cfg,
                    "output": {
                        "format": {"type": "audio/pcm", "rate": 24000},
                        "voice": cfg.rt_voice,
                    },
                },
            }
        session_config = {
            "modalities": ["text", "audio"],
            "voice": cfg.rt_voice,
            "instructions": instructions,
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "turn_detection": turn_detection,
        }
        if asr_model:
            session_config["input_audio_transcription"] = {"model": asr_model}
        return session_config

    def should_rotate_ws(self) -> bool:
        if not self.continuous or self.manual:
            return False
        max_turns = int(getattr(self.config, "rt_max_continuous_turns", 0) or 0)
        max_secs = int(getattr(self.config, "rt_max_continuous_seconds", 0) or 0)
        return ((max_turns > 0 and self.turns_in_ws >= max_turns)
                or (max_secs > 0 and monotonic() - self.ws_opened_at >= max_secs))

    def _session_busy(self) -> bool:
        return (self.session.lock.locked() or self.session.active_task is not None
                or self.service.sessions.get(self.sid) is not self.session)

    async def open(self):
        cfg = self.config
        if cfg.rt_provider == "bailian":
            address = (f"wss://{cfg.rt_workspace}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime"
                       if cfg.rt_workspace else "wss://dashscope.aliyuncs.com/api-ws/v1/realtime")
        else:
            address = cfg.rt_endpoint
        if not address or not cfg.rt_api_key.get_secret_value():
            msg = ("请在 API 接入 → 语音对话填写业务空间 ID 和 API Key。"
                   if cfg.rt_provider == "bailian" else "请在 API 接入 → 实时接口填写 WSS 地址和 API Key。")
            raise ProviderError(422, "realtime_config", msg)
        if "model=" in address:
            endpoint = address
        else:
            sep = "&" if "?" in address else "?"
            endpoint = address + sep + urlencode({"model": cfg.rt_model})
        if self._session_busy():
            raise ProviderError(409,"session_busy","该会话正在使用中。")
        try:
            for attempt in range(2):
                try:
                    async with asyncio.timeout(15):
                        self.ws = await DirectConnect(
                            endpoint,
                            additional_headers={"Authorization": "Bearer " + cfg.rt_api_key.get_secret_value()},
                            proxy=None, close_timeout=2, max_size=4 * 1024 * 1024,
                        )
                        created = json.loads(await self.ws.recv())
                        if created.get("type") != "session.created":
                            raise ValueError()
                        session_config = self._build_session_config(created.get("session"))
                        if self._defer_response:
                            session_config["tools"] = []
                        elif self.tool_context.allowed and self.tool_context.registry is not None:
                            session_config["tools"] = self._realtime_tool_definitions(nested=cfg.rt_provider == "bailian")
                            session_config["instructions"] = self.tool_instructions()
                        await self.send("session.update", session=session_config)
                        if json.loads(await self.ws.recv()).get("type") != "session.updated":
                            raise ValueError()
                        if self._defer_response:
                            self._session_update_acks.popleft()
                    break
                except (ConnectionClosed, TimeoutError, OSError):
                    if self.ws is not None:
                        with suppress(ConnectionClosed, TimeoutError, OSError):
                            await self.ws.close()
                        self.ws = None
                    self._session_update_acks.clear()
                    if attempt:
                        raise
                    await asyncio.sleep(0.4)
            self.ws_opened_at = monotonic()
            async with asyncio.timeout(15):
                self.service.rebuild_context(self.session, cfg.history_turns)
                for message in self.session.messages:
                    role = message["role"]
                    await self.send("conversation.item.create", item={"type":"message","role":role,
                        "content":[{"type":"input_text" if role=="user" else "text","text":message["content"]}]})
        except Exception:
            await self.close()
            error_msg = ("百炼连接失败，请检查北京业务空间、密钥、模型和音色。"
                         if cfg.rt_provider == "bailian"
                         else "实时语音连接失败，请检查接口地址、密钥、模型和音色。")
            raise ProviderError(502, "realtime_connect", error_msg) from None
        if self._session_busy():
            await self.close()
            raise ProviderError(409,"session_busy","该会话正在使用中。")
        self.reader = asyncio.create_task(self.receive())
        self.session.active_task = self.reader
        self.session.active_turn_id = self.turn_id
        await self.emit("ready", {"session_id":str(self.sid),"turn_id":str(self.turn_id)})

    async def append(self, pcm):
        if self.ws and not self.input_closed and self.reader is not None and not self.reader.done():
            self.audio_sent = True
            payload = pcm if self.config.rt_provider == "bailian" else resample_pcm16_mono(pcm, 16000, 24000)
            await self.send("input_audio_buffer.append", audio=base64.b64encode(payload).decode())

    async def finish(self):
        if self.input_closed or not self.audio_sent or (self.reader is not None and self.reader.done()):
            return
        self.input_closed = True
        if self.manual:
            await self.send("input_audio_buffer.commit")
            await self.send("response.create")
        else:
            silence_bytes = 32000 if self.config.rt_provider == "bailian" else 48000
            await self.send("input_audio_buffer.append", audio=base64.b64encode(bytes(silence_bytes)).decode())

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
                    self._awaiting_session_update_turn_id = None
                    self._voice_tool_selection = None
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
                        if not self._defer_response:
                            await self.refresh_tools()
                        self.started = monotonic()
                        self.first_audio_ms = None
                        self.session.active_turn_id = self.turn_id
                        self.previous_item = self.item
                        self.reply = self.user = ""
                        self.transcription_done = False
                        self.transcription_ready.clear()
                        self._response_text = ""
                        self._transcript_seq = 0
                        self.saved = self.response_done = False
                        self.active_response = None
                        await self.emit("next", {"session_id":str(self.sid),"turn_id":str(self.turn_id)})
                    elif not self.begun:
                        self.saved = False
                    self.item = event.get("item_id")
                    self.begun = True
                rid = event.get("response_id") or (event.get("response") or {}).get("id")
                if (rid and rid in self.ignore_responses) or (self.previous_item and event.get("item_id")==self.previous_item):
                    continue
                if kind == "response.created":
                    self.active_response = rid
                    self._start_response_segment()
                if kind == "error":
                    raise self.upstream_error(event)
                if kind in {"input_audio_buffer.speech_stopped","input_audio_buffer.committed"}:
                    if not self.continuous:
                        self.input_closed = True
                    await self.emit("thinking", {})
                elif kind == "conversation.item.input_audio_transcription.completed":
                    self.user = event.get("transcript","")
                    self.transcription_done = True
                    self.tool_context.question = self.user
                    self.tool_context.begin_order_turn(self.user, self.session.history)
                    self.order_guard.begin(self.user, self.tool_context.allowed)
                    self.control_plan_cache = control_plan(self.user, self.session.messages)
                    self.required_controls = {action["tool"] for action in self.control_plan_cache}
                    self.transcription_ready.set()

                    # Check for conversation end intent
                    if _is_end_intent(self.user):
                        if self.active_response:
                            self.ignore_responses.add(self.active_response)
                            with suppress(ConnectionClosed, OSError, RuntimeError):
                                await self.send("response.cancel")
                        self.pending_tools.clear()
                        self.pending_audio.clear()
                        self.reply = ""
                        self.saved = True
                        await self.audio.close()
                        with suppress(ConnectionClosed, OSError, RuntimeError):
                            await self.send("session.update", session={"turn_detection": None})
                        await self.emit("notice", "好的，我先休息了")
                        await self.emit("idle", {"reason": "end_intent"})
                        return

                    if self._defer_response:
                        if (getattr(self.tool_context, "registry", None) is not None
                                and len(self.tool_context.definitions()) > 5):
                            self._voice_tool_selection = TextToolSelection(self.tool_context)
                        self._awaiting_session_update_turn_id = self.turn_id
                        await self.refresh_tools(response_turn_id=self.turn_id)
                    else:
                        await self.refresh_tools()
                    await self.emit("user",self.user)
                    await self.release_output()
                elif kind == "session.updated":
                    if self._defer_response and self._session_update_acks:
                        acknowledged_turn = self._session_update_acks.popleft()
                        if acknowledged_turn == self._awaiting_session_update_turn_id == self.turn_id:
                            self._awaiting_session_update_turn_id = None
                            if not self.saved and not self.response_done:
                                await self.send("response.create")
                elif kind == "conversation.item.input_audio_transcription.failed":
                    raise self.upstream_error(event)
                elif kind in {
                    "response.audio_transcript.delta",
                    "response.output_audio_transcript.delta",
                    "response.text.delta",
                    "response.output_text.delta",
                }:
                    self._note_early_output()
                    self._append_transcript_delta(event.get("delta", ""))
                    if self.output_blocked():
                        self.held_text = True
                    else:
                        await self.release_output()
                        await self.emit("text", self.reply)
                elif kind in {"response.audio_transcript.done", "response.output_audio_transcript.done"}:
                    self._finalize_response_transcript(event.get("transcript") or "")
                    if self.output_blocked():
                        self.held_text = True
                elif kind in {"response.audio.delta", "response.output_audio.delta"}:
                    self._note_early_output()
                    if getattr(self, "first_audio_ms", None) is None and getattr(self, "started", None) is not None:
                        self.first_audio_ms = int(max(0.0, monotonic() - self.started) * 1000)
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
                    logger.info("realtime_response_done %s", json.dumps({
                        "session_id": str(self.sid), "turn_id": str(self.turn_id),
                        "response_id": rid, "status": event["response"].get("status"),
                        "status_reason": (event["response"].get("status_details") or {}).get("reason"),
                        "transcript_chars": len(self._response_text),
                        "response_segments": self._transcript_seq,
                    }, ensure_ascii=False))
                    if self.continuous and event["response"].get("status") == "cancelled":
                        continue
                    if event["response"].get("status") != "completed":
                        raise self.upstream_error(event)
                    for item in event["response"].get("output", []):
                        if item.get("type") == "function_call":
                            self.pending_tools[item["call_id"]] = item
                    usage = event["response"].get("usage") or {}
                    counts = TokenUsage.from_provider(usage) if usage else None
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
                        max_rounds, _ = turn_limits(getattr(self.tool_context, "allowed", None))
                        if self.tool_rounds >= max_rounds:
                            raise ValueError("tool_limit")
                        self.tool_rounds += 1
                        items = list(self.pending_tools.values())
                        self.pending_tools.clear()
                        self.tool_task = asyncio.create_task(self.run_tools(items, self.turn_id, self.tool_context))
                        continue
                    self.order_guard.finish_without_tools()
                    self.response_done = True
                if self.response_done and self.transcription_done and not self.saved:
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
                            "elapsed_ms": int(max(0.0, monotonic() - self.started) * 1000) if getattr(self, "started", None) is not None else None,
                            "history_persisted":self.session.history_persisted,
                            "order_guard_early_output": self.order_guard.early_output,
                            "order_guard_discarded": self.order_guard.discarded,
                            "order_guard_discarded_text_chars": self.order_guard.discarded_text_chars,
                            "order_guard_discarded_audio_bytes": self.order_guard.discarded_audio_bytes,
                            "sources":self.tool_context.sources(),"tool_calls":self.tool_context.summaries()})
                        self.turns_in_ws += 1
                        if self.saved and not self.input_closed and self.should_rotate_ws():
                            self.input_closed = True
                            await self.emit("rotate_session", {"session_id": str(self.sid), "turns": self.turns_in_ws})
                            return
                    if not self.continuous or self.input_closed:
                        return
        except asyncio.CancelledError:
            logger.info("realtime_receive_cancelled event=%s turn_id=%s", kind, self.turn_id, exc_info=True)
            raise
        except Exception as error:
            idle_disconnect = (isinstance(error, (ConnectionClosed, OSError)) and self.source == "device_voice"
                               and self.continuous and self.saved and not self.input_closed)
            self.input_closed = True
            logger.exception("realtime_receive_failed event=%s error_type=%s turn_id=%s",
                             kind, type(error).__name__, self.turn_id)
            if idle_disconnect:
                await self.emit("upstream_closed", {})
            elif self.control_continuation and self.control_notice and not self.saved:
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

    def upstream_error(self, event):
        response = event.get("response") or {}
        details = {
            "session_id": str(self.sid), "turn_id": str(self.turn_id),
            "event": event.get("type"), "event_id": event.get("event_id"),
            "request_id": event.get("request_id"), "response_id": event.get("response_id") or response.get("id"),
            "error": event.get("error"), "status": response.get("status"),
            "status_details": response.get("status_details"),
        }
        secrets = [self.config.rt_api_key.get_secret_value(),
                   self.config.api_key.get_secret_value(), self.config.tts_api_key.get_secret_value()]
        secrets.extend(getattr(self.tool_context, "secrets", ()))
        return ProviderError(502, "realtime_upstream_error",
                             json.dumps(redact_value(details, secrets), ensure_ascii=False))

    async def run_tools(self, items, turn_id, context):
        try:
            if self.control_continuation:
                return
            if self.required_controls or self.held_text:
                await self.audio.finish()
            if (self.turn_id == turn_id and self.config.rt_provider == "bailian"
                    and getattr(self.config, "rt_ack_enabled", True) and self.tool_rounds == 1
                    and not self.reply.strip() and self.first_audio_ms is None
                    and any(item.get("name") in _ACK_TRIGGER_TOOLS for item in items)
                    and not self.output_blocked()):
                ack_pcm = pick_ack_pcm(self.config.rt_voice)
                if ack_pcm:
                    for offset in range(0, len(ack_pcm), 4800):
                        await self.audio.push(ack_pcm[offset:offset + 4800])
                    await self.audio.finish()
            outputs = []
            for item in items:
                if item.get("name") in MUTATING_CONTROL_TOOLS:
                    await self.transcription_ready.wait()
                if self.turn_id != turn_id:
                    return
                if self.source == "device_voice":
                    await self.emit("activity", {"state": "searching", "turn_id": str(turn_id)})
                output = await context.execute(item.get("name", ""), item.get("arguments", "{}"), item["call_id"])
                outputs.append(output)
                if self.turn_id != turn_id:
                    return
                if self.source == "device_voice":
                    call = context.calls[-1]
                    if call.get("error_code") in {
                        "order_confirmation_required",
                        "order_confirmation_denied",
                        "confirmation_required",
                        "confirmation_denied",
                    }:
                        activity = "clarification"
                    elif (call["status"] == "ok" and (call.get("http_status") or 200) < 400
                          and not (isinstance(output, dict) and output.get("error"))
                          and (item.get("name") not in {"set_device_volume", "get_device_status"}
                               or isinstance(output, dict) and output.get("verified") is True)):
                        activity = "success"
                    else:
                        activity = "error"
                    await self.emit("activity", {"state": activity, "turn_id": str(turn_id)})
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

    async def persist(self, status, audio_status=None):
        if self.saved or not (self.user or self.reply):
            return
        elapsed_ms = int(max(0.0, monotonic() - self.started) * 1000)
        first_ms = getattr(self, "first_audio_ms", None)
        resolved_audio = audio_status or ("streamed" if status == "complete" else "interrupted")
        saved = await self.service.commit_external_turn(
            session_id=self.sid,
            turn_id=self.turn_id,
            source=self.source,
            user_text=self.user,
            reply_text=self.reply,
            provider=self.provider,
            model=self.config.rt_model,
            usage=self.usage,
            status=status,
            audio_status=resolved_audio,
            error_code=None if status == "complete" else "interrupted",
            elapsed_ms=elapsed_ms,
            first_audio_ms=first_ms,
            tool_context=self.tool_context,
            required_controls=self.required_controls,
            control_failure=self.control_failure,
            history_turns=self.config.history_turns,
            voice_mode="realtime",
            asr_provider=getattr(self.config, "rt_asr_model", None) or self.config.rt_provider,
            tts_provider=self.config.rt_provider,
        )
        if saved:
            self.saved = True

    async def close(self):
        if self.reader and self.reader is not asyncio.current_task():
            self.reader.cancel()
            await asyncio.gather(self.reader,return_exceptions=True)
        if self.ws:
            await self.ws.close()
