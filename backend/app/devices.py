"""Small, authenticated Xiaozhi device bridge. No audio inference or firmware writes."""
import asyncio
from contextlib import suppress
from datetime import datetime, timezone
from ipaddress import ip_address
import json
import logging
import os
from pathlib import Path
import re
import secrets
import socket
import tempfile
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .config import ROOT
from .llm import ProviderError
from .speech_bridge import SpeechRecognizer

MAX_FRAME_BYTES = 12000
# Only a stalled control channel reaches this; audio itself is driven by frames.
CONTROL_IDLE_SECONDS = 180
logger = logging.getLogger(__name__)


class DeviceSetup(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    lan_host: str = ""
    device_id: str = ""
    original_ota_url: str = Field(max_length=1000)
    original_recorded: Literal[True]

    @field_validator("lan_host")
    @classmethod
    def local_ip(cls, value):
        value = value.strip()
        if not value:
            return ""
        address = ip_address(value)
        if address.version != 4 or not address.is_private or address.is_loopback or address.is_unspecified or address.is_multicast:
            raise ValueError("Use this computer's private LAN IPv4 address")
        return str(address)

    @field_validator("device_id")
    @classmethod
    def mac(cls, value):
        value = value.strip().lower().replace("-", ":")
        if not value:
            return value
        if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", value):
            raise ValueError("Enter the device MAC from its original console")
        return value

    @field_validator("original_ota_url")
    @classmethod
    def original_url(cls, value):
        value = value.strip()
        if not value:
            # An empty portal field means use the firmware's compiled default.
            return value
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("Save the original OTA URL shown by the device before switching")
        return value


class DevicePreferences(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    text: str = Field(default="已连接电脑服务", min_length=1, max_length=120)
    volume: int = Field(default=30, ge=0, le=100)
    brightness: int = Field(default=60, ge=10, le=100)
    theme: Literal["light", "dark"] = "dark"


class DeviceHub:
    def __init__(self, path: Path = ROOT / "data" / "devices.json", port: int = 8003,
                 public_origin: str = "", speech: SpeechRecognizer | None = None):
        self.path = path
        self.port = port
        self.public_origin = public_origin
        self.setup: DeviceSetup | None = None
        self.preferences = DevicePreferences()
        self.token = secrets.token_urlsafe(32)
        self.connection: DeviceConnection | None = None
        self.gateway_running = False
        self.last_bootstrap: str | None = None
        self.last_connected: str | None = None
        self.last_error: str | None = None
        self.last_application: dict | None = None
        self.last_status: dict | None = None
        self.speech = speech if speech is not None else SpeechRecognizer()
        self.last_utterance: dict | None = None
        self.last_realtime_latency: dict | None = None
        self.last_session: dict | None = None
        # The conversation loop is attached by the admin app, which owns the model and
        # TTS providers; the gateway can run without it (recognition only).
        self.voice = None
        self.lock = asyncio.Lock()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            self.setup = DeviceSetup.model_validate(data["setup"]) if data.get("setup") else None
            self.preferences = DevicePreferences.model_validate(data.get("preferences", {}))
            self.token = data["token"]
            if not isinstance(self.token, str) or len(self.token) < 32:
                raise ValueError("Invalid device authentication configuration")

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def persist(self, setup, preferences):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent,
                                             prefix="devices-", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump({"setup": setup.model_dump() if setup else None,
                           "preferences": preferences.model_dump(), "token": self.token}, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError:
            raise ProviderError(500, "device_store_failed", "设备配置保存失败，请检查项目 data 目录。") from None
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    async def configure(self, setup):
        async with self.lock:
            if not setup.lan_host and not self.public_origin:
                raise ProviderError(422, "device_host_required", "本地模式需要填写电脑的局域网 IP。")
            if self.connection:
                raise ProviderError(409, "device_connected", "请先断开设备，再修改接入信息。")
            self.persist(setup, self.preferences)
            self.setup = setup
            self.last_status = None
            self.last_application = None
            self.last_bootstrap = None
            return self.public()

    @property
    def origin(self):
        if self.public_origin:
            return self.public_origin
        if self.setup is not None and self.setup.lan_host:
            return f"http://{self.setup.lan_host}:{self.port}"
        return None

    @property
    def websocket_url(self):
        origin = self.origin
        if origin is None:
            return None
        scheme = "wss" if self.public_origin else "ws"
        return f"{scheme}://{urlsplit(origin).netloc}/xiaozhi/v1/"

    async def save_preferences(self, preferences):
        async with self.lock:
            self.persist(self.setup, preferences)
            self.preferences = preferences
            # Saving is independent of applying, and never pretends to change hardware.
            self.last_application = None
            return self.public()

    def public(self):
        connected = self.connection is not None
        candidates = []
        if not self.public_origin:
            with suppress(OSError):
                for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                    host = item[4][0]
                    addr = ip_address(host)
                    if addr.is_private and not addr.is_loopback and host not in candidates:
                        candidates.append(host)
        ota_url = f"{self.origin}/xiaozhi/ota/?key={self.token}" if self.setup and self.origin else None
        return {"gateway_running": self.gateway_running, "gateway_port": self.port,
                "public_origin": self.public_origin, "ota_url": ota_url,
                "lan_candidates": candidates,
                "setup": self.setup.model_dump() if self.setup else None,
                "preferences": self.preferences.model_dump(), "connected": connected,
                "ready": connected and self.connection.ready,
                "tools": sorted(self.connection.tools) if connected else [],
                "server_info": self.connection.server_info if connected else None,
                "last_bootstrap": self.last_bootstrap, "last_connected": self.last_connected,
                "last_error": self.last_error, "last_application": self.last_application,
                "device_status": self.last_status,
                "local_ota_url": ota_url,
                "speech": self.speech.public(), "last_utterance": self.last_utterance,
                "last_realtime_latency": self.last_realtime_latency,
                "last_session": self.last_session,
                "recovery": "恢复需要在设备配网页填回保存的原 OTA 地址；网页没有执行一键切回。"}

    def authorized(self, device_id, token):
        return (self.setup is not None and bool(self.setup.device_id) and device_id.lower() == self.setup.device_id
                and isinstance(token, str) and secrets.compare_digest(token, self.token))

    def describe_rejection(self, origin, device_id, token, version):
        """Explain a refused handshake without echoing the token itself."""
        expected = self.setup.device_id if self.setup else ""
        parts = []
        if origin is not None:
            parts.append("请求带了 Origin，非设备来源一律拒绝")
        if not expected:
            parts.append("本机尚未配对设备")
        elif device_id.lower() != expected:
            parts.append(f"设备标识不匹配（收到 {device_id or '空'}，本机配对 {expected}）")
        elif not token:
            parts.append("请求未携带 token")
        elif not secrets.compare_digest(token, self.token):
            parts.append("token 与本机不一致")
        if version != "1":
            parts.append(f"协议版本为 {version}")
        return "WebSocket 握手被拒绝：" + "；".join(parts or ["未识别的校验失败"])

    async def bootstrap_authorized(self, device_id, token):
        async with self.lock:
            if self.setup is None or not isinstance(token, str) or not secrets.compare_digest(token, self.token):
                return False
            if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", device_id.lower()):
                return False
            if not self.setup.device_id:
                paired = self.setup.model_copy(update={"device_id": device_id.lower()})
                self.persist(paired, self.preferences)
                self.setup = paired
            return self.authorized(device_id, token)

    async def apply(self):
        async with self.lock:
            conn = self.connection
            if conn is None or not conn.ready:
                raise ProviderError(409, "device_offline", "设备尚未建立控制连接，请接入后按一下设备按钮再重试。")
            pref = self.preferences
            self.last_application = {"at": self.now(), "state": "applying", "results": {}}
            results = self.last_application["results"]
            # Read original state before issuing any settings changes.
            try:
                before = await conn.call("self.get_device_status", {})
                self.last_status = before
                for label, tool, arguments in (
                    ("volume", "self.audio_speaker.set_volume", {"volume": pref.volume}),
                    ("brightness", "self.screen.set_brightness", {"brightness": pref.brightness}),
                    ("theme", "self.screen.set_theme", {"theme": pref.theme}),
                ):
                    if tool not in conn.tools:
                        results[label] = {"state": "unsupported"}
                        continue
                    result = await conn.call(tool, arguments)
                    results[label] = {"state": "acknowledged", "result": result}
                after = await conn.call("self.get_device_status", {})
                self.last_status = after
                expected = {"volume": ("audio_speaker", pref.volume),
                            "brightness": ("screen", pref.brightness), "theme": ("screen", pref.theme)}
                for label, (section, value) in expected.items():
                    item = results.get(label)
                    if item is None or item["state"] != "acknowledged":
                        continue
                    readback = after.get(section, {}).get(label) if isinstance(after, dict) and isinstance(after.get(section), dict) else None
                    item["readback"] = readback
                    item["state"] = "verified" if readback == value else "acknowledged" if readback is None else "mismatch"
                # Protocol-native on-screen assistant text; no synthesized audio involved.
                await conn.send({"type": "tts", "state": "sentence_start", "text": pref.text})
                results["text"] = {"state": "sent", "note": "协议没有屏幕文字回执，请查看实机屏幕。"}
                self.last_application["state"] = "completed_with_results"
                self.last_error = None
            except ProviderError as error:
                self.last_application["state"] = "failed"
                self.last_error = error.message
                raise
            return self.public()

    async def apply_volume(self):
        async with self.lock:
            connection = self.connection
            if connection is None or not connection.ready:
                raise ProviderError(409, "device_offline", "音量已保存，设备尚未连接。")
            if "self.audio_speaker.set_volume" not in connection.tools:
                raise ProviderError(422, "volume_unsupported", "设备未提供音量控制。")
            await connection.call("self.audio_speaker.set_volume", {"volume": self.preferences.volume})
            status = await connection.call("self.get_device_status", {})
            self.last_status = status
            readback = status.get("audio_speaker", {}).get("volume") if isinstance(status, dict) else None
            if readback is not None and readback != self.preferences.volume:
                raise ProviderError(502, "volume_mismatch", "设备返回的音量与设置不一致，请重试。")
            return {"volume": self.preferences.volume, "verified": readback == self.preferences.volume}

    async def disconnect(self):
        if self.connection:
            with suppress(Exception):
                await self.connection.ws.close(code=1000)

    async def push_audio(self, payload: bytes):
        """Forward one microphone frame; the worker decides when the sentence ended."""
        result = await self.speech.push(payload)
        connection = self.connection
        if (self.speech.voice_active and connection is not None and connection.client_aec
                and connection.voice_task is not None and not connection.stopped and self.voice is not None):
            await self.voice.interrupt(connection)
        if result is not None:
            self.publish_utterance(result)
        return result

    def publish_utterance(self, result: dict):
        self.last_utterance = {"at": self.now(), "state": "recognized",
                               "text": result.get("text"), "metrics": self.speech.last_metrics}
        logger.info("device_audio_recognized %s", json.dumps(
            {"characters": len(result.get("text") or ""), **self.speech.last_metrics}, ensure_ascii=False))
        # Answering is detached: a slow model must never block the audio loop.
        voice = self.voice
        text = (result.get("text") or "").strip()
        connection = self.connection
        if voice is not None and text and connection is not None:
            voice.submit(text, connection)

    async def flush_audio(self):
        """Close the worker stream at disconnect so a pending sentence is not lost."""
        result = await self.speech.finish()
        if result is not None:
            self.publish_utterance(result)
        return result


class DeviceConnection:
    def __init__(self, ws, hub):
        self.ws = ws
        self.hub = hub
        self.pending = {}
        self.next_id = 1
        self.tools = set()
        self.server_info = None
        self.ready = False
        self.send_lock = asyncio.Lock()
        # Microphone frames are streamed straight to the recognizer; only counters stay here.
        self.listening = False
        self.mode = "auto"
        self.frames_received = 0
        self.frames_dropped = 0
        self.packets = 0
        self.stopped = False
        self.voice_session_id = None
        self.voice_task = None
        self.voice_turn_id = None
        # Diagnostics: real abort frames the firmware sent (not the internal abort log
        # that fires on every listen start) and the device's advertised AEC capability.
        self.abort_count = 0
        self.abort_reasons = []
        self.voice_lock = asyncio.Lock()
        self.audio_controller = None
        self.session_id = str(uuid4())
        self.client_abort = False
        self.close_after_chat = False
        self.client_aec = False
        self.features = {}
        from config.logger import setup_logging
        from .voice_transport import DeviceSocket
        self.logger = setup_logging()
        self.websocket = DeviceSocket(self)

    def clear_queues(self):
        self.stopped = True
        if self.voice_task is not None:
            self.voice_task.cancel()
        if self.audio_controller is not None:
            self.audio_controller.reset()

    def clearSpeakStatus(self):
        self.stopped = True

    async def send_audio(self, packet: bytes):
        """Send one Opus frame as a binary WebSocket message."""
        async with self.send_lock:
            try:
                await self.ws.send_bytes(packet)
            except (RuntimeError, OSError):
                raise ProviderError(409, "device_disconnected", "设备连接已断开，请重新连接。") from None

    def audio_start(self, mode: str = "auto"):
        self.frames_received = 0
        self.frames_dropped = 0
        self.listening = True
        self.mode = mode

    def audio_frame(self, payload: bytes) -> bool:
        """Count a frame; returns False when the recognizer stream is not open."""
        self.frames_received += 1
        if self.frames_received == 1:
            # First frame proves the device is sending audio at all; the shape decides
            # whether the decoder parameters are right.
            logger.info("device_audio_first_frame bytes=%s listening=%s", len(payload), self.listening)
        if not self.listening:
            self.frames_dropped += 1
            return False
        return True

    async def send(self, message):
        async with self.send_lock:
            try:
                await self.ws.send_json(message)
            except (RuntimeError, OSError):
                raise ProviderError(409, "device_disconnected", "设备连接已断开，请重新连接。") from None

    async def rpc(self, method, params):
        identifier = self.next_id
        self.next_id += 1
        future = asyncio.get_running_loop().create_future()
        self.pending[identifier] = future
        try:
            await self.send({"type": "mcp", "payload": {
                "jsonrpc": "2.0", "id": identifier, "method": method, "params": params}})
            try:
                return await asyncio.wait_for(future, timeout=8)
            except TimeoutError:
                raise ProviderError(504, "device_timeout", "设备未确认指令；请检查连接后重试，未报告为已生效。") from None
        finally:
            self.pending.pop(identifier, None)

    async def initialize(self):
        result = await self.rpc("initialize", {"protocolVersion": "2024-11-05",
                                "capabilities": {}, "clientInfo": {"name": "AtomS3R Windows", "version": "0.2.0"}})
        info = result.get("serverInfo", {})
        if isinstance(info, dict):
            self.server_info = {k: str(info[k])[:100] for k in ("name", "version") if k in info}
        cursor = None
        for _ in range(10):
            params = {"cursor": cursor} if cursor else {}
            result = await self.rpc("tools/list", params)
            self.tools.update(t["name"] for t in result.get("tools", [])
                              if isinstance(t, dict) and isinstance(t.get("name"), str))
            cursor = result.get("nextCursor")
            if not cursor:
                self.ready = True
                return
        raise ProviderError(502, "device_tools_invalid", "设备工具列表分页异常。")

    async def negotiate(self):
        try:
            await self.initialize()
            # Keep the firmware's control channel active using a read-only status query.
            # WebSocket transport pings alone don't update its application-level timeout.
            while True:
                await asyncio.sleep(30)
                async with self.hub.lock:
                    if self.hub.connection is not self:
                        return
                    if "self.get_device_status" in self.tools:
                        self.hub.last_status = await self.call("self.get_device_status", {})
        except (ProviderError, AttributeError, TypeError, KeyError):
            self.hub.last_error = "设备能力协商失败；请重新连接并核对固件。"
            await self.ws.close(code=1008)

    async def call(self, name, arguments):
        if name not in self.tools:
            raise ProviderError(422, "device_tool_missing", "当前固件未提供所需设备工具。")
        result = await self.rpc("tools/call", {"name": name, "arguments": arguments})
        if not isinstance(result, dict) or result.get("isError"):
            raise ProviderError(502, "device_command_failed", "设备报告指令执行失败。")
        for item in result.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                try:
                    value = json.loads(item.get("text", ""))
                except (ValueError, TypeError):
                    continue
                if value is False:
                    raise ProviderError(502, "device_command_rejected", "设备拒绝应用设置。")
                return value
        return result

    def receive(self, message):
        payload = message.get("payload")
        if message.get("type") != "mcp" or not isinstance(payload, dict):
            return
        identifier = payload.get("id")
        if not isinstance(identifier, int):
            return
        future = self.pending.get(identifier)
        if future is not None and not future.done():
            if "error" in payload:
                future.set_exception(ProviderError(502, "device_rpc_failed", "设备返回控制错误，请检查固件能力。"))
            elif "result" in payload:
                future.set_result(payload["result"])

    def close(self):
        for future in self.pending.values():
            if not future.done():
                future.set_exception(ProviderError(409, "device_disconnected", "设备已断开，指令没有确认。"))


def create_gateway(hub: DeviceHub):
    """LAN-facing app: only bootstrap, health and one authenticated WebSocket."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "device-bridge", "audio_enabled": hub.speech.available}

    @app.post("/xiaozhi/ota/")
    async def bootstrap(request: Request):
        if not await hub.bootstrap_authorized(request.headers.get("device-id", ""), request.query_params.get("key")):
            return JSONResponse(status_code=403, content={"error": "device_not_authorized"})
        # Read only the reported firmware version so the reply never announces an upgrade;
        # boot metadata is not stored, forwarded or otherwise acted on.
        reported = "1.0.0"
        try:
            body = await request.json()
            if isinstance(body, dict):
                candidate = body.get("application", {}).get("version")
                if isinstance(candidate, str) and candidate.strip():
                    reported = candidate.strip()[:32]
        except (ValueError, TypeError, AttributeError):
            pass
        hub.last_bootstrap = hub.now()
        # XiaoZhi firmware expects a firmware block; omitting it makes the device treat
        # the whole reply as unusable and fall back to its previous server.
        return {"server_time": {"timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
                                "timezone_offset": 480},
                "firmware": {"version": reported, "url": ""},
                "websocket": {"url": hub.websocket_url,
                              "token": hub.token, "version": 1}}

    @app.websocket("/xiaozhi/v1/")
    @app.websocket("/xiaozhi/v1")
    async def websocket(ws: WebSocket):
        token = ws.headers.get("authorization", "")
        if token.startswith("Bearer "):
            token = token[7:]
        origin = ws.headers.get("origin")
        device_id = ws.headers.get("device-id", "")
        version = ws.headers.get("protocol-version", "1")
        if (origin is not None
                or not hub.authorized(device_id, token)
                or version != "1"):
            hub.last_error = hub.describe_rejection(origin, device_id, token, version)
            await ws.close(code=1008)
            return
        # A second connection cannot evict or claim the active device.
        async with hub.lock:
            if hub.connection is not None or not hub.authorized(ws.headers.get("device-id", ""), token):
                await ws.close(code=1008)
                return
            await ws.accept()
            conn = DeviceConnection(ws, hub)
            hub.connection = conn
        realtime = None
        realtime_mode = False
        initialize_task = None
        try:
            text = await asyncio.wait_for(ws.receive_text(), 10)
            if len(text) > 12000:
                await ws.close(code=1009)
                return
            hello = json.loads(text)
            if not isinstance(hello, dict) or hello.get("type") != "hello" or hello.get("transport") != "websocket":
                await ws.close(code=1008)
                return
            if not isinstance(hello.get("features"), dict) or not hello["features"].get("mcp"):
                raise ProviderError(422, "mcp_unsupported", "设备没有启用 MCP，不能验证设置。")
            from core.handle.helloHandle import handleHelloMessage
            conn.welcome_msg = {
                "type": "hello", "transport": "websocket", "session_id": conn.session_id,
                "audio_params": {"format": "opus", "sample_rate": 24000,
                                 "channels": 1, "frame_duration": 60},
            }
            await handleHelloMessage(conn, hello)
            hub.last_connected = hub.now()
            hub.last_error = None
            initialize_task = asyncio.create_task(conn.negotiate())
            while True:
                packet = await asyncio.wait_for(ws.receive(), CONTROL_IDLE_SECONDS)
                if packet["type"] == "websocket.disconnect":
                    logger.info("device_disconnect_frame code=%s", packet.get("code"))
                    break
                conn.packets += 1
                if conn.packets == 1:
                    logger.info("device_first_packet kind=%s",
                                "bytes" if packet.get("bytes") is not None else "text")
                if packet.get("bytes") is not None:
                    if len(packet["bytes"]) > MAX_FRAME_BYTES:
                        await ws.close(code=1009)
                        break
                    if conn.audio_frame(packet["bytes"]):
                        if realtime_mode:
                            if realtime:
                                await realtime.append(packet["bytes"])
                            else:
                                # Realtime mode with no live turn: the frame would be
                                # swallowed, so count it as dropped instead.
                                conn.frames_dropped += 1
                            continue
                        recognition = await hub.push_audio(packet["bytes"])
                        if recognition is not None:
                            hub.last_utterance = {**hub.last_utterance,
                                                  "received": conn.frames_received,
                                                  "mode": conn.mode}
                elif packet.get("text"):
                    if len(packet["text"]) > 12000:
                        await ws.close(code=1009)
                        break
                    message = json.loads(packet["text"])
                    if not isinstance(message, dict):
                        await ws.close(code=1008)
                        break
                    conn.receive(message)
                    logger.info("device_message %s", json.dumps(
                        {key: message.get(key) for key in ("type", "state", "mode") if key in message},
                        ensure_ascii=False))
                    if message.get("type") == "listen" and message.get("state") == "start":
                        # manual mode must not use VAD: it buffers until an explicit stop.
                        mode = "manual" if message.get("mode") == "manual" else "auto"
                        # Speaking while the answer plays is an interruption, not a new
                        # question; stopping here keeps the old reply from talking over it.
                        if hub.voice is not None:
                            await hub.voice.interrupt(conn)
                        conn.audio_start(mode)
                        if realtime:
                            await realtime.close()
                            realtime = None
                        realtime_mode = hub.voice is not None and hub.voice.service.settings.voice_mode == "realtime"
                        if realtime_mode:
                            from .device_realtime import DeviceRealtime
                            realtime = DeviceRealtime(hub,conn,mode=="manual")
                            try:
                                await realtime.turn.open()
                            except ProviderError as error:
                                hub.last_error = error.message
                                await realtime.close()
                                realtime = None
                                await conn.send({"type":"tts","state":"stop"})
                        else:
                            await hub.speech.ensure_ready(mode)
                    elif message.get("type") == "abort":
                        reason = message.get("reason")
                        reason = reason if isinstance(reason, str) and reason else "unknown"
                        conn.abort_count += 1
                        conn.abort_reasons = (conn.abort_reasons + [reason])[-10:]
                        if realtime:
                            await realtime.close()
                            realtime = None
                        # The device gave up on this answer (user pressed the button or
                        # started talking). Stop sending the remaining audio immediately.
                        if hub.voice is not None:
                            await hub.voice.interrupt(conn)
                        logger.info("device_abort reason=%s", reason)
                    elif message.get("type") == "listen" and message.get("state") == "stop":
                        conn.listening = False
                        if realtime:
                            await realtime.turn.finish()
                        elif not realtime_mode:
                            await hub.flush_audio()
        except (WebSocketDisconnect, TimeoutError, json.JSONDecodeError, RuntimeError) as error:
            hub.last_error = "设备控制连接已结束；按设备按钮可重新建立连接。"
            logger.info("device_connection_closed reason=%s frames_received=%s frames_dropped=%s listening=%s",
                        type(error).__name__, conn.frames_received, conn.frames_dropped, conn.listening)
        except ProviderError as error:
            hub.last_error = error.message
        finally:
            if realtime:
                with suppress(Exception):
                    await realtime.close()
            conn.clear_queues()
            if conn.voice_task is not None:
                with suppress(asyncio.CancelledError):
                    await conn.voice_task
            await hub.speech.finish()
            # Snapshot before the connection object is dropped: after a disconnect this is
            # the only evidence of how much audio the device actually sent.
            hub.last_session = {"ended_at": hub.now(), "connected_at": hub.last_connected,
                                "frames_received": conn.frames_received,
                                "frames_dropped": conn.frames_dropped,
                                "listening": conn.listening, "ready": conn.ready,
                                "client_aec": conn.client_aec,
                                "abort_count": conn.abort_count,
                                "abort_reasons": list(conn.abort_reasons),
                                "features": {k: conn.features[k] for k in sorted(conn.features)},
                                "tools": sorted(conn.tools)}
            logger.info("device_session %s", json.dumps(hub.last_session, ensure_ascii=False))
            conn.close()
            if initialize_task is not None:
                initialize_task.cancel()
                with suppress(asyncio.CancelledError, ProviderError):
                    await initialize_task
            if hub.connection is conn:
                hub.connection = None
            with suppress(Exception):
                await ws.close()

    return app
