"""Agent tools wrapping DesktopHub for cross-platform Windows & macOS control and Computer Use."""
from __future__ import annotations

from .desktop import DesktopHub, is_sensitive_path
from .llm import ProviderError
from .tools import ToolSpec

DESKTOP_CAPABILITY_SPEC = ToolSpec(
    "desktop_control",
    "连接并控制个人电脑（兼容 Windows 与 macOS）：支持看屏幕（Computer Use）、读写剪贴板、浏览与读取非敏感文件、打开应用/链接、鼠标键盘操作及确认后执行终端命令。",
    {"type": "object", "properties": {}, "additionalProperties": False},
    permission="read",
)


def _node_param() -> dict:
    return {
        "type": "string",
        "maxLength": 64,
        "description": "可选。目标电脑节点 ID、名称或系统（如 mac / windows）；省略时使用默认在线电脑。",
    }


DESKTOP_LIST_NODES_SPEC = ToolSpec(
    "desktop_list_nodes",
    "查看当前已连接或历史配对的 Windows / macOS 个人电脑节点、系统平台与屏幕分辨率。",
    {"type": "object", "properties": {}, "additionalProperties": False},
    permission="read",
)

DESKTOP_INSPECT_SCREEN_SPEC = ToolSpec(
    "desktop_inspect_screen",
    "截取当前电脑屏幕并获取前景窗口信息与分辨率；传入 question 时同时用视觉模型观察画面、回答问题或定位界面元素坐标。",
    {
        "type": "object",
        "properties": {
            "node_id": _node_param(),
            "question": {
                "type": "string",
                "maxLength": 500,
                "description": "可选。你想看屏幕上什么内容、要读什么文字，或要寻找哪个按钮/输入框的位置。",
            },
        },
        "additionalProperties": False,
    },
    permission="read",
)

DESKTOP_CLIPBOARD_GET_SPEC = ToolSpec(
    "desktop_clipboard",
    "读取目标 Windows 或 macOS 电脑当前剪贴板中的文本内容。",
    {
        "type": "object",
        "properties": {"node_id": _node_param()},
        "additionalProperties": False,
    },
    permission="read",
)

DESKTOP_LIST_DIR_SPEC = ToolSpec(
    "desktop_list_dir",
    "列出目标电脑指定目录（如桌面 ~/Desktop、下载 ~/Downloads 或指定路径）的文件与子文件夹名称及大小。",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string", "maxLength": 500, "description": "目录路径；可用 ~ 表示用户主目录，省略则列出用户主目录。"},
            "node_id": _node_param(),
            "max_entries": {"type": "integer", "minimum": 1, "maximum": 120, "description": "最多返回条目数，默认 60。"},
        },
        "additionalProperties": False,
    },
    permission="read",
)

DESKTOP_READ_FILE_SPEC = ToolSpec(
    "desktop_read_file",
    "读取目标电脑上纯文本文件（代码、日志、Markdown、配置等）的片段。自动拒绝读取 .env、SSH 密钥等敏感凭证文件。",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1, "maxLength": 500, "description": "要读取的文件路径，支持 ~。"},
            "node_id": _node_param(),
            "offset": {"type": "integer", "minimum": 0, "description": "可选起始字符偏移，默认 0。"},
            "limit": {"type": "integer", "minimum": 100, "maximum": 12000, "description": "最多读取字符数，默认 6000。"},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
    permission="read",
)

DESKTOP_CLIPBOARD_SET_SPEC = ToolSpec(
    "desktop_set_clipboard",
    "写入文本到目标电脑的系统剪贴板（覆盖原有剪贴板，需用户确认）。",
    {
        "type": "object",
        "properties": {
            "text": {"type": "string", "minLength": 1, "maxLength": 10000, "description": "要写入剪贴板的文本。"},
            "node_id": _node_param(),
        },
        "required": ["text"],
        "additionalProperties": False,
    },
    permission="write",
)

DESKTOP_OPEN_SPEC = ToolSpec(
    "desktop_open",
    "在目标 Windows / macOS 电脑上打开应用程序、文件、目录或网址（需用户确认）。",
    {
        "type": "object",
        "properties": {
            "target": {"type": "string", "minLength": 1, "maxLength": 500, "description": "应用名（如 Safari / 记事本 / Code）、文件路径或 https:// 网址。"},
            "kind": {"type": "string", "enum": ["auto", "app", "url", "path"], "description": "目标类型，默认 auto。"},
            "node_id": _node_param(),
        },
        "required": ["target"],
        "additionalProperties": False,
    },
    permission="write",
)

DESKTOP_GUI_ACTION_SPEC = ToolSpec(
    "desktop_gui_action",
    "在目标电脑上执行 Computer Use 图形界面操控：鼠标移动/点击/双击/右键/滚轮，或输入文字、按下组合快捷键（需用户确认）。建议点击前先调用 desktop_inspect_screen 获取画面尺寸与坐标。",
    {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["click", "double_click", "right_click", "move", "type_text", "hotkey", "scroll"],
                "description": "要执行的 GUI 动作类型。",
            },
            "x": {"type": "integer", "minimum": 0, "maximum": 16000, "description": "点击/移动/滚轮的目标横坐标。"},
            "y": {"type": "integer", "minimum": 0, "maximum": 16000, "description": "点击/移动/滚轮的目标纵坐标。"},
            "coord_space": {
                "type": "string",
                "enum": ["image", "screen", "norm1000"],
                "description": "坐标来源：screen 直接用 inspect_screen 返回的 suggested_screen_coords（最推荐）；norm1000 为视觉模型 0-1000 归一化坐标；image 为截图图像像素坐标（默认）。",
            },
            "text": {"type": "string", "minLength": 1, "maxLength": 2000, "description": "当 action=type_text 时要输入的文本。"},
            "keys": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 24},
                "minItems": 1,
                "maxItems": 5,
                "description": "当 action=hotkey 时的按键组合，如 [\"cmd\", \"c\"] 或 [\"ctrl\", \"shift\", \"esc\"]。",
            },
            "scroll_y": {"type": "integer", "minimum": -50, "maximum": 50, "description": "当 action=scroll 时的垂直滚动量（正数向上、负数向下）。"},
            "node_id": _node_param(),
        },
        "required": ["action"],
        "additionalProperties": False,
    },
    permission="write",
)

DESKTOP_RUN_COMMAND_SPEC = ToolSpec(
    "desktop_run_command",
    "在目标 Windows（PowerShell）或 macOS（zsh/bash）电脑上执行终端命令并返回标准输出（高风险写操作，必须经过用户确认）。",
    {
        "type": "object",
        "properties": {
            "command": {"type": "string", "minLength": 1, "maxLength": 2000, "description": "要执行的单条终端命令。"},
            "cwd": {"type": "string", "maxLength": 500, "description": "可选工作目录，默认用户主目录。"},
            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 30, "description": "超时秒数，默认 10 秒，上限 30 秒。"},
            "node_id": _node_param(),
        },
        "required": ["command"],
        "additionalProperties": False,
    },
    permission="write",
)


class _DesktopBaseTool:
    def __init__(self, hub: DesktopHub):
        self.hub = hub


class DesktopListNodesTool(_DesktopBaseTool):
    spec = DESKTOP_LIST_NODES_SPEC

    async def run(self, arguments, *, trace=None):
        return {
            "default_node_id": self.hub.default_node_id,
            "online_count": len(self.hub.active),
            "nodes": self.hub.list_nodes(),
        }


class DesktopInspectScreenTool(_DesktopBaseTool):
    spec = DESKTOP_INSPECT_SCREEN_SPEC

    async def run(self, arguments, *, trace=None):
        return await self.hub.inspect_screen(
            node_id=arguments.get("node_id"),
            question=arguments.get("question", ""),
            analyze_vision=bool((arguments.get("question") or "").strip()),
        )


class DesktopClipboardGetTool(_DesktopBaseTool):
    spec = DESKTOP_CLIPBOARD_GET_SPEC

    async def run(self, arguments, *, trace=None):
        conn = self.hub.resolve_node(arguments.get("node_id"))
        res = await conn.rpc("clipboard_get", {}, timeout=10.0)
        return {"node_id": conn.node_id, "node_name": conn.name, "os": conn.os_name, **res}


class DesktopListDirTool(_DesktopBaseTool):
    spec = DESKTOP_LIST_DIR_SPEC

    async def run(self, arguments, *, trace=None):
        path = str(arguments.get("path") or "~").strip() or "~"
        if is_sensitive_path(path):
            raise ProviderError(403, "access_denied", "为保护电脑凭证与私钥安全，禁止访问该目录。")
        conn = self.hub.resolve_node(arguments.get("node_id"))
        res = await conn.rpc(
            "list_dir",
            {"path": path, "max_entries": int(arguments.get("max_entries") or 60)},
            timeout=15.0,
        )
        return {"node_id": conn.node_id, "node_name": conn.name, "os": conn.os_name, **res}


class DesktopReadFileTool(_DesktopBaseTool):
    spec = DESKTOP_READ_FILE_SPEC

    async def run(self, arguments, *, trace=None):
        path = str(arguments["path"]).strip()
        if is_sensitive_path(path):
            raise ProviderError(403, "access_denied", "为保护 .env、私钥与凭证安全，禁止读取该文件。")
        conn = self.hub.resolve_node(arguments.get("node_id"))
        res = await conn.rpc(
            "read_file",
            {
                "path": path,
                "offset": int(arguments.get("offset") or 0),
                "limit": int(arguments.get("limit") or 6000),
            },
            timeout=15.0,
        )
        return {"node_id": conn.node_id, "node_name": conn.name, "os": conn.os_name, **res}


class DesktopClipboardSetTool(_DesktopBaseTool):
    spec = DESKTOP_CLIPBOARD_SET_SPEC

    async def run(self, arguments, *, trace=None):
        conn = self.hub.resolve_node(arguments.get("node_id"))
        res = await conn.rpc("clipboard_set", {"text": arguments["text"]}, timeout=10.0)
        return {"node_id": conn.node_id, "node_name": conn.name, "os": conn.os_name, **res}


class DesktopOpenTool(_DesktopBaseTool):
    spec = DESKTOP_OPEN_SPEC

    async def run(self, arguments, *, trace=None):
        target = str(arguments["target"]).strip()
        if is_sensitive_path(target):
            raise ProviderError(403, "access_denied", "禁止直接打开敏感凭证文件。")
        conn = self.hub.resolve_node(arguments.get("node_id"))
        res = await conn.rpc(
            "open",
            {"target": target, "kind": arguments.get("kind") or "auto"},
            timeout=15.0,
        )
        return {
            "node_id": conn.node_id,
            "node_name": conn.name,
            "os": conn.os_name,
            **res,
            "next_step_note": "应用/目标已触发启动，请调用 desktop_inspect_screen 确认其窗口已真实前置并定位输入框或按钮，不要只打开应用就停下。",
        }


class DesktopGuiActionTool(_DesktopBaseTool):
    spec = DESKTOP_GUI_ACTION_SPEC

    async def run(self, arguments, *, trace=None):
        action = arguments["action"]
        x = arguments.get("x")
        y = arguments.get("y")
        if action in {"click", "double_click", "right_click", "move"} and (x is None or y is None):
            raise ProviderError(422, "tool_arguments", f"GUI 动作 {action} 必须同时提供 x 和 y 坐标。")
        if action == "type_text" and not arguments.get("text"):
            raise ProviderError(422, "tool_arguments", "type_text 必须提供 text 参数。")
        if action == "hotkey" and not arguments.get("keys"):
            raise ProviderError(422, "tool_arguments", "hotkey 必须提供 keys 按键数组。")
        conn = self.hub.resolve_node(arguments.get("node_id"))
        coord_space = arguments.get("coord_space") or "image"
        scr_x, scr_y = self.hub.convert_coordinates(conn, x, y, coord_space=coord_space)
        payload = {"action": action}
        if scr_x is not None and scr_y is not None:
            payload["x"] = scr_x
            payload["y"] = scr_y
        if "text" in arguments:
            payload["text"] = arguments["text"]
        if "keys" in arguments:
            payload["keys"] = arguments["keys"]
        if "scroll_y" in arguments:
            payload["scroll_y"] = int(arguments["scroll_y"])
        res = await conn.rpc("gui_action", payload, timeout=15.0)
        return {
            "node_id": conn.node_id,
            "node_name": conn.name,
            "os": conn.os_name,
            "screen_coords": {"x": scr_x, "y": scr_y} if scr_x is not None and scr_y is not None else None,
            **res,
            "verified_on_screen": False,
            "next_step_note": (
                "底层键鼠信号已发送，但系统无法保证焦点正确或文本已真的上屏。"
                "在向用户说‘已找到/已输入/已完成’之前，必须先调用 desktop_inspect_screen 截图核实画面是否真的达到目标；看不到就继续补救或如实说明。"
            ),
        }


class DesktopRunCommandTool(_DesktopBaseTool):
    spec = DESKTOP_RUN_COMMAND_SPEC

    async def run(self, arguments, *, trace=None):
        command = str(arguments["command"]).strip()
        cwd = str(arguments.get("cwd") or "").strip()
        if cwd and is_sensitive_path(cwd):
            raise ProviderError(403, "access_denied", "禁止在敏感目录中执行命令。")
        conn = self.hub.resolve_node(arguments.get("node_id"))
        timeout = min(30, max(1, int(arguments.get("timeout_seconds") or 10)))
        res = await conn.rpc(
            "run_command",
            {"command": command, "cwd": cwd or None, "timeout_seconds": timeout},
            timeout=float(timeout + 5),
        )
        return {"node_id": conn.node_id, "node_name": conn.name, "os": conn.os_name, **res}


DESKTOP_SPECS = (
    DESKTOP_CAPABILITY_SPEC,
    DESKTOP_LIST_NODES_SPEC,
    DESKTOP_INSPECT_SCREEN_SPEC,
    DESKTOP_CLIPBOARD_GET_SPEC,
    DESKTOP_LIST_DIR_SPEC,
    DESKTOP_READ_FILE_SPEC,
    DESKTOP_CLIPBOARD_SET_SPEC,
    DESKTOP_OPEN_SPEC,
    DESKTOP_GUI_ACTION_SPEC,
    DESKTOP_RUN_COMMAND_SPEC,
)
DESKTOP_BUILTIN_NAMES = {spec.name for spec in DESKTOP_SPECS}


def build_desktop_tools(hub: DesktopHub | None):
    if hub is None:
        return []
    return [
        DesktopListNodesTool(hub),
        DesktopInspectScreenTool(hub),
        DesktopClipboardGetTool(hub),
        DesktopListDirTool(hub),
        DesktopReadFileTool(hub),
        DesktopClipboardSetTool(hub),
        DesktopOpenTool(hub),
        DesktopGuiActionTool(hub),
        DesktopRunCommandTool(hub),
    ]
