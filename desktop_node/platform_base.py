"""Shared cross-platform adapter interface, filesystem/path guards, and shell runner."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
import platform
import subprocess
import time
from typing import Any

from .ui_tree import inspect_ui_tree

SENSITIVE_PATH_PARTS = frozenset({".ssh", ".gnupg", ".aws", ".kube", "keychains"})
SENSITIVE_FILENAMES = frozenset({
    ".env", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
    "desktop_nodes.json", "assistant_state.sqlite3", "devices.json",
    "cookies", "login data",
})
SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore", ".jks")


class DesktopRpcError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def is_sensitive_path(path_str: str) -> bool:
    raw = (path_str or "").strip()
    if not raw:
        return False
    expanded = str(Path(raw).expanduser())
    normalized = expanded.replace("\\", "/")
    parts = [p.lower() for p in normalized.split("/") if p and p != "."]
    if any(part in SENSITIVE_PATH_PARTS for part in parts):
        return True
    name = parts[-1] if parts else ""
    if name in SENSITIVE_FILENAMES or name.startswith(".env."):
        return True
    return any(name.endswith(ext) for ext in SENSITIVE_SUFFIXES)


def resolve_safe_path(path_str: str) -> Path:
    raw = (path_str or "").strip() or "~"
    if is_sensitive_path(raw):
        raise DesktopRpcError("access_denied", "为保护凭证与私钥安全，桌面节点拒绝访问该路径。")
    resolved = Path(raw).expanduser().resolve()
    if is_sensitive_path(str(resolved)):
        raise DesktopRpcError("access_denied", "为保护凭证与私钥安全，桌面节点拒绝访问该路径。")
    return resolved


class DesktopAdapter(ABC):
    os_name: str = "unknown"

    def capabilities(self, *, allow_shell: bool = True, allow_gui: bool = True) -> list[str]:
        caps = ["screenshot", "clipboard", "files", "open"]
        if allow_gui:
            caps.append("gui")
        if allow_shell:
            caps.append("shell")
        return caps

    @abstractmethod
    def screen_size(self) -> dict[str, int]:
        ...

    @abstractmethod
    def active_window(self) -> dict[str, str]:
        ...

    @abstractmethod
    def capture_screenshot(self, max_width: int = 1280, max_height: int = 800, quality: int = 80) -> dict[str, Any]:
        ...

    @abstractmethod
    def clipboard_get(self) -> dict[str, str]:
        ...

    @abstractmethod
    def clipboard_set(self, text: str) -> dict[str, Any]:
        ...

    @abstractmethod
    def open_target(self, target: str, kind: str = "auto") -> dict[str, Any]:
        ...

    def ui_tree(self, max_elements: int = 70) -> dict[str, Any]:
        return inspect_ui_tree(os_name=self.os_name, focus_only=False, max_elements=max_elements)

    def post_action_readback(self) -> dict[str, Any]:
        ui = inspect_ui_tree(os_name=self.os_name, focus_only=True)
        return {
            "active_window": self.active_window(),
            "focused_element": ui.get("focused"),
        }

    def _wait_for_ui(self, seconds: float) -> dict[str, Any]:
        duration = max(0.2, min(float(seconds), 5.0))
        time.sleep(duration)
        return {"ok": True, "action": "wait", "wait_seconds": duration, **self.post_action_readback()}

    def _paste_via_clipboard(self, text: str, paste_keys: list[str], enter_key: str, *, submit: bool = False) -> bool:
        prev: str | None = None
        try:
            got = self.clipboard_get()
            raw = got.get("text")
            if isinstance(raw, str) and len(raw) <= 2000 and got.get("truncated") != "true":
                prev = raw
        except DesktopRpcError:
            prev = None
        try:
            self.clipboard_set(text)
        except DesktopRpcError:
            return False
        time.sleep(0.05)
        self.gui_action("hotkey", keys=paste_keys, _readback=False)
        time.sleep(0.14)
        if submit:
            self.gui_action("hotkey", keys=[enter_key], _readback=False)
            time.sleep(0.12)
        if prev is not None:
            try:
                self.clipboard_set(prev)
            except DesktopRpcError:
                pass
        return True

    @abstractmethod
    def gui_action(
        self,
        action: str,
        *,
        x: int | None = None,
        y: int | None = None,
        text: str | None = None,
        keys: list[str] | None = None,
        scroll_y: int = 0,
        submit: bool = False,
        wait_seconds: float = 1.5,
        _readback: bool = True,
    ) -> dict[str, Any]:
        ...

    def list_dir(self, path: str = "~", max_entries: int = 60) -> dict[str, Any]:
        target = resolve_safe_path(path)
        if not target.exists():
            raise DesktopRpcError("not_found", f"路径不存在：{target}")
        if not target.is_dir():
            raise DesktopRpcError("not_directory", f"目标不是目录：{target}")
        entries = []
        truncated = False
        try:
            items = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            raise DesktopRpcError("access_denied", f"没有权限读取目录：{target}") from None
        limit = max(1, min(int(max_entries), 120))
        for item in items:
            if len(entries) >= limit:
                truncated = True
                break
            entry: dict[str, Any] = {
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
            }
            if item.is_file():
                try:
                    entry["size_bytes"] = item.stat().st_size
                except OSError:
                    entry["size_bytes"] = None
            entries.append(entry)
        return {"path": str(target), "entries": entries, "truncated": truncated}

    def read_file(self, path: str, offset: int = 0, limit: int = 6000) -> dict[str, Any]:
        target = resolve_safe_path(path)
        if not target.exists():
            raise DesktopRpcError("not_found", f"文件不存在：{target}")
        if not target.is_file():
            raise DesktopRpcError("not_file", f"目标不是文件：{target}")
        try:
            size = target.stat().st_size
            raw = target.read_bytes()[:256 * 1024]
        except PermissionError:
            raise DesktopRpcError("access_denied", f"没有权限读取文件：{target}") from None
        except OSError as error:
            raise DesktopRpcError("io_error", f"读取文件失败：{error}") from None
        if b"\x00" in raw[:1024]:
            raise DesktopRpcError("binary_file", "该文件似乎是二进制文件，无法以纯文本读取。")
        text = raw.decode("utf-8", errors="replace")
        start = max(0, int(offset))
        max_chars = max(100, min(int(limit), 12000))
        chunk = text[start:start + max_chars]
        return {
            "path": str(target),
            "size_bytes": size,
            "offset": start,
            "content": chunk,
            "truncated": (start + len(chunk)) < len(text) or size > len(raw),
        }

    def run_command(self, command: str, cwd: str | None = None, timeout_seconds: int = 10) -> dict[str, Any]:
        work_dir = resolve_safe_path(cwd) if cwd else Path.home()
        if not work_dir.is_dir():
            raise DesktopRpcError("invalid_cwd", f"工作目录不存在：{work_dir}")
        timeout = max(1, min(int(timeout_seconds), 30))
        system = platform.system().lower()
        if system == "windows":
            args = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
        else:
            shell = "/bin/zsh" if Path("/bin/zsh").exists() else "/bin/sh"
            args = [shell, "-lc", command]
        try:
            proc = subprocess.run(
                args,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            return {
                "exit_code": proc.returncode,
                "cwd": str(work_dir),
                "stdout": proc.stdout[:6000],
                "stderr": proc.stderr[:2000],
                "stdout_truncated": len(proc.stdout) > 6000,
                "stderr_truncated": len(proc.stderr) > 2000,
            }
        except subprocess.TimeoutExpired:
            raise DesktopRpcError("command_timeout", f"命令执行超过 {timeout} 秒已终止。") from None
        except OSError as error:
            raise DesktopRpcError("command_failed", f"无法启动命令：{error}") from None
