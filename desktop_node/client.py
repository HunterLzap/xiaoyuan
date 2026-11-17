"""WebSocket client connecting a personal Windows or macOS computer to Xiaoyuan Agent."""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import platform
import re
import socket
import sys
import time

from .overlay import ScreenOverlayHUD
from .platform_base import DesktopAdapter, DesktopRpcError
from .som import annotate_screenshot_som

logger = logging.getLogger("desktop_node")


def build_adapter() -> DesktopAdapter:
    sys_name = platform.system().lower()
    if sys_name == "darwin":
        from .platform_macos import MacOSDesktopAdapter
        return MacOSDesktopAdapter()
    if sys_name == "windows":
        from .platform_windows import WindowsDesktopAdapter
        return WindowsDesktopAdapter()
    raise RuntimeError(f"当前系统 {platform.system()} 暂不受支持；请使用 Windows 或 macOS。")


def default_node_id(os_name: str, host: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", host or "desktop").strip("-").lower() or "desktop"
    return f"{os_name}-{slug}"[:64]


def execute_rpc(
    adapter: DesktopAdapter,
    action: str,
    params: dict,
    *,
    allow_shell: bool = True,
    allow_gui: bool = True,
) -> dict:
    if action == "screenshot":
        shot = adapter.capture_screenshot(
            max_width=int(params.get("max_width") or 1280),
            max_height=int(params.get("max_height") or 800),
            quality=int(params.get("quality") or 80),
        )
        if params.get("som", True) and shot.get("image_base64") and shot.get("ui_elements"):
            try:
                raw_bytes = base64.b64decode(shot["image_base64"])
                som_bytes, annotated = annotate_screenshot_som(
                    raw_bytes,
                    shot["ui_elements"],
                    image_width=int(shot.get("image_width") or shot.get("width") or 0),
                    image_height=int(shot.get("image_height") or shot.get("height") or 0),
                    screen_width=int(shot.get("screen_width") or 0),
                    screen_height=int(shot.get("screen_height") or 0),
                )
                if annotated:
                    shot["som_image_base64"] = base64.b64encode(som_bytes).decode("ascii")
                    shot["som_mime_type"] = "image/jpeg"
                    shot["som_annotated"] = True
            except Exception as err:
                logger.debug("som_annotate_skipped err=%s", type(err).__name__)
        return shot
    if action == "clipboard_get":
        return adapter.clipboard_get()
    if action == "clipboard_set":
        return adapter.clipboard_set(str(params.get("text") or ""))
    if action == "list_dir":
        return adapter.list_dir(str(params.get("path") or "~"), max_entries=int(params.get("max_entries") or 60))
    if action == "read_file":
        return adapter.read_file(
            str(params.get("path") or ""),
            offset=int(params.get("offset") or 0),
            limit=int(params.get("limit") or 6000),
        )
    if action == "open":
        return adapter.open_target(str(params.get("target") or ""), kind=str(params.get("kind") or "auto"))
    if action == "gui_action":
        if not allow_gui:
            raise DesktopRpcError("gui_disabled", "该桌面节点已启动 --no-gui，禁止鼠标与键盘自动化。")
        return adapter.gui_action(
            str(params.get("action") or ""),
            x=params.get("x"),
            y=params.get("y"),
            text=params.get("text"),
            keys=params.get("keys"),
            scroll_y=int(params.get("scroll_y") or 0),
            submit=bool(params.get("submit")),
        )
    if action == "run_command":
        if not allow_shell:
            raise DesktopRpcError("shell_disabled", "该桌面节点已启动 --no-shell，禁止执行终端命令。")
        return adapter.run_command(
            str(params.get("command") or ""),
            cwd=params.get("cwd"),
            timeout_seconds=int(params.get("timeout_seconds") or 10),
        )
    raise DesktopRpcError("unsupported_action", f"未知操作：{action}")


def _describe_rpc_for_hud(action: str, params: dict) -> tuple[str, str]:
    if action == "screenshot":
        return ("观察电脑屏幕", "")
    if action == "open":
        target = str(params.get("target") or "").strip()
        return ("打开应用或链接", target[:32])
    if action == "gui_action":
        sub = str(params.get("action") or "").strip()
        if sub in {"click", "double_click", "right_click", "move"}:
            return ("鼠标点击操作", f"{sub} ({params.get('x')}, {params.get('y')})")
        if sub == "type_text":
            count = len(str(params.get("text") or ""))
            return ("输入文字", f"{count} 字" if count else "")
        if sub == "paste_text":
            count = len(str(params.get("text") or ""))
            return ("粘贴文字", f"{count} 字" if count else "")
        if sub == "click_and_type":
            count = len(str(params.get("text") or ""))
            return ("点击并输入", f"{count} 字" if count else "")
        if sub == "hotkey":
            keys = params.get("keys")
            combo = "+".join(str(k) for k in keys[:4]) if isinstance(keys, list) else ""
            return ("触发快捷键", combo)
        if sub == "scroll":
            return ("滚动页面", "")
        return ("界面操控", sub)
    if action == "clipboard_get":
        return ("读取剪贴板", "")
    if action == "clipboard_set":
        return ("写入剪贴板", f"{len(str(params.get('text') or ''))} 字")
    if action == "list_dir":
        return ("浏览目录", "")
    if action == "read_file":
        return ("读取文件内容", "")
    if action == "run_command":
        return ("执行终端命令", "")
    return ("处理操作", action)


async def _handle_request(
    ws,
    adapter: DesktopAdapter,
    msg: dict,
    *,
    allow_shell: bool,
    allow_gui: bool,
    hud: ScreenOverlayHUD | None = None,
) -> None:
    req_id = msg.get("request_id")
    action = str(msg.get("action") or "")
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    label, detail = _describe_rpc_for_hud(action, params)
    logger.info("[RPC] %s %s", action, detail or "-")
    if hud is not None:
        hud.show(label, detail)
    started = time.perf_counter()
    try:
        result = await asyncio.to_thread(
            execute_rpc, adapter, action, params,
            allow_shell=allow_shell, allow_gui=allow_gui,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info("[RPC] %s -> ok (%dms)", action, elapsed_ms)
        await ws.send(json.dumps({"type": "rpc_response", "request_id": req_id, "ok": True, "result": result}, ensure_ascii=False))
    except DesktopRpcError as error:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.warning("[RPC] %s -> error:%s (%dms): %s", action, error.code, elapsed_ms, error.message)
        await ws.send(json.dumps({
            "type": "rpc_response",
            "request_id": req_id,
            "ok": False,
            "error": {"code": error.code, "message": error.message},
        }, ensure_ascii=False))
    except Exception as error:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.warning("[RPC] %s -> exception:%s (%dms)", action, type(error).__name__, elapsed_ms)
        await ws.send(json.dumps({
            "type": "rpc_response",
            "request_id": req_id,
            "ok": False,
            "error": {"code": "desktop_internal_error", "message": f"本地执行异常：{type(error).__name__}"},
        }, ensure_ascii=False))
    finally:
        if hud is not None:
            hud.schedule_hide(4.5)


async def _heartbeat_loop(ws) -> None:
    while True:
        await asyncio.sleep(30.0)
        await ws.send(json.dumps({"type": "ping"}))


async def run_node(
    *,
    server: str,
    token: str,
    node_id: str | None = None,
    name: str | None = None,
    allow_shell: bool = True,
    allow_gui: bool = True,
    use_system_proxy: bool = False,
    show_hud: bool = True,
) -> None:
    try:
        import websockets
    except ImportError as error:
        raise RuntimeError("缺少依赖 websockets：请运行 pip install -r desktop_node/requirements-desktop.txt") from error

    adapter = build_adapter()
    check_perms = getattr(adapter, "check_permissions", None)
    if callable(check_perms):
        perms = check_perms()
        if isinstance(perms, dict):
            missing = []
            if perms.get("screen_recording") is False:
                missing.append("录屏与系统录音")
            if perms.get("accessibility") is False:
                missing.append("辅助功能")
            if missing:
                logger.warning(
                    "macOS 缺少权限 [%s]！请前往 系统设置 → 隐私与安全性 授权当前终端，否则无法看清应用窗口或点击输入。",
                    "、".join(missing),
                )
    hud = ScreenOverlayHUD(enabled=show_hud)
    hostname = socket.gethostname()
    resolved_id = (node_id or default_node_id(adapter.os_name, hostname)).strip()
    resolved_name = (name or f"{hostname} ({'Mac' if adapter.os_name == 'macos' else 'Windows'})").strip()
    headers = {"Authorization": f"Bearer {token}"}
    backoff = 2.0
    try:
        while True:
            hb_task: asyncio.Task | None = None
            try:
                logger.info("Connecting desktop node [%s / %s] -> %s", resolved_id, adapter.os_name, server)
                async with websockets.connect(
                    server,
                    additional_headers=headers,
                    proxy=True if use_system_proxy else None,
                    max_size=8 * 1024 * 1024,
                    ping_interval=20,
                    ping_timeout=20,
                ) as ws:
                    backoff = 2.0
                    screen = await asyncio.to_thread(adapter.screen_size)
                    await ws.send(json.dumps({
                        "type": "hello",
                        "node_id": resolved_id,
                        "name": resolved_name,
                        "os": adapter.os_name,
                        "hostname": hostname,
                        "arch": platform.machine(),
                        "screen": screen,
                        "capabilities": adapter.capabilities(allow_shell=allow_shell, allow_gui=allow_gui),
                    }, ensure_ascii=False))
                    hb_task = asyncio.create_task(_heartbeat_loop(ws))
                    while True:
                        raw = await ws.recv()
                        msg = json.loads(raw)
                        if not isinstance(msg, dict):
                            continue
                        kind = msg.get("type")
                        if kind == "welcome":
                            logger.info("Connected! Node ready: %s (%s)", resolved_name, screen)
                        elif kind == "rpc_request":
                            asyncio.create_task(_handle_request(
                                ws, adapter, msg, allow_shell=allow_shell, allow_gui=allow_gui, hud=hud,
                            ))
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning("Desktop connection ended (%s: %s), reconnecting in %.0fs...",
                               type(error).__name__, error, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, 30.0)
            finally:
                hud.hide()
                if hb_task is not None:
                    hb_task.cancel()
                    try:
                        await hb_task
                    except (asyncio.CancelledError, Exception):
                        pass
    finally:
        hud.close()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Xiaoyuan Personal Computer Node (Windows & macOS)")
    parser.add_argument("--server", default=os.environ.get("DESKTOP_SERVER_URL", ""), help="WebSocket URL, e.g. wss://host/assistant/desktop/v1/")
    parser.add_argument("--token", default=os.environ.get("DESKTOP_GATEWAY_TOKEN", ""), help="Desktop gateway bearer token from 终端节点 page")
    parser.add_argument("--node-id", default=os.environ.get("DESKTOP_NODE_ID", ""), help="Optional custom node id")
    parser.add_argument("--name", default=os.environ.get("DESKTOP_NODE_NAME", ""), help="Optional display name")
    parser.add_argument("--no-shell", action="store_true", help="Disable run_command RPC on this machine")
    parser.add_argument("--no-gui", action="store_true", help="Disable mouse/keyboard gui_action RPC on this machine")
    parser.add_argument("--no-hud", action="store_true", help="Disable screen border and top status pill overlay during operations")
    parser.add_argument("--use-system-proxy", action="store_true", help="Follow OS/env SOCKS/HTTP proxy instead of direct connection")
    args = parser.parse_args(argv)
    if not args.server or not args.token:
        parser.error("必须通过 --server 和 --token（或环境变量 DESKTOP_SERVER_URL / DESKTOP_GATEWAY_TOKEN）提供服务地址与令牌。")
    try:
        asyncio.run(run_node(
            server=args.server,
            token=args.token,
            node_id=args.node_id or None,
            name=args.name or None,
            allow_shell=not args.no_shell,
            allow_gui=not args.no_gui,
            use_system_proxy=args.use_system_proxy,
            show_hud=not args.no_hud,
        ))
    except KeyboardInterrupt:
        return 0
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
