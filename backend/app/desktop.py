"""Cross-platform Desktop Node hub and Computer Use bridge (Windows & macOS)."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
import base64
import json
import logging
import os
from pathlib import Path
import secrets
import socket
import tempfile
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
import httpx

from .config import ROOT, Settings
from .llm import ProviderError

logger = logging.getLogger(__name__)
DESKTOP_WS_MAX_BYTES = 6 * 1024 * 1024
DESKTOP_RPC_TIMEOUT = 25.0
SENSITIVE_PATH_PARTS = frozenset({".ssh", ".gnupg", ".aws", ".kube", "keychains"})
SENSITIVE_FILENAMES = frozenset({
    ".env", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", "desktop_nodes.json",
    "assistant_state.sqlite3", "devices.json", "cookies", "login data",
})
SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore", ".jks")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_sensitive_path(path_str: str) -> bool:
    raw = (path_str or "").strip()
    if not raw:
        return False
    normalized = raw.replace("\\", "/")
    parts = [p.lower() for p in normalized.split("/") if p and p != "."]
    if any(part in SENSITIVE_PATH_PARTS for part in parts):
        return True
    name = parts[-1] if parts else ""
    if name in SENSITIVE_FILENAMES or name.startswith(".env."):
        return True
    return any(name.endswith(ext) for ext in SENSITIVE_SUFFIXES)


def _detect_lan_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


@dataclass
class DesktopNodeConnection:
    ws: WebSocket
    hub: DesktopHub
    node_id: str
    name: str
    os_name: str
    hostname: str = ""
    arch: str = ""
    capabilities: list[str] = field(default_factory=list)
    screen: dict = field(default_factory=dict)
    connected_at: str = field(default_factory=_utc_now)
    last_seen_at: str = field(default_factory=_utc_now)
    pending: dict[str, asyncio.Future] = field(default_factory=dict)
    last_screenshot: dict | None = None

    def public(self) -> dict:
        shot = self.last_screenshot
        return {
            "node_id": self.node_id,
            "name": self.name,
            "os": self.os_name,
            "hostname": self.hostname,
            "arch": self.arch,
            "capabilities": list(self.capabilities),
            "screen": dict(self.screen),
            "online": True,
            "connected_at": self.connected_at,
            "last_seen_at": self.last_seen_at,
            "has_screenshot": shot is not None,
            "screenshot_captured_at": shot.get("captured_at") if shot else None,
        }

    async def rpc(self, action: str, params: dict | None = None, timeout: float = DESKTOP_RPC_TIMEOUT) -> dict:
        req_id = uuid4().hex
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self.pending[req_id] = future
        try:
            await self.ws.send_json({
                "type": "rpc_request",
                "request_id": req_id,
                "action": action,
                "params": params or {},
            })
            result = await asyncio.wait_for(future, timeout=max(2.0, min(float(timeout), 45.0)))
        except TimeoutError:
            msg = f"电脑节点 {self.name} 执行 {action} 超时。"
            self.hub.record_error("desktop_rpc_timeout", msg, detail={"node_id": self.node_id, "action": action})
            raise ProviderError(504, "desktop_rpc_timeout", msg) from None
        except (WebSocketDisconnect, ConnectionError, RuntimeError):
            msg = f"电脑节点 {self.name} 连接已断开。"
            self.hub.record_error("desktop_disconnected", msg, detail={"node_id": self.node_id, "action": action})
            raise ProviderError(502, "desktop_disconnected", msg) from None
        except ProviderError as error:
            self.hub.record_error(error.code, error.message, detail={"node_id": self.node_id, "action": action})
            raise
        finally:
            self.pending.pop(req_id, None)
        self.last_seen_at = _utc_now()
        return result if isinstance(result, dict) else {"value": result}

    def handle_message(self, message: dict) -> str | None:
        self.last_seen_at = _utc_now()
        kind = message.get("type")
        if kind == "ping":
            return "pong"
        if kind == "pong":
            return None
        if kind == "hello":
            if isinstance(message.get("screen"), dict):
                self.screen = message["screen"]
            if isinstance(message.get("capabilities"), list):
                self.capabilities = [str(item) for item in message["capabilities"][:24]]
            return None
        if kind == "rpc_response":
            req_id = message.get("request_id")
            if not isinstance(req_id, str):
                return None
            future = self.pending.get(req_id)
            if future is None or future.done():
                return None
            if message.get("ok", True):
                future.set_result(message.get("result"))
            else:
                raw_err = message.get("error")
                err: dict = raw_err if isinstance(raw_err, dict) else {}
                code = str(err.get("code") or "desktop_rpc_failed")
                msg = str(err.get("message") or "桌面节点执行失败。")
                future.set_exception(ProviderError(502, code, msg))
        return None

    def close(self) -> None:
        for future in self.pending.values():
            if not future.done():
                future.set_exception(ProviderError(409, "desktop_disconnected", "电脑节点已断开，操作未确认完成。"))
        self.pending.clear()


class DesktopHub:
    """Manages cross-platform Windows/macOS Desktop Nodes connected over WebSocket."""

    def __init__(
        self,
        path: Path = ROOT / "data" / "desktop_nodes.json",
        port: int = 8003,
        public_origin: str = "",
        public_base_path: str = "",
        lan_host_getter=None,
        settings_getter=None,
    ):
        self.path = path
        self.port = port
        self.public_origin = public_origin.rstrip("/")
        self.public_base_path = public_base_path.rstrip("/")
        self.lan_host_getter = lan_host_getter
        self.settings_getter = settings_getter
        self.lock = asyncio.Lock()
        self.gateway_token: str = ""
        self.default_node_id: str = ""
        self.saved_nodes: dict[str, dict] = {}
        self.active: dict[str, DesktopNodeConnection] = {}
        self.last_error: str | None = None
        self.error_logger: Callable[..., None] | None = None
        self._load()

    def record_error(self, code: str, message: str, *, detail: dict | None = None) -> None:
        cb = self.error_logger
        if cb is not None:
            with suppress(Exception):
                cb("desktop", code, message, detail=detail)

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.gateway_token = str(data.get("gateway_token") or "").strip()
                self.default_node_id = str(data.get("default_node_id") or "").strip()
                raw_nodes = data.get("nodes") or {}
                if isinstance(raw_nodes, dict):
                    self.saved_nodes = {
                        str(k): v for k, v in raw_nodes.items() if isinstance(v, dict)
                    }
            except (OSError, ValueError, TypeError):
                logger.warning("desktop_nodes.json 无法读取，将在新配置写入后重建。")
        if not self.gateway_token:
            self.gateway_token = secrets.token_urlsafe(24)
            self._persist()

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.path.parent,
                prefix="desktop-nodes-", suffix=".tmp", delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(
                    {
                        "gateway_token": self.gateway_token,
                        "default_node_id": self.default_node_id,
                        "nodes": self.saved_nodes,
                    },
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
                handle.flush()
                os.fsync(handle.fileno())
            with suppress(OSError):
                os.chmod(temp_path, 0o600)
            os.replace(temp_path, self.path)
        except OSError:
            logger.warning("desktop_nodes.json 持久化失败。")
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    @property
    def websocket_url(self) -> str:
        if self.public_origin:
            parts = urlsplit(self.public_origin)
            return f"wss://{parts.netloc}{self.public_base_path}/desktop/v1/"
        host = ""
        if self.lan_host_getter is not None:
            with suppress(Exception):
                host = str(self.lan_host_getter() or "").strip()
        if not host:
            host = _detect_lan_ip()
        return f"ws://{host}:{self.port}/desktop/v1/"

    def authorized(self, token: str) -> bool:
        expected = self.gateway_token
        return bool(expected and token and secrets.compare_digest(token.encode("utf-8"), expected.encode("utf-8")))

    async def rotate_token(self) -> dict:
        async with self.lock:
            self.gateway_token = secrets.token_urlsafe(24)
            self._persist()
            for conn in list(self.active.values()):
                with suppress(Exception):
                    await conn.ws.close(code=4002)
            return self.public()

    async def set_default_node(self, node_id: str) -> dict:
        async with self.lock:
            clean = (node_id or "").strip()
            if clean and clean not in self.saved_nodes and clean not in self.active:
                raise ProviderError(404, "desktop_node_not_found", "指定的电脑节点不存在。")
            self.default_node_id = clean
            self._persist()
            return self.public()

    async def delete_node(self, node_id: str) -> dict:
        async with self.lock:
            clean = (node_id or "").strip()
            if clean in self.active:
                conn = self.active.pop(clean)
                with suppress(Exception):
                    await conn.ws.close(code=4003)
            self.saved_nodes.pop(clean, None)
            if self.default_node_id == clean:
                self.default_node_id = next(iter(self.active), "") or next(iter(self.saved_nodes), "")
            self._persist()
            return self.public()

    def list_nodes(self) -> list[dict]:
        seen = set()
        items = []
        for node_id, conn in self.active.items():
            seen.add(node_id)
            item = conn.public()
            item["is_default"] = node_id == self.default_node_id
            items.append(item)
        for node_id, meta in self.saved_nodes.items():
            if node_id in seen:
                continue
            items.append({
                "node_id": node_id,
                "name": meta.get("name") or node_id,
                "os": meta.get("os") or "unknown",
                "hostname": meta.get("hostname") or "",
                "arch": meta.get("arch") or "",
                "capabilities": list(meta.get("capabilities") or []),
                "screen": dict(meta.get("screen") or {}),
                "online": False,
                "connected_at": meta.get("connected_at"),
                "last_seen_at": meta.get("last_seen_at"),
                "has_screenshot": False,
                "screenshot_captured_at": None,
                "is_default": node_id == self.default_node_id,
            })
        items.sort(key=lambda item: (not item["online"], not item["is_default"], item["name"]))
        return items

    def public(self) -> dict:
        ws_url = self.websocket_url
        return {
            "websocket_url": ws_url,
            "gateway_token": self.gateway_token,
            "default_node_id": self.default_node_id,
            "online_count": len(self.active),
            "nodes": self.list_nodes(),
            "last_error": self.last_error,
            "commands": {
                "macos": f'python3 -m desktop_node --server "{ws_url}" --token "{self.gateway_token}"',
                "windows": f'python -m desktop_node --server "{ws_url}" --token "{self.gateway_token}"',
            },
        }

    def resolve_node(self, node_id: str | None = None) -> DesktopNodeConnection:
        target = (node_id or "").strip()
        if target:
            if target in self.active:
                return self.active[target]
            lowered = target.lower()
            matches = [
                conn for conn in self.active.values()
                if lowered in conn.node_id.lower()
                or lowered in conn.name.lower()
                or lowered == conn.os_name.lower()
                or (lowered in {"mac", "macos", "osx", "苹果", "苹果电脑"} and conn.os_name.lower() == "macos")
                or (lowered in {"win", "windows", "pc", "台式机"} and conn.os_name.lower() == "windows")
                or (conn.hostname and lowered in conn.hostname.lower())
            ]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                names = ", ".join(f"{m.name}({m.node_id})" for m in matches)
                raise ProviderError(409, "desktop_node_ambiguous", f"匹配到多个在线电脑节点：{names}，请指定具体 node_id。")
            online = ", ".join(f"{c.name}({c.node_id})" for c in self.active.values()) or "无"
            raise ProviderError(409, "desktop_offline", f"未找到在线节点 {target}；当前在线电脑：{online}。")
        if self.default_node_id and self.default_node_id in self.active:
            return self.active[self.default_node_id]
        if len(self.active) == 1:
            return next(iter(self.active.values()))
        if len(self.active) > 1:
            names = ", ".join(f"{c.name}({c.node_id})" for c in self.active.values())
            raise ProviderError(409, "desktop_node_ambiguous", f"当前同时在线多台电脑（{names}），请指明要操作哪一台或在终端节点中设为默认。")
        raise ProviderError(409, "desktop_offline", "目前没有在线的个人电脑节点；请先在 Windows 或 Mac 上启动 desktop_node 连接。")

    async def disconnect(self) -> None:
        for conn in list(self.active.values()):
            conn.close()
            with suppress(Exception):
                await conn.ws.close(code=1001)
        self.active.clear()

    async def inspect_screen(self, node_id: str | None = None, question: str = "", analyze_vision: bool = True) -> dict:
        conn = self.resolve_node(node_id)
        shot = await conn.rpc("screenshot", {"max_width": 1280, "max_height": 800, "quality": 80}, timeout=25.0)
        b64 = shot.get("image_base64") or ""
        mime = str(shot.get("mime_type") or "image/jpeg")
        img_w = int(shot.get("image_width") or shot.get("width") or 0)
        img_h = int(shot.get("image_height") or shot.get("height") or 0)
        scr_w = int(shot.get("screen_width") or conn.screen.get("width") or img_w or 0)
        scr_h = int(shot.get("screen_height") or conn.screen.get("height") or img_h or 0)
        active_window = shot.get("active_window") or {}
        captured_at = _utc_now()
        if b64:
            with suppress(ValueError, TypeError):
                raw_bytes = base64.b64decode(b64)
                conn.last_screenshot = {
                    "bytes": raw_bytes,
                    "mime_type": mime,
                    "image_width": img_w,
                    "image_height": img_h,
                    "screen_width": scr_w,
                    "screen_height": scr_h,
                    "active_window": active_window,
                    "captured_at": captured_at,
                }
        out: dict = {
            "node_id": conn.node_id,
            "node_name": conn.name,
            "os": conn.os_name,
            "active_window": active_window,
            "screen": {"width": scr_w, "height": scr_h},
            "image": {"width": img_w, "height": img_h, "mime_type": mime},
            "captured_at": captured_at,
            "screenshot_url": f"/api/desktop/nodes/{conn.node_id}/screenshot",
        }
        if img_w and img_h and scr_w and scr_h:
            out["coordinate_hint"] = (
                f"当前截图尺寸为 {img_w}x{img_h}，对应屏幕坐标 {scr_w}x{scr_h}；"
                "调用 desktop_gui_action 时传入截图上的 (x, y) 即可（coord_space='image' 会自动换算）。"
            )
        clean_q = (question or "").strip()
        if analyze_vision and b64 and clean_q:
            vision = await self._analyze_screenshot(
                b64=b64, mime=mime, question=clean_q,
                img_w=img_w, img_h=img_h, scr_w=scr_w, scr_h=scr_h, os_name=conn.os_name,
            )
            out.update(vision)
        return out

    async def _analyze_screenshot(
        self, *, b64: str, mime: str, question: str,
        img_w: int, img_h: int, scr_w: int, scr_h: int, os_name: str,
    ) -> dict:
        settings: Settings | None = self.settings_getter() if self.settings_getter is not None else None
        if settings is None:
            return {"vision_analysis": None, "vision_note": "未加载模型设置，已返回窗口信息与截图尺寸。"}
        configured_model = (getattr(settings, "desktop_vision_model", "") or "").strip()
        if (getattr(settings, "rt_provider", "") == "bailian"
                and settings.rt_api_key.get_secret_value().strip()
                and (settings.voice_mode == "realtime" or not settings.model.strip() or configured_model.startswith("qwen"))):
            ws_id = (settings.rt_workspace or "").strip()
            base_url = (
                f"https://{ws_id}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
                if ws_id else "https://dashscope.aliyuncs.com/compatible-mode/v1"
            )
            api_key = settings.rt_api_key.get_secret_value().strip()
            model = configured_model or "qwen3-vl-plus"
        else:
            base_url = settings.base_url.rstrip("/")
            api_key = settings.api_key.get_secret_value().strip()
            model = configured_model or settings.model.strip()
        if not base_url or not api_key or not model:
            return {"vision_analysis": None, "vision_note": "未配置支持视觉的模型接口，已返回窗口信息与截图尺寸。"}
        prompt = (
            f"这是 {os_name} 电脑当前屏幕截图（图像尺寸 {img_w}x{img_h}，逻辑屏幕 {scr_w}x{scr_h}）。\n"
            f"用户/代理观察问题：{question}\n"
            "请简明准确地描述画面中可见的内容，回答问题；如果需要定位或点击某按钮/输入框，"
            f"请给出它在图像坐标系（x: 0..{img_w}, y: 0..{img_h}）中的中心点像素坐标 [x, y]。"
            "只报告图像中真实看到的元素，看不到时明确说明。"
        )
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    ],
                }
            ],
            "max_tokens": min(settings.max_tokens or 600, 800),
            "temperature": 0.1,
        }
        try:
            async with httpx.AsyncClient(timeout=min(float(settings.timeout_seconds), 25.0)) as client:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=payload,
                )
            if resp.status_code >= 400:
                err_msg = f"当前模型({model})视觉看图返回 HTTP {resp.status_code}，可能不支持图片输入。"
                self.record_error("desktop_vision_http_error", err_msg, detail={"model": model, "status": resp.status_code})
                return {
                    "vision_analysis": None,
                    "vision_error": err_msg,
                }
            data = resp.json()
            choice = (data.get("choices") or [{}])[0]
            content = ((choice.get("message") or {}).get("content")) or ""
            return {"vision_analysis": str(content).strip()}
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as error:
            err_msg = f"屏幕视觉解析请求失败：{type(error).__name__}"
            self.record_error("desktop_vision_error", err_msg, detail={"model": model})
            return {"vision_analysis": None, "vision_error": err_msg}

    def convert_coordinates(
        self, conn: DesktopNodeConnection, x: int | None, y: int | None, coord_space: str = "image",
    ) -> tuple[int | None, int | None]:
        if x is None or y is None or coord_space == "screen":
            return x, y
        shot = conn.last_screenshot
        if not shot:
            return x, y
        img_w = shot.get("image_width") or 0
        img_h = shot.get("image_height") or 0
        scr_w = shot.get("screen_width") or 0
        scr_h = shot.get("screen_height") or 0
        if img_w > 0 and img_h > 0 and scr_w > 0 and scr_h > 0:
            return round(x * scr_w / img_w), round(y * scr_h / img_h)
        return x, y

    def mount_routes(self, gateway_app: FastAPI) -> None:
        @gateway_app.websocket("/desktop/v1/")
        @gateway_app.websocket("/desktop/v1")
        async def desktop_ws(ws: WebSocket):
            auth = ws.headers.get("authorization", "")
            token = auth[7:].strip() if auth.startswith("Bearer ") else ws.headers.get("x-desktop-token", "").strip()
            if not self.authorized(token):
                self.last_error = "桌面节点鉴权失败，请检查 Token。"
                self.record_error("desktop_auth_failed", self.last_error)
                await ws.close(code=1008)
                return
            await ws.accept()
            conn: DesktopNodeConnection | None = None
            try:
                raw_hello = await asyncio.wait_for(ws.receive_text(), 10.0)
                if len(raw_hello) > 32768:
                    await ws.close(code=1009)
                    return
                hello = json.loads(raw_hello)
                if not isinstance(hello, dict) or hello.get("type") != "hello":
                    await ws.close(code=1008)
                    return
                raw_id = str(hello.get("node_id") or hello.get("hostname") or "").strip()
                node_id = raw_id[:64] if raw_id else f"node-{uuid4().hex[:8]}"
                name = str(hello.get("name") or hello.get("hostname") or node_id).strip()[:80]
                os_name = str(hello.get("os") or "unknown").strip().lower()[:32]
                hostname = str(hello.get("hostname") or "").strip()[:80]
                arch = str(hello.get("arch") or "").strip()[:32]
                caps = [str(item)[:40] for item in (hello.get("capabilities") or []) if isinstance(item, str)][:24]
                raw_screen = hello.get("screen")
                screen: dict = raw_screen if isinstance(raw_screen, dict) else {}
                conn = DesktopNodeConnection(
                    ws=ws, hub=self, node_id=node_id, name=name,
                    os_name=os_name, hostname=hostname, arch=arch,
                    capabilities=caps, screen=screen,
                )
                old_conn: DesktopNodeConnection | None = None
                async with self.lock:
                    old_conn = self.active.get(node_id)
                    self.active[node_id] = conn
                    self.saved_nodes[node_id] = {
                        "node_id": node_id,
                        "name": name,
                        "os": os_name,
                        "hostname": hostname,
                        "arch": arch,
                        "capabilities": caps,
                        "screen": screen,
                        "connected_at": conn.connected_at,
                        "last_seen_at": conn.last_seen_at,
                    }
                    if not self.default_node_id:
                        self.default_node_id = node_id
                    self._persist()
                if old_conn is not None and old_conn is not conn:
                    old_conn.close()
                    with suppress(Exception):
                        await old_conn.ws.close(code=4001)
                self.last_error = None
                await ws.send_json({
                    "type": "welcome",
                    "node_id": node_id,
                    "default_node_id": self.default_node_id,
                    "server_time": _utc_now(),
                })
                logger.info("desktop_node_connected node_id=%s os=%s name=%s", node_id, os_name, name)
                while True:
                    packet = await asyncio.wait_for(ws.receive(), 90.0)
                    if packet["type"] == "websocket.disconnect":
                        break
                    text = packet.get("text")
                    if not text:
                        continue
                    if len(text.encode("utf-8")) > DESKTOP_WS_MAX_BYTES:
                        await ws.close(code=1009)
                        break
                    msg = json.loads(text)
                    if not isinstance(msg, dict):
                        continue
                    reply = conn.handle_message(msg)
                    if reply == "pong":
                        await ws.send_json({"type": "pong", "server_time": _utc_now()})
            except (WebSocketDisconnect, TimeoutError, json.JSONDecodeError, ValueError, RuntimeError) as error:
                logger.info("desktop_node_disconnected node_id=%s reason=%s",
                            conn.node_id if conn else "unknown", type(error).__name__)
            finally:
                if conn is not None:
                    conn.close()
                    async with self.lock:
                        if self.active.get(conn.node_id) is conn:
                            del self.active[conn.node_id]
                            if conn.node_id in self.saved_nodes:
                                self.saved_nodes[conn.node_id]["last_seen_at"] = conn.last_seen_at
                                self._persist()
                with suppress(Exception):
                    await ws.close()


def mount_desktop_admin_routes(app: FastAPI, get_hub, record_audit=None) -> None:
    @app.get("/api/desktop")
    async def desktop_status():
        return get_hub().public()

    @app.post("/api/desktop/token/rotate")
    async def desktop_rotate_token():
        return await get_hub().rotate_token()

    @app.put("/api/desktop/default")
    async def desktop_set_default(body: dict):
        node_id = str(body.get("node_id") or "") if isinstance(body, dict) else ""
        return await get_hub().set_default_node(node_id)

    @app.delete("/api/desktop/nodes/{node_id}")
    async def desktop_delete_node(node_id: str):
        return await get_hub().delete_node(node_id)

    @app.post("/api/desktop/nodes/{node_id}/screenshot")
    async def desktop_refresh_screenshot(node_id: str):
        return await get_hub().inspect_screen(node_id=node_id, question="", analyze_vision=False)

    @app.get("/api/desktop/nodes/{node_id}/screenshot")
    async def desktop_latest_screenshot(node_id: str):
        conn = get_hub().active.get(node_id)
        if conn is None or conn.last_screenshot is None:
            raise HTTPException(status_code=404, detail={"code": "screenshot_missing", "message": "尚无最新屏幕截图。"})
        shot = conn.last_screenshot
        return Response(
            content=shot["bytes"],
            media_type=shot.get("mime_type") or "image/jpeg",
            headers={"Cache-Control": "no-store"},
        )
