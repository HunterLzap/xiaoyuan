"""Windows desktop control & screenshot adapter using built-in Win32 ctypes and PowerShell/.NET."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
from typing import Any
from urllib.parse import urlsplit

from .platform_base import DesktopAdapter, DesktopRpcError, resolve_safe_path

_VK_MAP: dict[str, int] = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
    "shift": 0x10, "ctrl": 0x11, "control": 0x11, "alt": 0x12, "option": 0x12,
    "esc": 0x1B, "escape": 0x1B, "space": 0x20, "pageup": 0x21, "pagedown": 0x22,
    "end": 0x23, "home": 0x24, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "delete": 0x2E, "win": 0x5B, "super": 0x5B, "cmd": 0x5B, "command": 0x5B,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC, ";": 0xBA, "'": 0xDE,
    ",": 0xBC, ".": 0xBE, "/": 0xBF, "`": 0xC0,
}
for _c in "abcdefghijklmnopqrstuvwxyz0123456789":
    _VK_MAP[_c] = ord(_c.upper())

_MODIFIERS = {"ctrl", "control", "shift", "alt", "option", "win", "super", "cmd", "command"}
_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_RIGHTDOWN = 0x0008
_MOUSEEVENTF_RIGHTUP = 0x0010
_MOUSEEVENTF_WHEEL = 0x0800


def _ensure_dpi_aware() -> None:
    try:
        user32 = ctypes.windll.user32
        if hasattr(user32, "SetProcessDpiAwarenessContext"):
            user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        elif hasattr(user32, "SetProcessDPIAware"):
            user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUT_UNION)]


class WindowsDesktopAdapter(DesktopAdapter):
    os_name = "windows"

    def __init__(self):
        _ensure_dpi_aware()

    def screen_size(self) -> dict[str, int]:
        _ensure_dpi_aware()
        user32 = ctypes.windll.user32
        return {"width": int(user32.GetSystemMetrics(0)), "height": int(user32.GetSystemMetrics(1))}

    def active_window(self) -> dict[str, str]:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        title = ""
        if hwnd:
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
        return {"app": "", "title": title}

    def capture_screenshot(self, max_width: int = 1280, max_height: int = 800, quality: int = 80) -> dict[str, Any]:
        screen = self.screen_size()
        active = self.active_window()
        max_w = max(320, min(int(max_width), 1920))
        max_h = max(240, min(int(max_height), 1200))
        q = max(40, min(int(quality), 95))
        ps = (
            "Add-Type -AssemblyName System.Drawing;"
            "$w = " + str(screen["width"]) + "; $h = " + str(screen["height"]) + ";"
            "$bmp = New-Object System.Drawing.Bitmap($w, $h);"
            "$g = [System.Drawing.Graphics]::FromImage($bmp);"
            "$g.CopyFromScreen(0, 0, 0, 0, $bmp.Size);"
            "$g.Dispose();"
            "$tw = $w; $th = $h;"
            "if ($w -gt " + str(max_w) + " -or $h -gt " + str(max_h) + ") {"
            "  $rx = " + str(max_w) + " / [double]$w; $ry = " + str(max_h) + " / [double]$h;"
            "  $r = [Math]::Min($rx, $ry);"
            "  $tw = [Math]::Max(1, [int][Math]::Round($w * $r));"
            "  $th = [Math]::Max(1, [int][Math]::Round($h * $r));"
            "  $scaled = New-Object System.Drawing.Bitmap($tw, $th);"
            "  $sg = [System.Drawing.Graphics]::FromImage($scaled);"
            "  $sg.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic;"
            "  $sg.DrawImage($bmp, 0, 0, $tw, $th);"
            "  $sg.Dispose(); $bmp.Dispose(); $bmp = $scaled;"
            "}"
            "$ms = New-Object System.IO.MemoryStream;"
            "$codec = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object { $_.MimeType -eq 'image/jpeg' } | Select-Object -First 1;"
            "$ep = New-Object System.Drawing.Imaging.EncoderParameters(1);"
            "$ep.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter([System.Drawing.Imaging.Encoder]::Quality, [long]" + str(q) + ");"
            "$bmp.Save($ms, $codec, $ep);"
            "$bmp.Dispose();"
            "$out = @{ width = $tw; height = $th; b64 = [Convert]::ToBase64String($ms.ToArray()) };"
            "$ms.Dispose();"
            "$out | ConvertTo-Json -Compress"
        )
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            raise DesktopRpcError("screen_capture_failed", proc.stderr.strip() or "Windows 截屏失败。")
        data = json.loads(proc.stdout.strip())
        return {
            "image_base64": data["b64"],
            "mime_type": "image/jpeg",
            "image_width": int(data["width"]),
            "image_height": int(data["height"]),
            "screen_width": screen["width"],
            "screen_height": screen["height"],
            "active_window": active,
        }

    def clipboard_get(self) -> dict[str, str]:
        ps = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; Get-Clipboard -Raw"
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
        )
        if proc.returncode != 0:
            raise DesktopRpcError("clipboard_failed", proc.stderr.strip() or "读取剪贴板失败。")
        text = proc.stdout.rstrip("\r\n")
        return {"text": text[:10000], "truncated": str(len(text) > 10000).lower()}

    def clipboard_set(self, text: str) -> dict[str, Any]:
        ps = "[Console]::InputEncoding = [Text.Encoding]::UTF8; $t = [Console]::In.ReadToEnd(); Set-Clipboard -Value $t"
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            input=text, capture_output=True, text=True, encoding="utf-8", timeout=5,
        )
        if proc.returncode != 0:
            raise DesktopRpcError("clipboard_failed", proc.stderr.strip() or "写入剪贴板失败。")
        return {"ok": True, "length": len(text)}

    def open_target(self, target: str, kind: str = "auto") -> dict[str, Any]:
        clean = (target or "").strip()
        if not clean:
            raise DesktopRpcError("invalid_target", "打开目标不能为空。")
        parsed = urlsplit(clean)
        is_url = kind == "url" or (kind == "auto" and parsed.scheme in {"http", "https"} and bool(parsed.netloc))
        if kind == "url" and parsed.scheme not in {"http", "https"}:
            raise DesktopRpcError("invalid_url", "仅允许打开 http:// 或 https:// 网址。")
        try:
            if is_url:
                os.startfile(clean)
            elif kind == "path" or clean.startswith(("~", "\\\\")) or (len(clean) >= 2 and clean[1] == ":"):
                resolved = resolve_safe_path(clean)
                if not resolved.exists():
                    raise DesktopRpcError("not_found", f"路径不存在：{resolved}")
                os.startfile(str(resolved))
            else:
                candidate = Path(clean).expanduser()
                if candidate.exists():
                    os.startfile(str(candidate))
                else:
                    subprocess.Popen(["cmd", "/c", "start", "", clean], shell=False)
        except OSError as error:
            raise DesktopRpcError("open_failed", f"打开失败：{error}") from None
        return {"ok": True, "opened": clean}

    def gui_action(
        self,
        action: str,
        *,
        x: int | None = None,
        y: int | None = None,
        text: str | None = None,
        keys: list[str] | None = None,
        scroll_y: int = 0,
    ) -> dict[str, Any]:
        user32 = ctypes.windll.user32
        _ensure_dpi_aware()
        if action in {"click", "double_click", "right_click", "move"}:
            if x is None or y is None:
                raise DesktopRpcError("invalid_args", f"{action} 需要坐标 x 和 y。")
            user32.SetCursorPos(int(x), int(y))
            if action == "click":
                user32.mouse_event(_MOUSEEVENTF_LEFTDOWN | _MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            elif action == "double_click":
                user32.mouse_event(_MOUSEEVENTF_LEFTDOWN | _MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                user32.mouse_event(_MOUSEEVENTF_LEFTDOWN | _MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            elif action == "right_click":
                user32.mouse_event(_MOUSEEVENTF_RIGHTDOWN | _MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
            return {"ok": True, "action": action, "x": int(x), "y": int(y)}
        if action == "scroll":
            if x is not None and y is not None:
                user32.SetCursorPos(int(x), int(y))
            user32.mouse_event(_MOUSEEVENTF_WHEEL, 0, 0, int(scroll_y) * 120, 0)
            return {"ok": True, "action": "scroll", "scroll_y": int(scroll_y)}
        if action == "type_text":
            if not text:
                raise DesktopRpcError("invalid_args", "type_text 需要输入文本。")
            utf16 = text.encode("utf-16-le")
            units = [int.from_bytes(utf16[i:i + 2], "little") for i in range(0, len(utf16), 2)]
            events: list[_INPUT] = []
            for code in units:
                for flag in (_KEYEVENTF_UNICODE, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP):
                    ev = _INPUT(type=_INPUT_KEYBOARD)
                    ev.union.ki = _KEYBDINPUT(wVk=0, wScan=code, dwFlags=flag, time=0, dwExtraInfo=None)
                    events.append(ev)
            arr = (_INPUT * len(events))(*events)
            user32.SendInput(len(events), arr, ctypes.sizeof(_INPUT))
            return {"ok": True, "action": "type_text", "length": len(text)}
        if action == "hotkey":
            if not keys:
                raise DesktopRpcError("invalid_args", "hotkey 需要按键列表。")
            mods = []
            normal = []
            for raw in keys:
                token = str(raw).strip().lower()
                vk = _VK_MAP.get(token)
                if vk is None:
                    raise DesktopRpcError("unsupported_key", f"不支持的按键名称：{raw}")
                if token in _MODIFIERS:
                    mods.append(vk)
                else:
                    normal.append(vk)
            order = mods + normal
            events: list[_INPUT] = []
            for vk in order:
                ev = _INPUT(type=_INPUT_KEYBOARD)
                ev.union.ki = _KEYBDINPUT(wVk=vk, wScan=0, dwFlags=0, time=0, dwExtraInfo=None)
                events.append(ev)
            for vk in reversed(order):
                ev = _INPUT(type=_INPUT_KEYBOARD)
                ev.union.ki = _KEYBDINPUT(wVk=vk, wScan=0, dwFlags=_KEYEVENTF_KEYUP, time=0, dwExtraInfo=None)
                events.append(ev)
            arr = (_INPUT * len(events))(*events)
            user32.SendInput(len(events), arr, ctypes.sizeof(_INPUT))
            return {"ok": True, "action": "hotkey", "keys": list(keys)}
        raise DesktopRpcError("unsupported_action", f"不支持的 GUI 动作：{action}")
