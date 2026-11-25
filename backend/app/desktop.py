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
import re
import secrets
import socket
import tempfile
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
import httpx

from .config import ROOT, Settings
from .llm import ProviderError

logger = logging.getLogger(__name__)
DESKTOP_WS_MAX_BYTES = 6 * 1024 * 1024
DESKTOP_RPC_TIMEOUT = 25.0
_ERROR_LOGGED = "_error_logged"
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
    last_som_screenshot: dict | None = None
    last_ui_elements: list[dict] = field(default_factory=list)

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
            err = ProviderError(504, "desktop_rpc_timeout", msg)
            self.hub.record_error("desktop_rpc_timeout", msg, detail={"node_id": self.node_id, "action": action})
            setattr(err, _ERROR_LOGGED, True)
            raise err from None
        except (WebSocketDisconnect, ConnectionError, RuntimeError):
            msg = f"电脑节点 {self.name} 连接已断开。"
            err = ProviderError(502, "desktop_disconnected", msg)
            self.hub.record_error("desktop_disconnected", msg, detail={"node_id": self.node_id, "action": action})
            setattr(err, _ERROR_LOGGED, True)
            raise err from None
        except ProviderError as error:
            self.hub.record_error(error.code, error.message, detail={"node_id": self.node_id, "action": action})
            setattr(error, _ERROR_LOGGED, True)
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
        self.last_screenshot = None
        self.last_som_screenshot = None
        self.last_ui_elements.clear()


_VISION_BRACKET_RE = re.compile(
    r"\[\s*(\d{1,4})\s*,\s*(\d{1,4})(?:\s*,\s*(\d{1,4})\s*,\s*(\d{1,4}))?\s*\]"
)


def _extract_vision_screen_coords(
    text: str, *, norm_1000: bool, img_w: int, img_h: int, scr_w: int, scr_h: int,
) -> list[dict]:
    if not text or scr_w <= 0 or scr_h <= 0:
        return []
    out: list[dict] = []
    for match in _VISION_BRACKET_RE.finditer(text):
        nums = [int(g) for g in match.groups() if g is not None]
        if len(nums) == 4:
            cx = (nums[0] + nums[2]) / 2.0
            cy = (nums[1] + nums[3]) / 2.0
        elif len(nums) == 2:
            cx, cy = float(nums[0]), float(nums[1])
        else:
            continue
        if norm_1000 and max(nums) <= 1000:
            sx = round(cx * scr_w / 1000.0)
            sy = round(cy * scr_h / 1000.0)
        elif img_w > 0 and img_h > 0:
            sx = round(cx * scr_w / img_w)
            sy = round(cy * scr_h / img_h)
        else:
            continue
        if 0 <= sx <= scr_w and 0 <= sy <= scr_h:
            out.append({"screen_x": sx, "screen_y": sy, "source": match.group(0)})
            if len(out) >= 6:
                break
    return out


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
        self._vision_client: httpx.AsyncClient | None = None
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
        if self._vision_client is not None and not self._vision_client.is_closed:
            await self._vision_client.aclose()
        self._vision_client = None

    async def inspect_screen(
        self,
        node_id: str | None = None,
        question: str = "",
        analyze_vision: bool = True,
        include_som: bool = True,
    ) -> dict:
        conn = self.resolve_node(node_id)
        shot = await conn.rpc(
            "screenshot",
            {"max_width": 1280, "max_height": 800, "quality": 80, "som": include_som},
            timeout=25.0,
        )
        b64 = shot.get("image_base64") or ""
        mime = str(shot.get("mime_type") or "image/jpeg")
        som_b64 = shot.get("som_image_base64") or ""
        som_mime = str(shot.get("som_mime_type") or mime)
        som_annotated = bool(shot.get("som_annotated") and som_b64)
        img_w = int(shot.get("image_width") or shot.get("width") or 0)
        img_h = int(shot.get("image_height") or shot.get("height") or 0)
        scr_w = int(shot.get("screen_width") or conn.screen.get("width") or img_w or 0)
        scr_h = int(shot.get("screen_height") or conn.screen.get("height") or img_h or 0)
        active_window = shot.get("active_window") or {}
        raw_focused = shot.get("focused_element")
        focused_element = raw_focused if isinstance(raw_focused, dict) else None
        raw_ui = shot.get("ui_elements")
        raw_elements: list = raw_ui if isinstance(raw_ui, list) else []
        clean_elements: list[dict] = []
        for elem in raw_elements[:70]:
            if not isinstance(elem, dict):
                continue
            try:
                cx = int(elem["x"])
                cy = int(elem["y"])
            except (KeyError, TypeError, ValueError):
                continue
            item = {
                "index": len(clean_elements),
                "role": str(elem.get("role") or "")[:32],
                "name": str(elem.get("name") or "")[:64],
                "value": str(elem.get("value") or "")[:60],
                "x": cx,
                "y": cy,
                "focused": bool(elem.get("focused")),
            }
            if elem.get("width") is not None and elem.get("height") is not None:
                with suppress(TypeError, ValueError):
                    item["width"] = int(elem["width"])
                    item["height"] = int(elem["height"])
            clean_elements.append(item)
        conn.last_ui_elements = clean_elements.copy()
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
        vision_b64 = som_b64 or b64
        vision_mime = som_mime if som_b64 else mime
        if vision_b64:
            conn.last_som_screenshot = {
                "data_url": f"data:{vision_mime};base64,{vision_b64}",
                "width": img_w,
                "height": img_h,
                "screen_width": scr_w,
                "screen_height": scr_h,
                "som_annotated": som_annotated,
                "captured_at": captured_at,
            }
        else:
            conn.last_som_screenshot = None
        out: dict = {
            "node_id": conn.node_id,
            "node_name": conn.name,
            "os": conn.os_name,
            "active_window": active_window,
            "focused_element": focused_element,
            "screen": {"width": scr_w, "height": scr_h},
            "image": {"width": img_w, "height": img_h, "mime_type": mime},
            "captured_at": captured_at,
            "som_annotated": som_annotated,
            "screenshot_url": f"/api/desktop/nodes/{conn.node_id}/screenshot",
        }
        if clean_elements:
            out["ui_elements"] = clean_elements
            out["targeting_hint"] = (
                "已获取当前窗口控件树 ui_elements"
                + ("（截图上已绘制对应 [index] 高亮方框 Set-of-Mark）" if som_annotated else "")
                + "：如果目标按钮/搜索框/联系人出现在 ui_elements 中，"
                "调用 desktop_gui_action 时直接传 element_index=<index>（精准度 100%，无需估算坐标）；"
                "列表中未覆盖的自绘区域再用图像坐标或 suggested_screen_coords。"
            )
        if img_w and img_h and scr_w and scr_h:
            out["coordinate_hint"] = (
                f"当前截图尺寸为 {img_w}x{img_h}，对应逻辑屏幕坐标 {scr_w}x{scr_h}。"
            )
        clean_q = (question or "").strip()
        if analyze_vision and vision_b64 and clean_q:
            vision = await self._analyze_screenshot(
                b64=vision_b64, mime=vision_mime, question=clean_q,
                img_w=img_w, img_h=img_h, scr_w=scr_w, scr_h=scr_h, os_name=conn.os_name,
            )
            out.update(vision)
        return out

    def latest_vision_frame(self, node_id: str | None) -> dict | None:
        if not node_id:
            return None
        conn = self.active.get(node_id)
        if conn is None or not conn.last_som_screenshot:
            return None
        return dict(conn.last_som_screenshot)

    def _get_vision_client(self) -> httpx.AsyncClient:
        if self._vision_client is None or self._vision_client.is_closed:
            self._vision_client = httpx.AsyncClient(timeout=25.0, trust_env=False)
        return self._vision_client

    async def _analyze_screenshot(
        self, *, b64: str, mime: str, question: str,
        img_w: int, img_h: int, scr_w: int, scr_h: int, os_name: str,
    ) -> dict:
        settings: Settings | None = self.settings_getter() if self.settings_getter is not None else None
        if settings is None:
            return {"vision_analysis": None, "vision_note": "未加载模型设置，已返回窗口信息与截图尺寸。"}
        configured_model = (getattr(settings, "desktop_vision_model", "") or "").strip()
        if _has_bailian_key(settings) and (
                settings.voice_mode == "realtime" or not settings.model.strip()
                or (_is_bailian_model_name(configured_model) and "aliyuncs.com" not in settings.base_url.lower())):
            base_url = _bailian_compatible_base_url(settings)
            api_key = settings.rt_api_key.get_secret_value().strip()
            model = configured_model or "qwen3-vl-plus"
        else:
            base_url = settings.base_url.rstrip("/")
            api_key = settings.api_key.get_secret_value().strip()
            model = configured_model or settings.model.strip()
        if not base_url or not api_key or not model:
            return {"vision_analysis": None, "vision_note": "未配置支持视觉的模型接口，已返回窗口信息与截图尺寸。"}
        is_qwen_vl = "qwen" in model.lower()
        coord_guide = (
            "如果需要给出按钮或输入框坐标，请严格使用你原生的 0..1000 归一化坐标系（左上角 [0, 0]，右下角 [1000, 1000]），"
            "以边界框 [x1, y1, x2, y2] 或中心点 [x, y] 格式标注，不要自行换算像素。"
            if is_qwen_vl
            else f"如果需要定位或点击某按钮/输入框，请给出它在图像坐标系（x: 0..{img_w}, y: 0..{img_h}）中的中心点坐标 [x, y]。"
        )
        prompt = (
            f"这是 {os_name} 电脑当前屏幕截图（图像尺寸 {img_w}x{img_h}，逻辑屏幕 {scr_w}x{scr_h}）。\n"
            f"用户/代理观察问题：{question}\n"
            f"请简明准确地描述画面中实际可见的窗口和元素（特别是前景窗口、搜索框、联系人或输入框文字），回答问题；{coord_guide}"
            "只报告截图里真实看到的文字与元素，看不到时明确说明。"
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
            client = self._get_vision_client()
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=min(float(settings.timeout_seconds), 25.0),
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
            content = str(((choice.get("message") or {}).get("content")) or "").strip()
            result: dict = {
                "vision_analysis": content,
                "vision_coord_space": "norm1000" if is_qwen_vl else "image",
            }
            suggested = _extract_vision_screen_coords(
                content, norm_1000=is_qwen_vl, img_w=img_w, img_h=img_h, scr_w=scr_w, scr_h=scr_h,
            )
            if suggested:
                result["suggested_screen_coords"] = suggested
            return result
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as error:
            err_msg = f"屏幕视觉解析请求失败：{type(error).__name__}"
            self.record_error("desktop_vision_error", err_msg, detail={"model": model})
            return {"vision_analysis": None, "vision_error": err_msg}

    def convert_coordinates(
        self, conn: DesktopNodeConnection, x: int | None, y: int | None, coord_space: str = "image",
    ) -> tuple[int | None, int | None]:
        if x is None or y is None or coord_space == "screen":
            return x, y
        shot = conn.last_screenshot or {}
        img_w = shot.get("image_width") or 0
        img_h = shot.get("image_height") or 0
        scr_w = shot.get("screen_width") or conn.screen.get("width") or 0
        scr_h = shot.get("screen_height") or conn.screen.get("height") or 0
        if coord_space == "norm1000" and scr_w > 0 and scr_h > 0:
            return round(x * scr_w / 1000.0), round(y * scr_h / 1000.0)
        if img_w > 0 and img_h > 0 and scr_w > 0 and scr_h > 0:
            return round(x * scr_w / img_w), round(y * scr_h / img_h)
        return x, y

    def resolve_ui_element(self, conn: DesktopNodeConnection, element_index: int) -> tuple[int, int, dict]:
        elements = conn.last_ui_elements or []
        if not elements:
            raise ProviderError(422, "ui_tree_empty", "尚未获取当前窗口控件树或应用未导出控件，请改用坐标或重新调用 desktop_inspect_screen。")
        if element_index < 0 or element_index >= len(elements):
            raise ProviderError(422, "invalid_element_index", f"控件索引 element_index={element_index} 超出当前范围（0..{len(elements) - 1}）。")
        elem = elements[element_index]
        return int(elem["x"]), int(elem["y"]), elem

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


def mount_desktop_admin_routes(app: FastAPI, get_hub, *, public: bool) -> None:
    async def require_local_desktop_admin(request: Request) -> None:
        loopback_client = request.client is not None and request.client.host in {"127.0.0.1", "::1"}
        loopback_host = request.url.hostname in {"localhost", "127.0.0.1", "::1"}
        # The public proxy authenticates itself, not the visitor using it.
        if public or not loopback_client or not loopback_host:
            raise HTTPException(status_code=403, detail={
                "code": "desktop_admin_local_only", "message": "桌面节点管理仅允许本机回环访问。",
            })

    router = APIRouter(prefix="/api/desktop", dependencies=[Depends(require_local_desktop_admin)])

    @router.get("")
    async def desktop_status():
        return get_hub().public()

    @router.post("/token/rotate")
    async def desktop_rotate_token():
        return await get_hub().rotate_token()

    @router.put("/default")
    async def desktop_set_default(body: dict):
        node_id = str(body.get("node_id") or "") if isinstance(body, dict) else ""
        return await get_hub().set_default_node(node_id)

    @router.delete("/nodes/{node_id}")
    async def desktop_delete_node(node_id: str):
        return await get_hub().delete_node(node_id)

    @router.post("/nodes/{node_id}/screenshot")
    async def desktop_refresh_screenshot(node_id: str):
        return await get_hub().inspect_screen(node_id=node_id, question="", analyze_vision=False, include_som=False)

    @router.get("/nodes/{node_id}/screenshot")
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

    app.include_router(router)


def supports_native_vision(model_name: str) -> bool:
    """Models supporting multimodal image_url input alongside OpenAI tool calls."""
    lowered = (model_name or "").strip().lower()
    if not lowered:
        return False
    return lowered.startswith((
        "qwen3.5",
        "qwen3.8",
        "qwen4",
        "qwen3-vl",
        "qwen2.5-vl",
        "qwen-vl",
        "qvq",
        "deepseek-v4",
        "gpt-4o",
        "gpt-4.1",
        "gpt-5",
        "o1",
        "o3",
        "o4",
        "gemini",
        "claude-3",
        "claude-4",
        "kimi-latest",
    ))


def _is_bailian_model_name(model_name: str) -> bool:
    return (model_name or "").strip().lower().startswith(("qwen", "qvq", "deepseek-v4"))


def _has_bailian_key(settings: Settings) -> bool:
    return (
        getattr(settings, "rt_provider", "") == "bailian"
        and bool(settings.rt_api_key.get_secret_value().strip())
    )


def _bailian_compatible_base_url(settings: Settings) -> str:
    ws_id = (getattr(settings, "rt_workspace", "") or "").strip()
    return (
        f"https://{ws_id}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
        if ws_id else "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )


def _bailian_planner_copy(config: Settings, model_name: str) -> Settings:
    return config.model_copy(update={
        "voice_mode": "pipeline",
        "provider": "bailian",
        "base_url": _bailian_compatible_base_url(config),
        "api_key": config.rt_api_key,
        "model": model_name,
        "input_price_per_million": None,
        "output_price_per_million": None,
    })


def build_desktop_planner_config(config: Settings) -> Settings | None:
    """Returns OpenAI-compatible multimodal/text-model Settings for desktop control, or None to keep default."""
    planner = (getattr(config, "desktop_planner_model", "") or "").strip()
    has_text = bool(config.model.strip() and config.api_key.get_secret_value().strip() and config.base_url.strip())
    if _has_bailian_key(config):
        if planner and _is_bailian_model_name(planner) and (
                "aliyuncs.com" not in config.base_url.lower()
                or not has_text
                or config.voice_mode == "realtime"):
            return _bailian_planner_copy(config, planner)
        if not planner and config.voice_mode == "realtime" and (not has_text or not supports_native_vision(config.model)):
            return _bailian_planner_copy(config, "qwen3.5-plus")
    if config.voice_mode != "realtime":
        if not planner or planner == config.model.strip():
            if not has_text and _has_bailian_key(config):
                return _bailian_planner_copy(config, planner or "qwen3.5-plus")
            return None
        if config.api_key.get_secret_value().strip() and config.base_url.strip():
            return config.model_copy(update={"model": planner})
        return _bailian_planner_copy(config, planner) if _has_bailian_key(config) else None
    if has_text:
        return config.model_copy(update={
            "voice_mode": "pipeline",
            "model": planner or config.model.strip(),
            "input_price_per_million": None,
            "output_price_per_million": None,
        })
    return None


def desktop_planner_uses_direct_vision(config: Settings | None) -> bool:
    """True when desktop turns run directly on a native multimodal vision+tool model."""
    if config is None:
        return False
    planner_cfg = build_desktop_planner_config(config)
    effective = planner_cfg if planner_cfg is not None else config
    if getattr(effective, "voice_mode", "pipeline") == "realtime":
        return False
    return supports_native_vision(getattr(effective, "model", ""))
