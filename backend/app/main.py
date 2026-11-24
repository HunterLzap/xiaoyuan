import asyncio
import base64
from contextlib import asynccontextmanager, aclosing, suppress
import json
import os
import re
import secrets
import time
from ipaddress import ip_address
from pathlib import Path
from typing import Callable
from uuid import UUID
import urllib.parse

from fastapi import FastAPI, Query, Request, Response, WebSocket, WebSocketDisconnect
from .realtime import RealtimeTurn
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import qwen_voices, voices
from .asr import transcribe_browser_wav
from .config import ROOT, Settings
from .llm import ChatProvider, OpenAICompatibleProvider, ProviderError
from .realtime_text import build_chat_provider
from .schemas import (ApprovalDecisionRequest, ChatRequest, ChatResponse, KnowledgeResult, KnowledgeSearchRequest,
                      SessionDetail, SessionRename, SessionSummary,
                      PersonalKnowledgeSearchRequest, PersonalKnowledgeRename, InsightCorrectAnswer,
                      InsightClearFilters, LibraryCreate, LibraryRename)
from .schemas import (QwenVoicePreview, VoicePlaybackRequest, VoiceRequest,
                      VoiceSessionRequest, VoiceStopRequest, ChatCancelRequest)
from .knowledge import KnowledgeProvider, M5StackKnowledge, M5STACK_URL
from .personal_kb import PersonalKnowledgeBase, KnowledgeError, MAX_FILE_BYTES
from .tools import (build_tool_registry, tool_catalog, ExternalToolStore, BUILTIN_NAMES,
                    ExternalToolConfig, ToolCallRequest, ToolEnabledUpdate)
from .api_requests import (DebugRequest, confirm_request, merge_request, send_request,
                           request_dump, secret_values)
from .audit_store import AuditStore, FilterRequired, CountMismatch
from .error_log import ErrorLogStore
from .embeddings import build_embedder, EmbeddingError, to_blob
from .history_store import HistoryStore
from .service import ChatService
from .settings_store import (SettingsStore, SettingsUpdate, public_settings, APISettingsUpdate,
                             TTSSettingsUpdate, TTSPreview, public_tts_settings,
                             ConnectionsUpdate, AssistantUpdate, CapabilitySettingsUpdate,
                             AssistantSelectionUpdate)
from .tts import (CLONE_MODEL, PRESET_VOICES, TTSProvider, build_tts_provider,
                  shared_client, close_shared_client)
from .voice_profiles import BUSINESS_STATE_FIELDS, VoiceProfileStore
from .web_search import close_web_search_client
from .desktop import DesktopHub, mount_desktop_admin_routes
from .devices import DeviceHub, DeviceSetup, DevicePreferences
from .voice_transport import DeviceVoice, VoiceStreamingResponse, sse
from .speech_bridge import SpeechRecognizer, SPEECH_PYTHON


def create_app(settings: Settings | None = None, provider: ChatProvider | None = None,
               settings_store: SettingsStore | None = None,
               provider_factory: Callable[[Settings], ChatProvider] = build_chat_provider,
               knowledge_factory: Callable[[Settings], KnowledgeProvider] | None = None,
               device_hub: DeviceHub | None = None,
               tts_factory: Callable[[Settings], TTSProvider] = build_tts_provider,
               desktop_hub: DesktopHub | None = None) -> FastAPI:
    # Bracketed IPv6 entries in NO_PROXY make httpx fail on construction, which would
    # otherwise abort startup when the model client is built in the lifespan below.
    for name in ("no_proxy", "NO_PROXY"):
        value = os.environ.get(name)
        if value and ("[" in value or "]" in value):
            os.environ[name] = "localhost,127.0.0.1,::1"
    store = settings_store if settings_store is not None else SettingsStore()
    startup_config = settings if settings is not None else Settings()
    build_knowledge = knowledge_factory or (lambda config: M5StackKnowledge(config.m5stack_timeout_seconds))
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state_db_path = (
            startup_config.assistant_db_path
            if startup_config.assistant_db_path != ROOT / "data" / "assistant_state.sqlite3"
            else (store.path.parent / "data" / "assistant_state.sqlite3"
                  if (settings_store is not None or startup_config.history_db_path is not None
                      or startup_config.personal_kb_db_path is not None)
                  else None)
        )
        voice_profiles = VoiceProfileStore(state_db_path)
        config = voice_profiles.overlay_settings(startup_config)
        adapter = provider
        if adapter is None and not config.missing_config:
            adapter = provider_factory(config)
        history = HistoryStore(config.history_db_path) if config.history_db_path is not None else None
        knowledge = build_knowledge(config) if config.m5stack_enabled else None
        app.state.service = ChatService(config, adapter, history, knowledge)
        app.state.personal_kb = (PersonalKnowledgeBase(config.personal_kb_db_path)
                                 if config.personal_kb_db_path is not None else None)
        app.state.external_tools = ExternalToolStore(store.path.parent / "data" / "tools.json")
        if app.state.personal_kb is not None:
            app.state.personal_kb.initialize_if_missing()
        if config.selected_tool_ids is None or config.selected_kb_ids is None:
            defaults = [item["name"] for item in tool_catalog(config, knowledge, app.state.personal_kb,
                        app.state.external_tools) if item["kind"] in {"official", "weather", "search", "http", "desktop"} and item["enabled"]]
            kb_defaults = ([app.state.personal_kb.default_library_id()]
                           if config.selected_kb_ids is None and config.personal_kb_enabled and app.state.personal_kb is not None else [])
            if state_db_path is not None:
                missing = {}
                if config.selected_tool_ids is None:
                    missing["selected_tool_ids"] = defaults
                if config.selected_kb_ids is None:
                    missing["selected_kb_ids"] = kb_defaults
                voice_profiles.save_settings(missing)
                config = Settings.model_validate({**config.model_dump(), **missing})
            else:
                config = store.initialize_selection(config, defaults, kb_defaults)
            app.state.service.settings = config
        app.state.audit = AuditStore(config.personal_kb_db_path) if config.personal_kb_db_path is not None else None
        app.state.voice_profiles = voice_profiles
        app.state.voice_profiles.seed_from_settings(config)
        app.state.embedder = build_embedder(config)
        app.state.kb_index_lock = asyncio.Lock()
        app.state.tool_call_locks = {}
        app.state.debug_tasks = {}
        app.state.operation_lock = asyncio.Lock()
        app.state.tts_preview_lock = asyncio.Lock()
        app.state.cancel_markers = {}
        app.state.devices = device_hub if device_hub is not None else DeviceHub(
            store.path.parent / "data" / "devices.json",
            public_origin=config.public_origin,
            public_base_path=config.public_base_path,
            speech=SpeechRecognizer(
                python=config.speech_python or SPEECH_PYTHON,
                threads=config.speech_threads, model_dir=config.asr_model_dir,
            ),
        )
        app.state.devices.voice = DeviceVoice(
            app.state.devices, app.state.service, tts_factory)
        app.state.desktop = desktop_hub if desktop_hub is not None else DesktopHub(
            store.path.parent / "data" / "desktop_nodes.json",
            public_origin=config.public_origin,
            public_base_path=config.public_base_path,
        )
        app.state.desktop.settings_getter = lambda: app.state.service.settings
        app.state.desktop.lan_host_getter = lambda: (app.state.devices.setup.lan_host if app.state.devices.setup else "")
        app.state.error_log = ErrorLogStore(state_db_path)
        def log_system_error(source: str, code: str, message: str, *, detail=None, secrets=()):
            merged_secrets = tuple(secrets) if secrets else tuple(audit_secrets())
            app.state.error_log.record(source, code, message, detail=detail, secrets=merged_secrets)
        app.state.service.error_logger = log_system_error
        app.state.devices.error_logger = log_system_error
        app.state.desktop.error_logger = log_system_error
        refresh_tools()
        # Pay the TTS client's CA-load cost at startup instead of on the first turn.
        shared_client(config.tts_timeout_seconds)
        # Warm the local ASR worker only when explicit local recognition mode is selected.
        speech = app.state.devices.speech
        app.state.speech_prewarm = (
            asyncio.create_task(speech.ensure_ready())
            if config.voice_mode == "pipeline" and config.asr_provider == "local" and getattr(speech, "available", False)
            else None
        )
        try:
            yield
        finally:
            if app.state.speech_prewarm is not None:
                app.state.speech_prewarm.cancel()
                with suppress(asyncio.CancelledError):
                    await app.state.speech_prewarm
            await app.state.desktop.disconnect()
            await app.state.devices.disconnect()
            await app.state.devices.speech.close()
            await app.state.service.close()
            if app.state.embedder is not None:
                await app.state.embedder.close()
            await close_shared_client()
            await close_web_search_client()

    app = FastAPI(title="AtomS3R AI Assistant", version="0.2.0", lifespan=lifespan,
                  root_path=startup_config.public_base_path)

    def _asset_version() -> str:
        base = Path(__file__).parent
        stamps = [
            int((base / name).stat().st_mtime)
            for name in ("app.html", "app.css", "paths.js", "app.js", "voice.js")
            if (base / name).exists()
        ]
        return str(max(stamps) if stamps else 1)

    def app_page():
        content = Path(__file__).with_name("app.html").read_text(encoding="utf-8")
        html = (
            content.replace("__APP_BASE_PATH__", startup_config.public_base_path)
            .replace("__ASSET_VERSION__", _asset_version())
        )
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})
    allowed_hosts = ["localhost", "127.0.0.1", "[::1]"]
    if startup_config.public_origin:
        allowed_hosts.append(urllib.parse.urlsplit(startup_config.public_origin).hostname)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.middleware("http")
    async def protect_local_settings(request: Request, call_next):
        try:
            local = request.client is not None and ip_address(request.client.host).is_loopback
        except ValueError:
            local = False
        public = startup_config.public_origin
        if public:
            supplied = request.headers.get("x-assistant-admin", "")
            expected = startup_config.admin_proxy_token.get_secret_value()
            if not local or not secrets.compare_digest(supplied.encode("utf-8"), expected.encode("ascii")):
                return JSONResponse(status_code=401, content={"detail": {
                    "code": "authentication_required", "message": "请通过已登录的管理入口访问。",
                }})
            origin = request.headers.get("origin")
            unsafe = request.method not in {"GET", "HEAD", "OPTIONS"}
            if ((origin is not None and origin != public)
                    or unsafe and request.headers.get("x-local-settings") != "1"):
                return JSONResponse(status_code=403, content={"detail": {
                    "code": "invalid_origin", "message": "请求必须来自已登录的同源管理页面。",
                }})
        elif (request.url.path in {"/settings", "/knowledge", "/devices"}
              or request.url.path.startswith(("/api/settings", "/api/assistant", "/api/knowledge", "/api/tools", "/api/insights", "/api/devices", "/api/voice", "/api/approvals", "/api/desktop"))):
            origin = request.headers.get("origin")
            invalid_origin = origin is not None and origin != str(request.base_url).rstrip("/")
            missing_header = request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("x-local-settings") != "1"
            if not local or invalid_origin or missing_header:
                return JSONResponse(status_code=403, content={"detail": {
                    "code": "local_only", "message": "配置和连接测试仅允许本机同源访问。",
                }})
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "microphone=(self), camera=()"
        if request.url.path in {"/", "/settings", "/devices", "/settings.js", "/paths.js", "/app.js", "/voice.js", "/app.css"}:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "connect-src 'self'; media-src 'self' blob: https://g-adoc.alcasset.com https://help-static-aliyun-doc.aliyuncs.com; frame-ancestors 'none'; form-action 'self'"
            )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request, error: RequestValidationError):
        # Never echo submitted API keys (or chat text) in validation errors.
        return JSONResponse(status_code=422, content={"detail": [
            {"loc": item["loc"], "msg": item["msg"], "type": item["type"]}
            for item in error.errors()
        ]})

    @app.exception_handler(KnowledgeError)
    async def knowledge_error_handler(request, error: KnowledgeError):
        return JSONResponse(status_code=error.status, content={
            "detail": {"code": error.code, "message": error.message},
        })

    @app.exception_handler(ProviderError)
    async def provider_error_handler(request, error: ProviderError):
        err_log = getattr(app.state, "error_log", None)
        if (err_log is not None and error.status >= 400
                and error.code not in {"session_not_found", "tool_not_found", "insight_not_found"}
                and not getattr(error, "_error_logged", False)):
            src = ("desktop" if error.code.startswith("desktop_")
                   else "device" if error.code.startswith(("device_", "ota_"))
                   else "tool" if error.code.startswith(("tool_", "approval_", "order_"))
                   else "model" if error.status in (502, 503, 504) else "system")
            await asyncio.to_thread(
                err_log.record, src, error.code, error.message,
                detail={"status": error.status, "path": request.url.path}, secrets=audit_secrets(),
            )
        return JSONResponse(status_code=error.status, content={
            "detail": {"code": error.code, "message": error.message},
        })

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request, error: Exception):
        err_log = getattr(app.state, "error_log", None)
        if err_log is not None:
            await asyncio.to_thread(
                err_log.record,
                "system",
                f"unhandled_{type(error).__name__}",
                f"服务端未捕获异常：{type(error).__name__}: {str(error)[:300]}",
                detail={"path": request.url.path, "method": request.method},
                secrets=audit_secrets(),
            )
        return JSONResponse(status_code=500, content={
            "detail": {"code": "internal_server_error", "message": "服务内部处理异常，详情已记录到「执行洞察 → 异常日志」。"},
        })

    @app.get("/health")
    async def health():
        service = app.state.service
        return {
            "status": "ok", "configured": not service.settings.missing_config,
            "missing_config": service.settings.missing_config,
            "provider": service.settings.active_provider, "model": service.settings.active_model,
            "upstream_verified": service.usage.successful_calls > 0,
            "history_turns": service.settings.history_turns,
            "context_history_chars": service.settings.context_history_chars,
            "history_enabled": service.history_store is not None,
            "m5stack_enabled": service.settings.m5stack_enabled,
            "desktop_enabled": service.settings.desktop_enabled,
            "desktop_online_nodes": len(app.state.desktop.active) if getattr(app.state, "desktop", None) else 0,
        }

    @app.post("/api/approvals/{approval_id}")
    async def decide_approval(approval_id: str, body: ApprovalDecisionRequest):
        return app.state.service.resolve_approval(approval_id, body.decision, session_id=body.session_id)

    mount_desktop_admin_routes(app, lambda: app.state.desktop, public=bool(startup_config.public_origin))

    _STOP_INTENT_RE = re.compile(
        r"^(?:停|停下|停下来|停止|停止操作|别动|别动了|别操作了|取消|取消操作|住手|stop|cancel)[！!。.？?]*$",
        re.IGNORECASE,
    )

    async def _maybe_stop_by_text(request: ChatRequest) -> dict | None:
        if request.session_id is None or not _STOP_INTENT_RE.match((request.message or "").strip()):
            return None
        session = app.state.service.get_session(request.session_id)
        task = session.active_task
        if task is None or task.done():
            return None
        await stop_active_turn(request.session_id)
        return {
            "session_id": str(request.session_id),
            "reply": "已停止当前操作。",
            "model": app.state.service.settings.active_model,
            "provider": app.state.service.settings.active_provider,
            "usage": None,
            "estimated_cost": None,
            "currency": app.state.service.settings.currency,
            "finish_reason": "stop",
            "session_usage": session.usage.model_copy().model_dump(mode="json"),
            "history_persisted": True,
        }

    @app.post("/chat/cancel")
    async def chat_cancel(body: ChatCancelRequest):
        stopped = await stop_active_turn(body.session_id, body.turn_id)
        return {"ok": True, "stopped": stopped}

    @app.post("/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest):
        stopped_reply = await _maybe_stop_by_text(request)
        if stopped_reply is not None:
            return stopped_reply
        task = asyncio.current_task()
        marker = {"token": None, "turn_id": None}
        app.state.cancel_markers[task] = marker
        try:
            return await app.state.service.chat(request)
        except asyncio.CancelledError as error:
            # 仅认领 stop/reset 对这个 HTTP task 发出的专属取消；其他原因/追加取消继续传播。
            if (marker["token"] is not None and error.args == (marker["token"],)
                    and marker["turn_id"] is not None and task.cancelling() == 1):
                return JSONResponse(status_code=409, content={"detail": {
                    "code": "turn_cancelled", "message": "本轮已按请求取消，未生成完整回答。"}})
            raise
        finally:
            app.state.cancel_markers.pop(task, None)

    @app.post("/chat/stream")
    async def chat_stream(request: ChatRequest):
        def _sse(event_name: str, payload: dict) -> str:
            return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

        stopped_reply = await _maybe_stop_by_text(request)
        if stopped_reply is not None:
            async def _stopped_events():
                yield _sse("session", {"session_id": stopped_reply["session_id"], "turn_id": "", "history_persisted": True})
                yield _sse("text", {"delta": stopped_reply["reply"], "full": stopped_reply["reply"]})
                yield _sse("done", stopped_reply)

            return StreamingResponse(
                _stopped_events(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        async def _events():
            task = asyncio.current_task()
            marker = {"token": None, "turn_id": None}
            app.state.cancel_markers[task] = marker
            try:
                async with aclosing(app.state.service.turn(request)) as events:
                    async for kind, payload in events:
                        if kind in ("session", "tool", "text", "done"):
                            yield _sse(kind, payload)
            except ProviderError as error:
                if (error.status >= 400
                        and error.code not in {"session_not_found", "tool_not_found", "insight_not_found"}
                        and not getattr(error, "_error_logged", False)):
                    with suppress(Exception):
                        await asyncio.to_thread(
                            app.state.error_log.record,
                            "system",
                            error.code,
                            error.message,
                            detail={"status": error.status, "path": "/chat/stream"},
                            secrets=tuple(audit_secrets()),
                        )
                yield _sse("error", {"code": error.code, "message": error.message})
            except asyncio.CancelledError as error:
                if (task is not None and marker["token"] is not None and error.args == (marker["token"],)
                        and marker["turn_id"] is not None and task.cancelling() == 1):
                    yield _sse("error", {"code": "turn_cancelled", "message": "本轮已按请求取消，未生成完整回答。"})
                else:
                    raise
            finally:
                app.state.cancel_markers.pop(task, None)

        return StreamingResponse(
            _events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/", include_in_schema=False)
    async def home():
        return app_page()

    @app.get("/devices", include_in_schema=False)
    async def devices_page():
        return app_page()

    @app.get("/api/devices")
    async def devices_status():
        return app.state.devices.public()

    @app.put("/api/devices/setup")
    async def devices_setup(update: DeviceSetup):
        return await app.state.devices.configure(update)

    @app.put("/api/devices/preferences")
    async def devices_preferences(update: DevicePreferences):
        return await app.state.devices.save_preferences(update)

    @app.post("/api/devices/apply")
    async def devices_apply():
        return await app.state.devices.apply()

    @app.post("/api/devices/volume/apply")
    async def apply_device_volume():
        return await app.state.devices.apply_volume()

    @app.get("/api/devices/speech")
    async def devices_speech():
        """Read-only view of the local recognizer and the last utterance it produced."""
        hub = app.state.devices
        return {"speech": hub.speech.public(), "last_utterance": hub.last_utterance,
                "frames_received": hub.connection.frames_received if hub.connection else 0,
                "listening": bool(hub.connection and hub.connection.listening)}

    @app.get("/voice-capture.js", include_in_schema=False)
    async def capture_script():
        return FileResponse(Path(__file__).with_name("voice-capture.js"), media_type="text/javascript")

    @app.websocket("/api/voice/realtime")
    async def realtime_socket(ws: WebSocket):
        origin = startup_config.public_origin or "http://" + ws.headers.get("host", "")
        trusted = ws.client and ip_address(ws.client.host).is_loopback and ws.headers.get("origin") == origin
        if startup_config.public_origin:
            trusted = trusted and secrets.compare_digest(ws.headers.get("x-assistant-admin","").encode(),
                startup_config.admin_proxy_token.get_secret_value().encode())
        if not trusted:
            await ws.close(code=1008)
            return
        await ws.accept()
        turn = None
        recv = None
        try:
            service = app.state.service
            if service.settings.voice_mode != "realtime":
                raise ProviderError(409,"voice_mode","请切换到实时对话模式。")
            raw_sid = ws.query_params.get("session")
            async def emit(kind,data):
                await ws.send_json({"type":kind,"data":data})
            turn = RealtimeTurn(service,UUID(raw_sid) if raw_sid else None,"web_voice",emit,False)
            turn.continuous = True
            await turn.open()
            while not turn.reader.done():
                recv = asyncio.create_task(ws.receive())
                finished,_ = await asyncio.wait((recv,turn.reader),return_when=asyncio.FIRST_COMPLETED)
                if recv not in finished:
                    break
                packet = recv.result()
                if packet["type"]=="websocket.disconnect":
                    break
                if packet.get("text") == "finish":
                    await turn.finish()
                elif packet.get("bytes") and len(packet["bytes"]) <= 16384 and len(packet["bytes"])%2==0:
                    await turn.append(packet["bytes"])
                else:
                    break
        except ProviderError as error:
            await ws.send_json({"type":"error","data":error.message})
        except (WebSocketDisconnect,ValueError,RuntimeError,OSError):
            pass
        finally:
            if recv:
                recv.cancel()
                await asyncio.gather(recv,return_exceptions=True)
            if turn:
                await turn.close()
            with suppress(WebSocketDisconnect, RuntimeError, OSError):
                await ws.close()

    @app.post("/api/voice/session")
    async def voice_session(body: VoiceSessionRequest):
        service = app.state.service
        session_id = body.session_id or service.new_session()
        return {"session_id": str(session_id),
                "history": service.session_detail(session_id).messages}

    async def stop_active_turn(session_id, turn_id=None):
        """停止会话当前活跃回合；若它正好是文字 /chat，先打专属标记，让文字端返回 409 而不是 500。

        只标记文字 HTTP task（cancel_markers 中存在），语音/其他取消仍走原 service.stop 的普通取消；
        turn_id 为空表示“停止该会话当前回合”（/api/voice/turn 的混合通道场景）。
        """
        service = app.state.service
        session = service.get_session(session_id)
        task = session.active_task
        if (task is not None and task is not asyncio.current_task() and not task.done()
                and not task.cancelling() and (turn_id is None or session.active_turn_id == turn_id)):
            marker = app.state.cancel_markers.get(task)
            if marker is not None:
                token = "chat_stop_" + secrets.token_hex(16)
                marker.update(token=token, turn_id=session.active_turn_id)
                task.cancel(token)
        return await service.stop(session_id, turn_id)

    async def stop_requested_turn(body: VoiceStopRequest):
        return await stop_active_turn(body.session_id, body.turn_id)

    @app.post("/api/voice/reset")
    async def voice_reset(body: VoiceStopRequest):
        await stop_requested_turn(body)
        return {"ok": True}

    @app.post("/api/voice/stop")
    async def voice_stop(body: VoiceStopRequest):
        stopped = await stop_requested_turn(body)
        return {"ok": True, "stopped": stopped}

    @app.post("/api/voice/playback")
    async def voice_playback(body: VoicePlaybackRequest):
        await app.state.service.playback(body.session_id, body.turn_id, body.state)
        return {"ok": True}

    @app.post("/api/voice/asr")
    async def voice_asr(request: Request):
        """Transcribe one browser recording (WAV bytes in the body)."""
        raw = await request.body()
        if not raw or len(raw) > 20 * 1024 * 1024:
            raise ProviderError(422, "voice_audio_invalid", "录音为空或过大。")
        started = time.perf_counter()
        result = await transcribe_browser_wav(
            app.state.service.settings, raw, app.state.devices.speech,
        )
        return {**result, "ms": int((time.perf_counter() - started) * 1000)}

    @app.post("/api/voice/turn")
    async def voice_turn(body: VoiceRequest):
        service = app.state.service
        if service.provider is None:
            raise ProviderError(503, "not_configured", "请先配置对话模型。")
        if body.session_id is not None:
            await stop_active_turn(body.session_id)

        async def generate():
            try:
                async with aclosing(service.turn(
                    ChatRequest(message=body.text, session_id=body.session_id),
                    source="web_voice", tts_factory=tts_factory, turn_id=body.turn_id,
                )) as events:
                    async for kind, payload in events:
                        if kind == "audio":
                            payload = {"pcm": base64.b64encode(payload).decode("ascii")}
                        yield sse(kind, payload)
            except ProviderError as error:
                yield sse("error", {"code": error.code, "message": error.message})

        return VoiceStreamingResponse(generate(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store",
                                          "X-Accel-Buffering": "no"})

    @app.get("/favicon.ico", include_in_schema=False, status_code=204)
    async def favicon():
        return Response(status_code=204)

    @app.get("/settings", include_in_schema=False)
    async def settings_page():
        return app_page()

    @app.get("/settings.js", include_in_schema=False)
    @app.get("/app.js", include_in_schema=False)
    async def settings_script():
        return FileResponse(Path(__file__).with_name("app.js"), media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    @app.get("/paths.js", include_in_schema=False)
    async def paths_script():
        return FileResponse(Path(__file__).with_name("paths.js"), media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    @app.get("/voice.js", include_in_schema=False)
    async def voice_script():
        return FileResponse(Path(__file__).with_name("voice.js"), media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    @app.get("/app.css", include_in_schema=False)
    async def app_styles():
        return FileResponse(Path(__file__).with_name("app.css"), media_type="text/css", headers={"Cache-Control": "no-cache"})

    def settings_payload(config: Settings) -> dict:
        return {**public_settings(config), "voice_profiles": app.state.voice_profiles.all_profiles()}

    def tts_settings_payload(config: Settings) -> dict:
        return {**public_tts_settings(config), "voice_profiles": app.state.voice_profiles.all_profiles()}

    @app.get("/api/settings")
    async def get_settings():
        return settings_payload(app.state.service.settings)

    @app.get("/api/settings/tts")
    async def get_tts_settings():
        return tts_settings_payload(app.state.service.settings)

    async def save_grouped_settings(update: ConnectionsUpdate | AssistantUpdate | CapabilitySettingsUpdate):
        async with app.state.operation_lock:
            service = app.state.service
            config = store.prepare(service.settings, update)
            if (isinstance(update, AssistantUpdate) and config.tts_provider == "mimo"
                    and config.tts_model == "mimo-v2.5-tts-voicedesign" and not config.tts_instruction.strip()):
                raise ProviderError(422, "tts_voice_description_required", "请填写音色描述。")
            text_changed = any(getattr(config, name) != getattr(service.settings, name)
                               for name in ("base_url", "api_key", "model", "provider", "timeout_seconds", "max_tokens",
                                            "voice_mode", "rt_workspace", "rt_endpoint", "rt_provider", "rt_api_key", "rt_model"))
            knowledge_changed = config.m5stack_enabled != service.settings.m5stack_enabled
            embedding_changed = config.embedding_enabled != service.settings.embedding_enabled
            adapter = provider_factory(config) if text_changed and not config.missing_config else None
            if isinstance(update, CapabilitySettingsUpdate):
                app.state.voice_profiles.save_settings(
                    {k: getattr(config, k) for k in update.model_fields_set if k in BUSINESS_STATE_FIELDS}
                )
            else:
                try:
                    store.save(config, update)
                except Exception:
                    if adapter is not None:
                        await adapter.close()
                    raise
                state_updates = {k: getattr(config, k) for k in (update.model_fields_set & BUSINESS_STATE_FIELDS)}
                if state_updates:
                    app.state.voice_profiles.save_settings(state_updates)
            app.state.voice_profiles.record_from_settings(
                config,
                save_realtime=isinstance(update, ConnectionsUpdate) or config.voice_mode == "realtime",
                save_tts=isinstance(update, (ConnectionsUpdate, AssistantUpdate)) or config.voice_mode == "pipeline",
            )
            if text_changed:
                old_adapter = service.provider
                service.apply_settings(config, adapter)
                if old_adapter is not None:
                    await service.retire_provider(old_adapter)
            else:
                service.settings = config
            if knowledge_changed:
                service.knowledge = build_knowledge(config) if config.m5stack_enabled else None
            if embedding_changed:
                old_embedder = app.state.embedder
                app.state.embedder = build_embedder(config)
                if old_embedder is not None:
                    await old_embedder.close()
            refresh_tools()
            return {"text": settings_payload(config), "tts": tts_settings_payload(config)}

    @app.put("/api/settings/api")
    async def save_api_settings(update: APISettingsUpdate):
        return await save_grouped_settings(update)

    @app.put("/api/settings/connections")
    async def save_connections(update: ConnectionsUpdate):
        return await save_grouped_settings(update)

    @app.put("/api/settings/assistant")
    async def save_assistant(update: AssistantUpdate):
        return await save_grouped_settings(update)

    @app.put("/api/settings/capabilities")
    async def save_capabilities(update: CapabilitySettingsUpdate):
        return await save_grouped_settings(update)

    @app.get("/api/assistant/selection")
    async def get_assistant_selection():
        settings = app.state.service.settings
        return {"selected_tool_ids": settings.selected_tool_ids or [],
                "selected_kb_ids": settings.selected_kb_ids or []}

    @app.put("/api/assistant/selection")
    async def save_assistant_selection(update: AssistantSelectionUpdate):
        async with app.state.operation_lock:
            service = app.state.service
            if "selected_tool_ids" in update.model_fields_set:
                catalog = tool_catalog(service.settings, service.knowledge,
                                       app.state.personal_kb, app.state.external_tools,
                                       desktop=getattr(app.state, "desktop", None))
                known = {item["name"] for item in catalog if item["kind"] in {"official", "weather", "search", "http", "desktop"}}
                if any(tool_id not in known for tool_id in update.selected_tool_ids):
                    raise ProviderError(422, "assistant_tool_unknown", "请选择已有的天气、联网搜索、M5、电脑控制或 HTTP API 能力。")
            if "selected_kb_ids" in update.model_fields_set and update.selected_kb_ids:
                await asyncio.to_thread(get_personal_kb().assert_libraries, update.selected_kb_ids)
            config = store.prepare(service.settings, update)
            app.state.voice_profiles.save_settings(
                {k: getattr(config, k) for k in update.model_fields_set if k in BUSINESS_STATE_FIELDS}
            )
            service.settings = config
            refresh_tools()
            return {"selected_tool_ids": config.selected_tool_ids,
                    "selected_kb_ids": config.selected_kb_ids}

    @app.put("/api/settings/tts")
    async def save_tts_settings(update: TTSSettingsUpdate):
        async with app.state.operation_lock:
            config = store.prepare(app.state.service.settings, update)
            if (config.tts_provider == "mimo" and config.tts_model == "mimo-v2.5-tts-voicedesign"
                    and not config.tts_instruction.strip()):
                raise ProviderError(422, "tts_voice_description_required", "VoiceDesign 需要填写音色描述。")
            store.save(config, update)
            app.state.service.settings = config
            app.state.voice_profiles.record_from_settings(config, save_realtime=False, save_tts=True)
            return tts_settings_payload(config)

    @app.post("/api/settings/tts/preview")
    async def preview_tts(request: TTSPreview):
        if app.state.tts_preview_lock.locked():
            raise ProviderError(409, "tts_preview_busy", "已有试听正在合成，请稍后重试。")
        async with app.state.tts_preview_lock:
            async with app.state.operation_lock:
                current = app.state.service.settings
                if request.connection is not None:
                    current = store.prepare(current, request.connection)
                config = store.prepare(current, request.config)
            adapter = tts_factory(config)
            try:
                audio = await adapter.synthesize(request.text)
                return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})
            finally:
                await adapter.close()

    @app.get("/api/voices")
    async def list_voices():
        """Saved cloned voices, plus the presets each model accepts."""
        return {"cloned": voices.public_list(), "presets": PRESET_VOICES,
                "clone_model": CLONE_MODEL}

    @app.get("/api/voices/qwen")
    async def list_qwen_voices(target_model: str | None = None):
        return {"voices": await qwen_voices.list_public(app.state.service.settings, target_model=target_model)}

    @app.post("/api/voices/qwen")
    async def create_qwen_voice(request: Request):
        try:
            declared = int(request.headers.get("content-length", "0"))
        except ValueError:
            raise ProviderError(422, "voice_audio_size_invalid", "无法读取音频大小。") from None
        if declared > voices.MAX_UPLOAD_BYTES:
            raise ProviderError(422, "voice_audio_too_large", "音频不能超过 10MB。")
        raw = await request.body()
        if len(raw) > voices.MAX_UPLOAD_BYTES:
            raise ProviderError(422, "voice_audio_too_large", "音频不能超过 10MB。")
        name = urllib.parse.unquote(request.headers.get("x-voice-name", ""))
        filename = urllib.parse.unquote(request.headers.get("x-voice-filename", "upload.wav"))
        target_model = urllib.parse.unquote(request.headers.get("x-target-model", "")).strip() or None
        async with app.state.operation_lock:
            return await qwen_voices.create(app.state.service.settings, raw, filename, name, target_model=target_model)

    @app.post("/api/voices/qwen/preview")
    async def preview_qwen_voice(body: QwenVoicePreview):
        config = app.state.service.settings.model_copy(deep=True)
        config.tts_rate = body.rate if body.rate is not None else config.tts_rate
        config.tts_pitch = body.pitch if body.pitch is not None else config.tts_pitch
        audio = await qwen_voices.preview(config, body.voice, body.text)
        return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    @app.delete("/api/voices/qwen/{voice}")
    async def remove_qwen_voice(voice: str):
        await qwen_voices.delete(app.state.service.settings, voice)
        return {"ok": True}

    @app.post("/api/voices")
    async def create_voice(request: Request):
        """Accept an uploaded clip and store it as a named cloned voice."""
        raw = await request.body()
        name = request.headers.get("x-voice-name", "")
        filename = request.headers.get("x-voice-filename", "upload.wav")
        try:
            decoded_name = urllib.parse.unquote(name)
        except (TypeError, ValueError):
            decoded_name = name
        return voices.process_upload(raw, filename, decoded_name)

    @app.delete("/api/voices/{voice_id}")
    async def remove_voice(voice_id: str):
        voices.delete(voice_id)
        return {"ok": True, "cloned": voices.public_list()}

    @app.put("/api/settings")
    async def save_settings(update: SettingsUpdate):
        async with app.state.operation_lock:
            old_service = app.state.service
            config = store.prepare(old_service.settings, update)
            adapter = provider_factory(config) if not config.missing_config else None
            try:
                store.save(config, update)
            except Exception:
                if adapter is not None:
                    await adapter.close()
                raise
            old_adapter = old_service.provider
            old_service.apply_settings(config, adapter)
            old_service.knowledge = build_knowledge(config) if config.m5stack_enabled else None
            refresh_tools()
            if old_adapter is not None:
                await old_service.retire_provider(old_adapter)
            return public_settings(config)

    @app.post("/api/settings/test", response_model=ChatResponse)
    async def test_settings(update: SettingsUpdate):
        async with app.state.operation_lock:
            config = store.prepare(app.state.service.settings, update).model_copy(update={"voice_mode": "pipeline"})
            if config.missing_config:
                raise ProviderError(422, "not_configured", "请填写 " + ", ".join(config.missing_config))
            adapter = provider_factory(config)
            try:
                diagnostic = ChatService(config, adapter)
                return await diagnostic.chat(ChatRequest(message="请只回复：连接成功"))
            finally:
                await adapter.close()

    @app.post("/api/settings/models")
    async def list_models(update: SettingsUpdate):
        async with app.state.operation_lock:
            config = store.prepare(app.state.service.settings, update).model_copy(update={"voice_mode": "pipeline"})
            adapter = provider_factory(config)
            try:
                if not isinstance(adapter, OpenAICompatibleProvider):
                    raise ProviderError(422, "models_unsupported", "当前适配器不支持获取模型列表；请手填模型 ID。")
                result = await adapter.list_models()
                if isinstance(result, dict):
                    chat, speech = result.get("chat", []), result.get("speech", [])
                else:
                    chat, speech = list(result), []
                return {"models": chat, "speech_models": speech, "chat_verified": False}
            finally:
                await adapter.close()

    @app.get("/usage")
    async def usage():
        service = app.state.service
        return {"currency": service.settings.currency, "scope": "current_process",
                "active_sessions": len(service.sessions), "totals": service.usage}

    def get_knowledge() -> KnowledgeProvider:
        knowledge = app.state.service.knowledge
        if knowledge is None:
            raise ProviderError(503, "m5stack_disabled", "请先在设置中启用 M5Stack 官方资料检索。")
        return knowledge

    @app.post("/api/knowledge/m5stack/status")
    async def knowledge_status():
        return await get_knowledge().status()

    @app.post("/api/knowledge/m5stack/search", response_model=KnowledgeResult)
    async def knowledge_search(request: KnowledgeSearchRequest):
        return await get_knowledge().search(request)

    @app.get("/api/knowledge/m5stack")
    async def knowledge_config():
        return {"enabled": app.state.service.settings.m5stack_enabled, "server_url": M5STACK_URL,
                "tool_name": "knowledge_search", "read_only": True}

    def apply_setting(name, value):
        if name not in ("tts_rate", "tts_pitch"):
            raise ProviderError(422, "setting_unknown", "不支持该设置项。")
        from pydantic import ValidationError as _PydValidationError
        current = app.state.service.settings
        try:
            config = Settings(_env_file=None, **{**current.model_dump(), name: value})
        except _PydValidationError:
            raise ProviderError(422, "setting_range", "数值超出允许范围。") from None
        app.state.voice_profiles.save_settings({name: getattr(config, name)})
        app.state.service.settings = config
        app.state.voice_profiles.record_from_settings(
            config,
            save_realtime=config.voice_mode == "realtime",
            save_tts=config.voice_mode == "pipeline",
        )
        return getattr(config, name)

    def refresh_tools():
        service = app.state.service
        desktop = getattr(app.state, "desktop", None)
        app.state.tools = build_tool_registry(service.settings, service.knowledge,
                                              app.state.personal_kb, app.state.external_tools, app.state.embedder,
                                              devices=getattr(app.state, "devices", None), apply_setting=apply_setting,
                                              desktop=desktop)
        app.state.resource_tools = build_tool_registry(service.settings, service.knowledge,
            app.state.personal_kb, app.state.external_tools, app.state.embedder,
            devices=getattr(app.state, "devices", None), apply_setting=apply_setting,
            desktop=desktop, assistant_scope=False)
        service.tools = app.state.tools
        service.audit = app.state.audit
        service.tool_secrets = audit_secrets

    @app.get("/api/tools")
    async def list_tools():
        service = app.state.service
        return {"tools": tool_catalog(service.settings, service.knowledge,
                                      app.state.personal_kb, app.state.external_tools,
                                      desktop=getattr(app.state, "desktop", None)),
                "conversation_integration": True,
                "automatic_permissions": ["read"],
                "supported_file_types": ["txt", "md", "markdown", "docx", "pdf"]}

    @app.put("/api/tools/{name}")
    async def save_external_tool(name: str, body: ExternalToolConfig):
        if name != body.name:
            raise ProviderError(422, "tool_name", "路径与配置中的工具名称必须一致。")
        async with app.state.operation_lock:
            result = app.state.external_tools.put(body)
            refresh_tools()
            return result

    @app.put("/api/tools/{name}/enabled")
    async def enable_tool(name: str, body: ToolEnabledUpdate):
        fields = {"search_m5stack": "m5stack_enabled", "search_personal_knowledge": "personal_kb_enabled",
                  "get_weather": "weather_enabled", "web_search": "web_search_enabled", "desktop_control": "desktop_enabled"}
        if name in fields:
            update = CapabilitySettingsUpdate.model_validate({fields[name]: body.enabled})
            await save_grouped_settings(update)
        else:
            async with app.state.operation_lock:
                app.state.external_tools.enable(name, body.enabled)
                refresh_tools()
        return await list_tools()

    @app.delete("/api/tools/{name}", status_code=204)
    async def delete_external_tool(name: str):
        async with app.state.operation_lock:
            app.state.external_tools.delete(name)
            refresh_tools()
        return Response(status_code=204)

    @app.post("/api/tools/{name}/call")
    async def call_tool(name: str, body: ToolCallRequest):
        registry = app.state.resource_tools
        tool = registry.get(name)
        if tool is None:
            raise ProviderError(404, "tool_not_found", "工具不存在或未启用。")
        lock = app.state.tool_call_locks.setdefault(name, asyncio.Lock())
        if lock.locked():
            raise ProviderError(409, "tool_busy", "该工具已有请求执行中，请勿重复提交。")
        permission = tool.spec.permission
        summary = json.dumps(body.arguments, ensure_ascii=False)
        trace_data: dict = {}
        outcome: dict | None = None
        state, error_code = "error", None
        async with lock:
            try:
                call_outcome = await app.state.service.tool_gateway.execute_manual(
                    registry,
                    name,
                    body.arguments,
                    confirmed=body.confirmed,
                    secrets=audit_secrets(),
                    trace_out=trace_data,
                )
                outcome = call_outcome
                state = "ok"
                return call_outcome["result"]
            except (ProviderError, KnowledgeError, EmbeddingError) as error:
                error_code = error.code
                raise
            except asyncio.CancelledError:
                state, error_code = "cancelled", "tool_cancelled"
                raise
            finally:
                elapsed = (trace_data.get("_gateway") or {}).get("elapsed_ms", 0)
                result_payload = outcome.get("result") if outcome is not None else None
                response = trace_data.get("response", result_payload)
                http_status = response.get("status") if isinstance(response, dict) and isinstance(response.get("status"), int) else None
                calls = [{
                    "tool_name": name,
                    "trigger_question": None,
                    "request": trace_data.get("request", {"arguments": body.arguments}),
                    "response": response,
                    "http_status": http_status,
                    "elapsed_ms": elapsed,
                    "status": state,
                    "error_code": error_code,
                }]
                snapshots = [{**match, "sent_to_model": False, "cited": False}
                             for match in ((result_payload or {}).get("matches", []) if isinstance(result_payload, dict) else [])]
                await record_audit(
                    "tool_call",
                    query_summary=summary,
                    tool_name=name,
                    permission=permission,
                    hit=state == "ok",
                    status=state,
                    error_code=error_code,
                    elapsed_ms=elapsed,
                    calls=calls,
                    snapshots=snapshots,
                    source="manual_tool",
                )

    @app.get("/api/tools/{name}")
    async def get_external_tool(name: str):
        if name in BUILTIN_NAMES:
            for item in tool_catalog(app.state.service.settings, app.state.service.knowledge,
                                     app.state.personal_kb, app.state.external_tools,
                                     desktop=getattr(app.state, "desktop", None)):
                if item["name"] == name:
                    return item
        cfg = app.state.external_tools.items.get(name)
        if cfg is None:
            raise ProviderError(404, "tool_not_found", "工具不存在。")
        return app.state.external_tools.public(cfg)

    @app.post("/api/tools/debug")
    async def debug_request(body: DebugRequest):
        if body.request_id in app.state.debug_tasks:
            raise ProviderError(409, "tool_debug_duplicate", "该请求已在执行中。")
        draft = body.request
        if body.reuse_tool:
            stored = app.state.external_tools.items.get(body.reuse_tool)
            if stored is None:
                raise ProviderError(404, "tool_not_found", "要复用密钥的工具不存在。")
            draft = merge_request(draft, stored.request)
        draft = merge_request(draft)
        confirm_request(draft, body.permission, body.confirmed)
        started = time.perf_counter()
        trace = {}
        result, state, error_code = None, "error", None
        task = asyncio.create_task(send_request(draft, trace=trace))
        app.state.debug_tasks[body.request_id] = task
        try:
            result = await task
            state = "ok" if 200 <= result["status"] < 300 else "error"
            error_code = None if state == "ok" else "http_" + str(result["status"])
        except ProviderError as error:
            error_code = error.code
            raise
        except asyncio.CancelledError as error:
            state, error_code = "cancelled", "tool_cancelled"
            raise ProviderError(409, "tool_cancelled",
                                "等待已取消；若请求已发出，外部操作可能已生效，请核实，未自动重试。") from error
        finally:
            app.state.debug_tasks.pop(body.request_id, None)
            elapsed = int((time.perf_counter() - started) * 1000)
            calls = [{"tool_name": body.reuse_tool or "debug", "trigger_question": None,
                      "request": trace.get("request", request_dump(draft)),
                      "response": trace.get("response", result),
                      "http_status": result["status"] if result is not None else None,
                      "elapsed_ms": elapsed, "status": state, "error_code": error_code}]
            await record_audit("tool_call", query_summary=f"{draft.method} {draft.url}",
                tool_name=body.reuse_tool or "debug", permission=body.permission, hit=state == "ok",
                status=state, error_code=error_code, calls=calls, call_id=str(body.request_id),
                source="manual_debug", elapsed_ms=elapsed)
        return {"request_id": str(body.request_id), **result}

    @app.post("/api/tools/debug/{request_id}/cancel")
    async def cancel_debug(request_id: UUID):
        task = app.state.debug_tasks.get(request_id)
        if task is None:
            return {"cancelled": False,
                    "message": "没有正在等待的请求；若此前已发出，结果可能已生效，请核实。"}
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        return {"cancelled": True,
                "message": "已停止等待并尝试取消；外部操作可能已生效，请核实，未自动重试。"}

    def get_personal_kb() -> PersonalKnowledgeBase:
        kb = app.state.personal_kb
        if kb is None:
            raise ProviderError(503, "personal_kb_disabled", "个人知识库未配置存储位置。")
        return kb

    @app.get("/api/knowledge/personal")
    async def personal_kb_list(limit: int = Query(default=50, ge=1, le=200),
                               offset: int = Query(default=0, ge=0),
                               library_id: str | None = Query(default=None, max_length=64)):
        return await asyncio.to_thread(get_personal_kb().list_documents, limit, offset, library_id)

    @app.get("/api/knowledge/personal/{document_id}/original")
    async def personal_kb_original(document_id: str, version: str | None = Query(default=None, min_length=1, max_length=200)):
        filename, raw = await asyncio.to_thread(get_personal_kb().original, document_id, version)
        return Response(content=raw, media_type="application/octet-stream",
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(filename)})

    @app.get("/api/knowledge/personal/{document_id}/chunks")
    async def personal_kb_chunks(document_id: str,
                                 version: str | None = Query(default=None, min_length=1, max_length=200),
                                 limit: int = Query(default=50, ge=1, le=200),
                                 offset: int = Query(default=0, ge=0)):
        return await asyncio.to_thread(get_personal_kb().list_chunks, document_id, version, limit, offset)

    async def read_document_upload(request: Request):
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > MAX_FILE_BYTES:
                raise ProviderError(413, "kb_size", "文件不能超过 10MB。")
            raw.extend(chunk)
        return bytes(raw)

    def audit_secrets():
        config = app.state.service.settings
        values = [getattr(config, name).get_secret_value() for name in ("api_key", "rt_api_key", "tts_api_key")]
        values.append(config.web_search_api_key.get_secret_value())
        for cfg in app.state.external_tools.items.values():
            values.extend(secret_values(cfg.request))
        return [value for value in values if value]

    async def record_audit(surface, **fields):
        if app.state.audit is None:
            return None
        return await asyncio.to_thread(app.state.audit.record, surface, secrets=audit_secrets(), **fields)

    async def publish_document_upload(kb, filename, raw, title="", group="", document_id=None, library_id=None):
        if app.state.kb_index_lock.locked():
            raise ProviderError(409, "kb_index_busy", "已有资料正在建立索引，请稍后再上传。")
        async with app.state.kb_index_lock:
            try:
                if app.state.service.settings.embedding_enabled and app.state.embedder is None:
                    raise KnowledgeError("embedding_config", "已启用向量化，但缺少百炼业务空间或密钥。", 503)
                prepared = await asyncio.to_thread(kb.prepare_document, filename, raw, title, group, document_id, library_id)
                embedder = app.state.embedder
                blobs = None
                if embedder is not None:
                    blobs = []
                    chunks = prepared["chunks"]
                    for start in range(0, len(chunks), embedder.batch_size):
                        texts = [chunk["text"] for chunk in chunks[start:start + embedder.batch_size]]
                        vectors = await embedder.embed(texts)
                        blobs.extend(to_blob(vector) for vector in vectors)
                    if len(blobs) != len(chunks):
                        raise EmbeddingError("embedding_count", "资料向量不完整，未发布新版本。")
                return await asyncio.to_thread(kb.publish_document, prepared, blobs,
                    embedder.model if embedder else None, embedder.dimensions if embedder else None)
            except (KnowledgeError, EmbeddingError) as error:
                await record_audit("kb_ingest", query_summary=filename, status="error", error_code=error.code,
                    parse_errors=getattr(error, "diagnostics", None) or [{"error_code": error.code,
                        "message": str(error)}])
                if isinstance(error, EmbeddingError):
                    raise ProviderError(503, error.code, "向量索引创建失败，旧资料保持不变；未自动重试。") from None
                raise ProviderError(error.status, error.code, error.message) from None

    @app.post("/api/knowledge/personal/upload")
    async def personal_kb_upload(request: Request):
        kb = get_personal_kb()
        raw = await read_document_upload(request)
        filename = urllib.parse.unquote(request.headers.get("x-doc-filename", "")) or "upload.txt"
        title = urllib.parse.unquote(request.headers.get("x-doc-title", ""))
        group = urllib.parse.unquote(request.headers.get("x-doc-group", ""))
        library_id = urllib.parse.unquote(request.headers.get("x-doc-library", "")) or None
        if len(title) > 200 or len(group) > 80 or (library_id and len(library_id) > 64):
            raise ProviderError(422, "kb_metadata", "名称不能超过 200 字，分组不能超过 80 字。")
        return await publish_document_upload(kb, filename, raw, title, group, library_id=library_id)

    @app.post("/api/knowledge/personal/{document_id}/replace")
    async def personal_kb_replace(document_id: str, request: Request):
        kb = get_personal_kb()
        raw = await read_document_upload(request)
        filename = urllib.parse.unquote(request.headers.get("x-doc-filename", "")) or "upload.txt"
        return await publish_document_upload(kb, filename, raw, document_id=document_id)

    @app.patch("/api/knowledge/personal/{document_id}")
    async def personal_kb_rename(document_id: str, update: PersonalKnowledgeRename):
        try:
            return await asyncio.to_thread(get_personal_kb().rename_document,
                                           document_id, update.title, update.group)
        except KnowledgeError as error:
            raise ProviderError(error.status, error.code, error.message) from error

    @app.delete("/api/knowledge/personal/{document_id}", status_code=204)
    async def personal_kb_delete(document_id: str):
        try:
            await asyncio.to_thread(get_personal_kb().delete_document, document_id)
        except KnowledgeError as error:
            raise ProviderError(error.status, error.code, error.message) from error
        return Response(status_code=204)

    @app.get("/api/knowledge/libraries")
    async def list_kb_libraries():
        return await asyncio.to_thread(get_personal_kb().list_libraries)

    @app.post("/api/knowledge/libraries", status_code=201)
    async def create_kb_library(body: LibraryCreate):
        try:
            return await asyncio.to_thread(get_personal_kb().create_library, body.name)
        except KnowledgeError as error:
            raise ProviderError(error.status, error.code, error.message) from error

    @app.patch("/api/knowledge/libraries/{library_id}")
    async def rename_kb_library(library_id: str, body: LibraryRename):
        try:
            return await asyncio.to_thread(get_personal_kb().rename_library, library_id, body.name)
        except KnowledgeError as error:
            raise ProviderError(error.status, error.code, error.message) from error

    @app.delete("/api/knowledge/libraries/{library_id}", status_code=204)
    async def delete_kb_library(library_id: str):
        async with app.state.operation_lock:
            # 采用先取消选用再删除，避免 .env 与 SQLite 跨存储提交失败留下失效选择。
            if library_id in (app.state.service.settings.selected_kb_ids or []):
                raise ProviderError(409, "kb_library_selected",
                    "该知识库正被助手使用，请先在助手配置取消选择并保存，再删除。")
            try:
                await asyncio.to_thread(get_personal_kb().delete_library, library_id)
            except KnowledgeError as error:
                raise ProviderError(error.status, error.code, error.message) from error
            refresh_tools()
        return Response(status_code=204)

    @app.post("/api/knowledge/personal/search")
    async def personal_kb_search(body: PersonalKnowledgeSearchRequest):
        kb = get_personal_kb()
        settings = app.state.service.settings
        scope_ids = [body.library_id] if body.library_id else (settings.selected_kb_ids or [])
        started = time.perf_counter()
        calls = []
        result = {"query": body.query, "status": "empty", "hit": False, "matches": [], "parse_errors": [],
                  "hybrid": body.hybrid, "retrieval_mode": "hybrid" if body.hybrid else "keyword",
                  "score_type": "rrf" if body.hybrid else "bm25", "vector_index": None}
        try:
            if scope_ids and not settings.personal_kb_enabled:
                raise KnowledgeError("personal_kb_disabled", "个人知识库检索已停用。", 503)
            if scope_ids:
                await asyncio.to_thread(kb.assert_libraries, scope_ids)
                await asyncio.to_thread(kb.assert_group, body.group, scope_ids)
            query_vector, query_model = None, None
            if body.hybrid and scope_ids:
                embedder = app.state.embedder
                if embedder is None:
                    raise KnowledgeError("embedding_disabled", "向量检索未启用或缺少百炼密钥/业务空间。", 503)
                coverage = await asyncio.to_thread(kb.vector_coverage, embedder.model, embedder.dimensions, body.group, scope_ids)
                if not coverage["ready"]:
                    raise KnowledgeError("kb_vectors_missing", "所选资料向量不完整或模型已改变，请重新建立向量索引。", 503)
                if coverage["total_chunks"]:
                    embedding_started = time.perf_counter()
                    call = {"tool_name": "embedding", "trigger_question": body.query,
                            "request": {"model": embedder.model, "dimensions": embedder.dimensions, "input_count": 1},
                            "response": None, "http_status": None, "status": "error", "error_code": None}
                    calls.append(call)
                    try:
                        query_vector = (await embedder.embed([body.query]))[0]
                    except EmbeddingError as error:
                        call["error_code"] = error.code
                        raise
                    finally:
                        call["elapsed_ms"] = int((time.perf_counter() - embedding_started) * 1000)
                    call["status"] = "ok"
                    call["response"] = {"vector_count": 1, "dimensions": len(query_vector)}
                    query_model = embedder.model
                else:
                    result = {"query": body.query, "status": "empty", "hit": False, "matches": [],
                              "hybrid": True, "retrieval_mode": "hybrid", "score_type": "rrf", "vector_index": coverage}
            if scope_ids and (not body.hybrid or query_vector is not None):
                result = await asyncio.to_thread(kb.search, body.query, body.top_k, body.group, query_vector, query_model, scope_ids)
        except (KnowledgeError, EmbeddingError) as error:
            await record_audit("kb_search", query_summary=body.query, question=body.query, top_k=body.top_k,
                status="unavailable" if isinstance(error, EmbeddingError) or error.status == 503 else "error",
                error_code=error.code, calls=calls, elapsed_ms=int((time.perf_counter() - started) * 1000))
            if isinstance(error, EmbeddingError):
                raise ProviderError(503, error.code, "向量检索暂不可用，未自动回退成关键词检索。") from None
            raise ProviderError(error.status, error.code, error.message) from None
        matches = result.get("matches", [])
        snapshots = [{**match, "sent_to_model": False, "cited": False} for match in matches]
        sources = [{"doc_id": match["document_id"], "filename": match["filename"],
                    "ordinal": match["ordinal"], "page": match.get("page"),
                    "score": match.get("score"), "score_type": match.get("score_type")} for match in matches]
        audit_id = await record_audit("kb_search", query_summary=body.query, question=body.query, hit=bool(matches),
            top_k=body.top_k, sources=sources, snapshots=snapshots, calls=calls, parse_errors=result.get("parse_errors", []),
            elapsed_ms=int((time.perf_counter() - started) * 1000), status="ok" if matches else "empty")
        return {**result, "audit_id": audit_id}

    @app.get("/api/insights/kb")
    async def insights_kb(limit: int = Query(default=50, ge=1, le=200),
                          offset: int = Query(default=0, ge=0),
                          q: str = Query(default="", max_length=200),
                          answer_type: str | None = Query(default=None, max_length=40),
                          status: str | None = Query(default=None, max_length=40),
                          tool_name: str | None = Query(default=None, max_length=80),
                          since: str | None = Query(default=None, max_length=40),
                          until: str | None = Query(default=None, max_length=40)):
        if app.state.audit is None:
            return {"items": [], "total": 0}
        return await asyncio.to_thread(app.state.audit.list_kb, limit, offset, q=q,
            answer_type=answer_type, status=status, tool_name=tool_name, since=since, until=until)

    @app.get("/api/insights/tools")
    async def insights_tools(limit: int = Query(default=50, ge=1, le=200),
                             offset: int = Query(default=0, ge=0),
                             q: str = Query(default="", max_length=200),
                             answer_type: str | None = Query(default=None, max_length=40),
                             status: str | None = Query(default=None, max_length=40),
                             tool_name: str | None = Query(default=None, max_length=80),
                             since: str | None = Query(default=None, max_length=40),
                             until: str | None = Query(default=None, max_length=40)):
        if app.state.audit is None:
            return {"items": [], "total": 0}
        return await asyncio.to_thread(app.state.audit.list_tools, limit, offset, q=q,
            answer_type=answer_type, status=status, tool_name=tool_name, since=since, until=until)

    @app.get("/api/insights/traces")
    async def insights_traces(limit: int = Query(default=50, ge=1, le=200),
                              offset: int = Query(default=0, ge=0),
                              q: str = Query(default="", max_length=200),
                              source: str | None = Query(default=None, max_length=40),
                              status: str | None = Query(default=None, max_length=40),
                              since: str | None = Query(default=None, max_length=40),
                              until: str | None = Query(default=None, max_length=40)):
        if app.state.audit is None:
            return {"items": [], "total": 0}
        return await asyncio.to_thread(
            app.state.audit.list_traces, limit, offset, q=q,
            source=source, status=status, since=since, until=until,
        )

    @app.get("/api/insights/traces/{trace_id}")
    async def insights_trace_detail(trace_id: str):
        if app.state.audit is None:
            raise ProviderError(404, "insight_not_found", "追踪记录不存在。")
        detail = await asyncio.to_thread(app.state.audit.trace_detail, trace_id)
        if detail is None:
            raise ProviderError(404, "insight_not_found", "追踪记录不存在。")
        return detail

    @app.delete("/api/insights/traces/{trace_id}", status_code=204)
    async def delete_insight_trace(trace_id: str, confirm: bool = Query(default=False)):
        if app.state.audit is None:
            raise ProviderError(404, "insight_not_found", "追踪记录不存在。")
        if not confirm:
            raise ProviderError(422, "confirm_required", "删除记录需明确确认。")
        if not await asyncio.to_thread(app.state.audit.delete_trace, trace_id):
            raise ProviderError(404, "insight_not_found", "追踪记录不存在。")
        return Response(status_code=204)

    @app.get("/api/insights/errors")
    async def insights_errors(limit: int = Query(default=50, ge=1, le=200),
                              offset: int = Query(default=0, ge=0),
                              source: str = Query(default="", max_length=32),
                              q: str = Query(default="", max_length=200)):
        err_log = getattr(app.state, "error_log", None)
        if err_log is None:
            return {"items": [], "total": 0}
        return await asyncio.to_thread(err_log.list, limit, offset, source=source, q=q)

    @app.delete("/api/insights/errors")
    async def clear_insights_errors():
        err_log = getattr(app.state, "error_log", None)
        deleted = await asyncio.to_thread(err_log.clear) if err_log is not None else 0
        return {"deleted": deleted}

    @app.get("/api/insights/parsing")
    async def insights_parsing(limit: int = Query(default=50, ge=1, le=200),
                               offset: int = Query(default=0, ge=0)):
        if app.state.audit is None:
            return {"items": [], "total": 0}
        return await asyncio.to_thread(app.state.audit.list_parsing, limit, offset)

    @app.get("/api/insights/parsing/{audit_id}")
    async def insights_parse_detail(audit_id: int):
        if app.state.audit is None:
            raise ProviderError(404, "insight_not_found", "解析记录不存在。")
        detail = await asyncio.to_thread(app.state.audit.detail, audit_id, "kb_ingest")
        if detail is None:
            raise ProviderError(404, "insight_not_found", "解析记录不存在。")
        return detail

    @app.get("/api/insights/kb/{audit_id}")
    async def insights_kb_detail(audit_id: int):
        if app.state.audit is None:
            raise ProviderError(404, "insight_not_found", "洞察记录不存在。")
        detail = await asyncio.to_thread(app.state.audit.detail, audit_id, "kb_search")
        if detail is None:
            raise ProviderError(404, "insight_not_found", "洞察记录不存在。")
        if app.state.personal_kb is not None and detail["snapshots"]:
            detail["snapshots"] = await asyncio.to_thread(app.state.personal_kb.snapshot_availability, detail["snapshots"])
        return detail

    @app.get("/api/insights/tools/{audit_id}")
    async def insights_tool_detail(audit_id: int):
        if app.state.audit is None:
            raise ProviderError(404, "insight_not_found", "洞察记录不存在。")
        detail = await asyncio.to_thread(app.state.audit.detail, audit_id, "tool_call")
        if detail is None:
            raise ProviderError(404, "insight_not_found", "洞察记录不存在。")
        if app.state.personal_kb is not None and detail["snapshots"]:
            detail["snapshots"] = await asyncio.to_thread(app.state.personal_kb.snapshot_availability, detail["snapshots"])
        return detail

    @app.patch("/api/insights/kb/{audit_id}")
    async def insights_kb_correct(audit_id: int, body: InsightCorrectAnswer):
        if app.state.audit is None:
            raise ProviderError(404, "insight_not_found", "洞察记录不存在。")
        detail = await asyncio.to_thread(app.state.audit.save_correct_answer, audit_id,
                                         body.correct_answer, audit_secrets())
        if detail is None:
            raise ProviderError(404, "insight_not_found", "洞察记录不存在。")
        return await insights_kb_detail(audit_id)

    async def clear_insights(surfaces, body):
        if app.state.audit is None:
            raise ProviderError(404, "insight_not_found", "洞察记录不存在。")
        if not body.confirm:
            raise ProviderError(422, "confirm_required", "清空记录需明确确认。")
        try:
            deleted = await asyncio.to_thread(app.state.audit.delete_filtered, surfaces,
                expected_total=body.expected_total, q=body.q, answer_type=body.answer_type,
                status=body.status, tool_name=body.tool_name, since=body.since, until=body.until)
        except FilterRequired:
            raise ProviderError(422, "filter_required", "清空必须带筛选条件，不能删除全部记录。") from None
        except CountMismatch as error:
            raise ProviderError(409, "count_changed", f"匹配记录已变化（当前 {error.count} 条），请刷新后重新确认。") from None
        return {"deleted": deleted}

    @app.delete("/api/insights/kb/{audit_id}", status_code=204)
    async def delete_insight_kb(audit_id: int, confirm: bool = Query(default=False)):
        if app.state.audit is None:
            raise ProviderError(404, "insight_not_found", "洞察记录不存在。")
        if not confirm:
            raise ProviderError(422, "confirm_required", "删除记录需明确确认。")
        if not await asyncio.to_thread(app.state.audit.delete_one, audit_id, "kb_search"):
            raise ProviderError(404, "insight_not_found", "洞察记录不存在。")
        return Response(status_code=204)

    @app.delete("/api/insights/tools/{audit_id}", status_code=204)
    async def delete_insight_tool(audit_id: int, confirm: bool = Query(default=False)):
        if app.state.audit is None:
            raise ProviderError(404, "insight_not_found", "洞察记录不存在。")
        if not confirm:
            raise ProviderError(422, "confirm_required", "删除记录需明确确认。")
        if not await asyncio.to_thread(app.state.audit.delete_one, audit_id, "tool_call"):
            raise ProviderError(404, "insight_not_found", "洞察记录不存在。")
        return Response(status_code=204)

    @app.post("/api/insights/kb/clear")
    async def clear_insight_kb(body: InsightClearFilters):
        return await clear_insights(("kb_search",), body)

    @app.post("/api/insights/tools/clear")
    async def clear_insight_tools(body: InsightClearFilters):
        return await clear_insights(("tool_call",), body)

    @app.delete("/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: UUID):
        async with app.state.operation_lock:
            connection = app.state.devices.connection
            if connection is not None and getattr(connection, "voice_session_id", None) == session_id:
                raise ProviderError(409, "session_busy", "设备正在使用该会话，请结束交互后再删除。")
            await app.state.service.delete_session(session_id)
        return Response(status_code=204)

    @app.get("/sessions", response_model=list[SessionSummary])
    async def list_sessions(limit: int | None = Query(default=None, ge=1, le=200),
                            offset: int = Query(default=0, ge=0),
                            q: str = Query(default="", max_length=200)):
        return app.state.service.list_sessions(limit=limit, offset=offset, q=q)

    @app.get("/sessions/{session_id}", response_model=SessionDetail)
    async def get_session(session_id: UUID):
        return app.state.service.session_detail(session_id)

    @app.patch("/sessions/{session_id}", response_model=SessionSummary)
    async def rename_session(session_id: UUID, update: SessionRename):
        async with app.state.operation_lock:
            return await app.state.service.rename_session(session_id, update.title)

    return app


app = create_app()
