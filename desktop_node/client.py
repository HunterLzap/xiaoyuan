"""WebSocket client connecting a personal Windows or macOS computer to Xiaodan Agent."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import platform
import re
import socket
import sys

from .platform_base import DesktopAdapter, DesktopRpcError

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
        return adapter.capture_screenshot(
            max_width=int(params.get("max_width") or 1280),
            max_height=int(params.get("max_height") or 800),
            quality=int(params.get("quality") or 80),
        )
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


async def _handle_request(
    ws,
    adapter: DesktopAdapter,
    msg: dict,
    *,
    allow_shell: bool,
    allow_gui: bool,
) -> None:
    req_id = msg.get("request_id")
    action = str(msg.get("action") or "")
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    try:
        result = await asyncio.to_thread(
            execute_rpc, adapter, action, params,
            allow_shell=allow_shell, allow_gui=allow_gui,
        )
        await ws.send(json.dumps({"type": "rpc_response", "request_id": req_id, "ok": True, "result": result}, ensure_ascii=False))
    except DesktopRpcError as error:
        await ws.send(json.dumps({
            "type": "rpc_response",
            "request_id": req_id,
            "ok": False,
            "error": {"code": error.code, "message": error.message},
        }, ensure_ascii=False))
    except Exception as error:
        await ws.send(json.dumps({
            "type": "rpc_response",
            "request_id": req_id,
            "ok": False,
            "error": {"code": "desktop_internal_error", "message": f"本地执行异常：{type(error).__name__}"},
        }, ensure_ascii=False))


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
) -> None:
    try:
        import websockets
    except ImportError as error:
        raise RuntimeError("缺少依赖 websockets：请运行 pip install -r desktop_node/requirements-desktop.txt") from error

    adapter = build_adapter()
    hostname = socket.gethostname()
    resolved_id = (node_id or default_node_id(adapter.os_name, hostname)).strip()
    resolved_name = (name or f"{hostname} ({'Mac' if adapter.os_name == 'macos' else 'Windows'})").strip()
    headers = {"Authorization": f"Bearer {token}"}
    backoff = 2.0
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
                            ws, adapter, msg, allow_shell=allow_shell, allow_gui=allow_gui,
                        ))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("Desktop connection ended (%s: %s), reconnecting in %.0fs...",
                           type(error).__name__, error, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.5, 30.0)
        finally:
            if hb_task is not None:
                hb_task.cancel()
                try:
                    await hb_task
                except (asyncio.CancelledError, Exception):
                    pass


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Xiaodan Personal Computer Node (Windows & macOS)")
    parser.add_argument("--server", default=os.environ.get("DESKTOP_SERVER_URL", ""), help="WebSocket URL, e.g. wss://host/assistant/desktop/v1/")
    parser.add_argument("--token", default=os.environ.get("DESKTOP_GATEWAY_TOKEN", ""), help="Desktop gateway bearer token from 终端节点 page")
    parser.add_argument("--node-id", default=os.environ.get("DESKTOP_NODE_ID", ""), help="Optional custom node id")
    parser.add_argument("--name", default=os.environ.get("DESKTOP_NODE_NAME", ""), help="Optional display name")
    parser.add_argument("--no-shell", action="store_true", help="Disable run_command RPC on this machine")
    parser.add_argument("--no-gui", action="store_true", help="Disable mouse/keyboard gui_action RPC on this machine")
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
        ))
    except KeyboardInterrupt:
        return 0
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
