"""macOS desktop control & screenshot adapter using built-in frameworks/tools."""
from __future__ import annotations

import base64
import ctypes
import ctypes.util
import os
from pathlib import Path
import plistlib
import re
import subprocess
import tempfile
from typing import Any
from urllib.parse import urlsplit

from .platform_base import DesktopAdapter, DesktopRpcError, resolve_safe_path

_MAC_KEYCODES: dict[str, int] = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19,
    "3": 20, "4": 21, "6": 22, "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28,
    "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35, "enter": 36,
    "return": 36, "l": 37, "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43,
    "/": 44, "n": 45, "m": 46, ".": 47, "tab": 48, "space": 49, "`": 50,
    "backspace": 51, "delete": 51, "esc": 53, "escape": 53,
    "f5": 96, "f6": 97, "f7": 98, "f3": 99, "f8": 100, "f9": 101, "f11": 103,
    "f10": 109, "f12": 111, "home": 115, "pageup": 116, "forwarddelete": 117,
    "f4": 118, "end": 119, "f2": 120, "pagedown": 121, "f1": 122,
    "left": 123, "right": 124, "down": 125, "up": 126,
}

_MAC_MODIFIERS: dict[str, int] = {
    "shift": 1 << 17,
    "ctrl": 1 << 18,
    "control": 1 << 18,
    "alt": 1 << 19,
    "option": 1 << 19,
    "opt": 1 << 19,
    "cmd": 1 << 20,
    "command": 1 << 20,
    "super": 1 << 20,
    "win": 1 << 20,
}

_MAC_APP_ALIASES: dict[str, tuple[str, ...]] = {
    "飞书": ("Lark", "Feishu"),
    "feishu": ("Lark", "Feishu"),
    "lark": ("Lark", "Feishu"),
    "微信": ("WeChat",),
    "wechat": ("WeChat",),
    "企业微信": ("企业微信", "WeCom", "WXWork"),
    "钉钉": ("DingTalk",),
    "腾讯会议": ("TencentMeeting", "VooV Meeting"),
    "剪映": ("VideoFusion-macOS", "CapCut"),
    "谷歌浏览器": ("Google Chrome", "Chrome"),
    "chrome": ("Google Chrome",),
    "火狐": ("Firefox",),
    "edge": ("Microsoft Edge",),
    "浏览器": ("Safari", "Google Chrome"),
    "终端": ("Terminal", "iTerm"),
    "备忘录": ("Notes",),
    "记事本": ("TextEdit", "Notes"),
    "计算器": ("Calculator",),
    "访达": ("Finder",),
    "音乐": ("Music", "QQMusic", "NeteaseMusic"),
    "网易云音乐": ("NeteaseMusic",),
    "qq音乐": ("QQMusic",),
    "qq": ("QQ",),
    "wps": ("wpsoffice", "WPS Office"),
    "vscode": ("Visual Studio Code",),
    "百度网盘": ("BaiduNetdisk_mac", "BaiduNetdisk"),
    "阿里云盘": ("aDrive",),
    "系统设置": ("System Settings", "System Preferences"),
    "活动监视器": ("Activity Monitor",),
}

_kCGHIDEventTap = 0
_kCGMouseButtonLeft = 0
_kCGMouseButtonRight = 1
_kCGEventLeftMouseDown = 1
_kCGEventLeftMouseUp = 2
_kCGEventRightMouseDown = 3
_kCGEventRightMouseUp = 4
_kCGEventMouseMoved = 5
_kCGEventScrollWheel = 22
_kCGScrollEventUnitLine = 1


def _load_cg():
    path = ctypes.util.find_library("ApplicationServices") or (
        "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
    )
    cg = ctypes.CDLL(path)

    class CGPoint(ctypes.Structure):
        _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

    cg.CGPoint = CGPoint
    cg.CGMainDisplayID.restype = ctypes.c_uint32
    cg.CGDisplayPixelsWide.argtypes = [ctypes.c_uint32]
    cg.CGDisplayPixelsWide.restype = ctypes.c_size_t
    cg.CGDisplayPixelsHigh.argtypes = [ctypes.c_uint32]
    cg.CGDisplayPixelsHigh.restype = ctypes.c_size_t

    cg.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, CGPoint, ctypes.c_uint32]
    cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
    cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
    cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
    cg.CGEventKeyboardSetUnicodeString.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_uint16)]
    cg.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    cg.CGEventSetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int64]
    cg.CGEventCreateScrollWheelEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int32]
    cg.CGEventCreateScrollWheelEvent.restype = ctypes.c_void_p
    cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    cg.CFRelease.argtypes = [ctypes.c_void_p]
    return cg


class MacOSDesktopAdapter(DesktopAdapter):
    os_name = "macos"

    def __init__(self):
        self._cg = None

    def _cg_lib(self):
        if self._cg is None:
            self._cg = _load_cg()
        return self._cg

    def screen_size(self) -> dict[str, int]:
        try:
            cg = self._cg_lib()
            did = cg.CGMainDisplayID()
            return {"width": int(cg.CGDisplayPixelsWide(did)), "height": int(cg.CGDisplayPixelsHigh(did))}
        except OSError:
            return {"width": 1440, "height": 900}

    def active_window(self) -> dict[str, str]:
        script = (
            'tell application "System Events"\n'
            '  set frontApp to name of first application process whose frontmost is true\n'
            '  set winTitle to ""\n'
            '  try\n'
            '    set winTitle to name of front window of application process frontApp\n'
            '  end try\n'
            '  return frontApp & "\t" & winTitle\n'
            'end tell'
        )
        proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=4)
        if proc.returncode != 0:
            return {"app": "", "title": "", "note": "如需前景窗口标题，请授予终端/Python 辅助功能权限"}
        app, _, title = proc.stdout.strip().partition("\t")
        return {"app": app, "title": title}

    def capture_screenshot(self, max_width: int = 1280, max_height: int = 800, quality: int = 80) -> dict[str, Any]:
        screen = self.screen_size()
        active = self.active_window()
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(prefix="xd-shot-", suffix=".jpg", delete=False) as handle:
                tmp_path = Path(handle.name)
            proc = subprocess.run(
                ["screencapture", "-x", "-t", "jpg", str(tmp_path)],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode != 0 or not tmp_path.exists() or tmp_path.stat().st_size == 0:
                raise DesktopRpcError("screen_capture_denied", "macOS 截屏失败：请在 系统设置 -> 隐私与安全性 -> 录屏 中授权。")
            w, h = self._sips_size(tmp_path)
            max_w = max(320, min(int(max_width), 1920))
            max_h = max(240, min(int(max_height), 1200))
            if w > max_w or h > max_h:
                ratio = min(max_w / max(w, 1), max_h / max(h, 1))
                target_w = max(1, round(w * ratio))
                target_h = max(1, round(h * ratio))
                subprocess.run(
                    ["sips", "--resampleHeightWidth", str(target_h), str(target_w),
                     "-s", "formatOptions", str(max(40, min(int(quality), 95))), str(tmp_path)],
                    capture_output=True, text=True, timeout=10,
                )
                w, h = self._sips_size(tmp_path)
            raw = tmp_path.read_bytes()
            return {
                "image_base64": base64.b64encode(raw).decode("ascii"),
                "mime_type": "image/jpeg",
                "image_width": w,
                "image_height": h,
                "screen_width": screen["width"],
                "screen_height": screen["height"],
                "active_window": active,
            }
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    @staticmethod
    def _sips_size(path: Path) -> tuple[int, int]:
        proc = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
                              capture_output=True, text=True, timeout=5)
        w = re.search(r"pixelWidth:\s*(\d+)", proc.stdout)
        h = re.search(r"pixelHeight:\s*(\d+)", proc.stdout)
        return (int(w.group(1)) if w else 0, int(h.group(1)) if h else 0)

    def clipboard_get(self) -> dict[str, str]:
        env = {**os.environ, "LC_ALL": "en_US.UTF-8"}
        proc = subprocess.run(["pbpaste"], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=5)
        if proc.returncode != 0:
            raise DesktopRpcError("clipboard_failed", proc.stderr.strip() or "读取剪贴板失败。")
        text = proc.stdout
        return {"text": text[:10000], "truncated": str(len(text) > 10000).lower()}

    def clipboard_set(self, text: str) -> dict[str, Any]:
        env = {**os.environ, "LC_ALL": "en_US.UTF-8"}
        proc = subprocess.run(["pbcopy"], input=text, capture_output=True, text=True, encoding="utf-8", env=env, timeout=5)
        if proc.returncode != 0:
            raise DesktopRpcError("clipboard_failed", proc.stderr.strip() or "写入剪贴板失败。")
        return {"ok": True, "length": len(text)}

    @staticmethod
    def _bundle_names(bundle: Path) -> set[str]:
        names = {bundle.stem.lower()}
        info_plist = bundle / "Contents" / "Info.plist"
        if info_plist.exists():
            try:
                data = plistlib.loads(info_plist.read_bytes())
                for key in ("CFBundleDisplayName", "CFBundleName", "CFBundleExecutable"):
                    val = data.get(key)
                    if isinstance(val, str) and val.strip():
                        names.add(val.strip().lower())
            except Exception:
                pass
        resources = bundle / "Contents" / "Resources"
        for lproj in ("zh-Hans.lproj", "zh_CN.lproj", "Base.lproj"):
            sp = resources / lproj / "InfoPlist.strings"
            if not sp.exists():
                continue
            try:
                raw = sp.read_bytes()
                try:
                    data = plistlib.loads(raw)
                    for key in ("CFBundleDisplayName", "CFBundleName"):
                        val = data.get(key)
                        if isinstance(val, str) and val.strip():
                            names.add(val.strip().lower())
                    continue
                except Exception:
                    pass
                text = raw.decode("utf-16", errors="ignore") if b"\x00" in raw[:64] else raw.decode("utf-8", errors="ignore")
                for m in re.finditer(r'CFBundle(?:Display)?Name\s*"?\s*=\s*"([^"]+)"', text):
                    names.add(m.group(1).strip().lower())
            except OSError:
                pass
        return names

    def _scan_app_bundles(self) -> list[Path]:
        roots = [Path("/Applications"), Path.home() / "Applications", Path("/System/Applications")]
        bundles: list[Path] = []
        for root in roots:
            if not root.exists():
                continue
            try:
                for p in root.iterdir():
                    if p.suffix.lower() == ".app":
                        bundles.append(p)
                    elif p.is_dir() and not p.name.startswith("."):
                        try:
                            for sub in p.iterdir():
                                if sub.suffix.lower() == ".app":
                                    bundles.append(sub)
                        except OSError:
                            pass
            except OSError:
                pass
        return bundles

    def _resolve_app_bundle(self, target: str) -> str | None:
        clean = (target or "").strip()
        lowered = clean.lower()
        candidates: list[str] = [clean]
        for key, vals in _MAC_APP_ALIASES.items():
            if lowered == key.lower() or key.lower() in lowered:
                candidates.extend(vals)
        seen: list[str] = []
        for item in candidates:
            if item and item not in seen:
                seen.append(item)
        bundles = self._scan_app_bundles()
        bundle_index = [(b, self._bundle_names(b)) for b in bundles]
        for cand in seen:
            cl = cand.lower()
            for bundle, names in bundle_index:
                if cl in names:
                    return str(bundle)
        for cand in seen:
            safe_q = re.sub(r"[\'\"\\\n\r*]", "", cand).strip()
            if not safe_q:
                continue
            try:
                proc = subprocess.run(
                    ["mdfind", f"kMDItemContentType == 'com.apple.application-bundle' && (kMDItemDisplayName == '*{safe_q}*'cd || kMDItemFSName == '*{safe_q}*'cd)"],
                    capture_output=True, text=True, timeout=4,
                )
                if proc.returncode == 0:
                    for line in proc.stdout.splitlines():
                        p = line.strip()
                        if p.endswith(".app") and Path(p).exists():
                            return p
            except (OSError, subprocess.SubprocessError):
                pass
        for cand in seen:
            cl = cand.lower()
            for bundle, names in bundle_index:
                if any(cl in n for n in names):
                    return str(bundle)
        return None

    def open_target(self, target: str, kind: str = "auto") -> dict[str, Any]:
        clean = (target or "").strip()
        if not clean:
            raise DesktopRpcError("invalid_target", "打开目标不能为空。")
        parsed = urlsplit(clean)
        is_url = kind == "url" or (kind == "auto" and parsed.scheme in {"http", "https"} and bool(parsed.netloc))
        if kind == "url" and parsed.scheme not in {"http", "https"}:
            raise DesktopRpcError("invalid_url", "仅允许打开 http:// 或 https:// 网址。")
        if is_url:
            cmd = ["open", clean]
        elif kind == "app":
            cmd = ["open", "-a", clean]
        elif kind == "path" or clean.startswith(("~", "/")):
            resolved = resolve_safe_path(clean)
            if not resolved.exists():
                raise DesktopRpcError("not_found", f"路径不存在：{resolved}")
            cmd = ["open", str(resolved)]
        else:
            candidate = Path(clean).expanduser()
            cmd = ["open", str(candidate)] if candidate.exists() else ["open", "-a", clean]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if proc.returncode != 0 and (kind == "app" or (kind == "auto" and not is_url and not clean.startswith(("~", "/")))):
            resolved_bundle = self._resolve_app_bundle(clean)
            if resolved_bundle:
                proc2 = subprocess.run(["open", resolved_bundle], capture_output=True, text=True, timeout=10)
                if proc2.returncode == 0:
                    return {"ok": True, "opened": resolved_bundle, "requested": clean}
        if proc.returncode != 0:
            raise DesktopRpcError("open_failed", proc.stderr.strip() or f"打开失败：{clean}")
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
        cg = self._cg_lib()
        if action in {"click", "double_click", "right_click", "move"}:
            if x is None or y is None:
                raise DesktopRpcError("invalid_args", f"{action} 需要坐标 x 和 y。")
            pt = cg.CGPoint(float(x), float(y))
            self._post_mouse(cg, _kCGEventMouseMoved, pt, _kCGMouseButtonLeft)
            if action == "click":
                self._post_mouse(cg, _kCGEventLeftMouseDown, pt, _kCGMouseButtonLeft)
                self._post_mouse(cg, _kCGEventLeftMouseUp, pt, _kCGMouseButtonLeft)
            elif action == "double_click":
                for count in (1, 2):
                    down = cg.CGEventCreateMouseEvent(None, _kCGEventLeftMouseDown, pt, _kCGMouseButtonLeft)
                    up = cg.CGEventCreateMouseEvent(None, _kCGEventLeftMouseUp, pt, _kCGMouseButtonLeft)
                    cg.CGEventSetIntegerValueField(down, 1, count)
                    cg.CGEventSetIntegerValueField(up, 1, count)
                    cg.CGEventPost(_kCGHIDEventTap, down)
                    cg.CGEventPost(_kCGHIDEventTap, up)
                    cg.CFRelease(down)
                    cg.CFRelease(up)
            elif action == "right_click":
                self._post_mouse(cg, _kCGEventRightMouseDown, pt, _kCGMouseButtonRight)
                self._post_mouse(cg, _kCGEventRightMouseUp, pt, _kCGMouseButtonRight)
            return {"ok": True, "action": action, "x": int(x), "y": int(y)}
        if action == "scroll":
            if x is not None and y is not None:
                self._post_mouse(cg, _kCGEventMouseMoved, cg.CGPoint(float(x), float(y)), _kCGMouseButtonLeft)
            ev = cg.CGEventCreateScrollWheelEvent(None, _kCGScrollEventUnitLine, 1, int(scroll_y))
            cg.CGEventPost(_kCGHIDEventTap, ev)
            cg.CFRelease(ev)
            return {"ok": True, "action": "scroll", "scroll_y": int(scroll_y)}
        if action == "type_text":
            if not text:
                raise DesktopRpcError("invalid_args", "type_text 需要输入文本。")
            utf16 = text.encode("utf-16-le")
            units = [int.from_bytes(utf16[i:i + 2], "little") for i in range(0, len(utf16), 2)]
            for start in range(0, len(units), 16):
                chunk = units[start:start + 16]
                buf = (ctypes.c_uint16 * len(chunk))(*chunk)
                down = cg.CGEventCreateKeyboardEvent(None, 0, True)
                cg.CGEventKeyboardSetUnicodeString(down, len(chunk), buf)
                cg.CGEventPost(_kCGHIDEventTap, down)
                cg.CFRelease(down)
                up = cg.CGEventCreateKeyboardEvent(None, 0, False)
                cg.CGEventKeyboardSetUnicodeString(up, len(chunk), buf)
                cg.CGEventPost(_kCGHIDEventTap, up)
                cg.CFRelease(up)
            return {"ok": True, "action": "type_text", "length": len(text)}
        if action == "hotkey":
            if not keys:
                raise DesktopRpcError("invalid_args", "hotkey 需要按键列表。")
            flags = 0
            main_code: int | None = None
            for raw in keys:
                token = str(raw).strip().lower()
                if token in _MAC_MODIFIERS:
                    flags |= _MAC_MODIFIERS[token]
                elif token in _MAC_KEYCODES:
                    main_code = _MAC_KEYCODES[token]
                else:
                    raise DesktopRpcError("unsupported_key", f"不支持的按键名称：{raw}")
            if main_code is None:
                raise DesktopRpcError("invalid_args", "hotkey 必须包含至少一个非修饰键。")
            down = cg.CGEventCreateKeyboardEvent(None, main_code, True)
            up = cg.CGEventCreateKeyboardEvent(None, main_code, False)
            if flags:
                cg.CGEventSetFlags(down, flags)
                cg.CGEventSetFlags(up, flags)
            cg.CGEventPost(_kCGHIDEventTap, down)
            cg.CGEventPost(_kCGHIDEventTap, up)
            cg.CFRelease(down)
            cg.CFRelease(up)
            return {"ok": True, "action": "hotkey", "keys": list(keys)}
        raise DesktopRpcError("unsupported_action", f"不支持的 GUI 动作：{action}")

    @staticmethod
    def _post_mouse(cg, event_type: int, pt, button: int) -> None:
        ev = cg.CGEventCreateMouseEvent(None, event_type, pt, button)
        cg.CGEventPost(_kCGHIDEventTap, ev)
        cg.CFRelease(ev)
