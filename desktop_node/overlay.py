"""Cross-platform non-intrusive screen edge border and top HUD status pill."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import threading

logger = logging.getLogger("desktop_node.overlay")

_MACOS_SWIFT_HUD = r'''
import AppKit
import Foundation

final class BorderOverlayView: NSView {
    var statusText: String = "小圆正在操作电脑" {
        didSet { needsDisplay = true }
    }
    var pulseOn: Bool = true {
        didSet { needsDisplay = true }
    }

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        NSColor.clear.setFill()
        dirtyRect.fill()

        let strokeWidth: CGFloat = 4.0
        let inset = strokeWidth / 2.0 + 1.0
        let borderRect = bounds.insetBy(dx: inset, dy: inset)
        let borderPath = NSBezierPath(roundedRect: borderRect, xRadius: 10, yRadius: 10)
        borderPath.lineWidth = strokeWidth
        NSColor(calibratedRed: 0.22, green: 0.74, blue: 0.97, alpha: 0.85).setStroke()
        borderPath.stroke()

        let innerPath = NSBezierPath(roundedRect: borderRect.insetBy(dx: 2.5, dy: 2.5), xRadius: 8, yRadius: 8)
        innerPath.lineWidth = 1.5
        NSColor(calibratedRed: 0.56, green: 0.88, blue: 1.0, alpha: 0.32).setStroke()
        innerPath.stroke()

        let font = NSFont.systemFont(ofSize: 13, weight: .semibold)
        let attrs: [NSAttributedString.Key: Any] = [
            .font: font,
            .foregroundColor: NSColor(white: 0.98, alpha: 1.0)
        ]
        let label = statusText as NSString
        let textSize = label.size(withAttributes: attrs)
        let dotDiameter: CGFloat = 8.0
        let padX: CGFloat = 14.0
        let gap: CGFloat = 8.0
        let pillWidth = min(bounds.width - 40.0, padX * 2 + dotDiameter + gap + textSize.width)
        let pillHeight: CGFloat = 32.0
        let topOffset: CGFloat = 42.0
        let pillX = (bounds.width - pillWidth) / 2.0
        let pillY = bounds.height - topOffset - pillHeight
        let pillRect = NSRect(x: pillX, y: pillY, width: pillWidth, height: pillHeight)
        let pillPath = NSBezierPath(roundedRect: pillRect, xRadius: pillHeight / 2.0, yRadius: pillHeight / 2.0)

        NSColor(calibratedRed: 0.08, green: 0.10, blue: 0.14, alpha: 0.90).setFill()
        pillPath.fill()

        pillPath.lineWidth = 1.2
        NSColor(calibratedRed: 0.22, green: 0.74, blue: 0.97, alpha: 0.88).setStroke()
        pillPath.stroke()

        let dotColor = pulseOn
            ? NSColor(calibratedRed: 0.22, green: 0.74, blue: 0.97, alpha: 1.0)
            : NSColor(calibratedRed: 0.22, green: 0.74, blue: 0.97, alpha: 0.45)
        let dotRect = NSRect(
            x: pillX + padX,
            y: pillY + (pillHeight - dotDiameter) / 2.0,
            width: dotDiameter,
            height: dotDiameter
        )
        dotColor.setFill()
        NSBezierPath(ovalIn: dotRect).fill()

        let textRect = NSRect(
            x: pillX + padX + dotDiameter + gap,
            y: pillY + (pillHeight - textSize.height) / 2.0 - 0.5,
            width: pillWidth - (padX * 2 + dotDiameter + gap),
            height: textSize.height
        )
        label.draw(in: textRect, withAttributes: attrs)
    }
}

final class HUDController {
    let window: NSPanel
    let overlayView: BorderOverlayView
    var pulseTimer: Timer?

    init() {
        let frame = NSScreen.main?.frame ?? NSRect(x: 0, y: 0, width: 1280, height: 800)
        window = NSPanel(
            contentRect: frame,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = false
        window.ignoresMouseEvents = true
        window.hidesOnDeactivate = false
        window.level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.statusWindow)) + 5)
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        window.sharingType = .none

        overlayView = BorderOverlayView(frame: NSRect(origin: .zero, size: frame.size))
        overlayView.autoresizingMask = [.width, .height]
        window.contentView = overlayView
    }

    func show(text: String) {
        if let screenFrame = NSScreen.main?.frame {
            window.setFrame(screenFrame, display: false)
        }
        overlayView.statusText = text
        window.orderFrontRegardless()
        if pulseTimer == nil {
            pulseTimer = Timer.scheduledTimer(withTimeInterval: 0.65, repeats: true) { [weak self] _ in
                self?.overlayView.pulseOn.toggle()
            }
        }
    }

    func hide() {
        pulseTimer?.invalidate()
        pulseTimer = nil
        window.orderOut(nil)
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let controller = HUDController()

DispatchQueue.global(qos: .userInitiated).async {
    while let line = readLine() {
        guard let data = line.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let cmd = obj["cmd"] as? String else {
            continue
        }
        DispatchQueue.main.async {
            switch cmd {
            case "show":
                let text = (obj["text"] as? String) ?? "小圆正在操作电脑"
                controller.show(text: text)
            case "hide":
                controller.hide()
            case "quit":
                controller.hide()
                app.terminate(nil)
            default:
                break
            }
        }
    }
    DispatchQueue.main.async {
        controller.hide()
        app.terminate(nil)
    }
}

app.run()
'''


def _ensure_macos_hud_binary() -> Path | None:
    swiftc = shutil.which("swiftc")
    if not swiftc:
        return None
    digest = hashlib.sha256(_MACOS_SWIFT_HUD.encode("utf-8")).hexdigest()[:12]
    cache_dir = Path.home() / ".cache" / "xiaodan"
    binary = cache_dir / f"desktop-hud-{digest}"
    if binary.exists() and binary.is_file():
        return binary
    cache_dir.mkdir(parents=True, exist_ok=True)
    src = cache_dir / f"desktop-hud-{digest}.swift"
    tmp_bin = cache_dir / f"desktop-hud-{digest}.tmp"
    try:
        src.write_text(_MACOS_SWIFT_HUD, encoding="utf-8")
        proc = subprocess.run(
            [swiftc, "-O", str(src), "-o", str(tmp_bin)],
            capture_output=True, text=True, timeout=45,
        )
        if proc.returncode != 0 or not tmp_bin.exists():
            logger.debug("swiftc overlay build failed: %s", proc.stderr.strip())
            return None
        tmp_bin.replace(binary)
        return binary
    except (OSError, subprocess.SubprocessError) as error:
        logger.debug("macos overlay prepare error: %s", error)
        return None
    finally:
        src.unlink(missing_ok=True)
        tmp_bin.unlink(missing_ok=True)


def _run_windows_tk_worker() -> int:
    import ctypes
    import queue
    import tkinter as tk

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    cmd_queue: queue.Queue[dict] = queue.Queue()

    def _stdin_reader():
        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if isinstance(msg, dict):
                cmd_queue.put(msg)
        cmd_queue.put({"cmd": "quit"})

    reader = threading.Thread(target=_stdin_reader, daemon=True)
    reader.start()

    root = tk.Tk()
    transparent_key = "#010203"
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-transparentcolor", transparent_key)
    root.configure(bg=transparent_key)
    w = root.winfo_screenwidth()
    h = root.winfo_screenheight()
    root.geometry(f"{w}x{h}+0+0")

    canvas = tk.Canvas(root, width=w, height=h, bg=transparent_key, highlightthickness=0, bd=0)
    canvas.pack(fill="both", expand=True)

    hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
    gwl_exstyle = -20
    ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, gwl_exstyle)
    # WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
    ex_style |= 0x00080000 | 0x00000020 | 0x08000000 | 0x00000080
    ctypes.windll.user32.SetWindowLongW(hwnd, gwl_exstyle, ex_style)
    try:
        # WDA_EXCLUDEFROMCAPTURE: hide overlay from CopyFromScreen while keeping visible to user
        ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x00000011)
    except Exception:
        pass

    root.withdraw()
    pulse_state = {"on": True, "visible": False, "text": "小圆正在操作电脑"}

    def _draw():
        canvas.delete("all")
        if not pulse_state["visible"]:
            return
        canvas.create_rectangle(2, 2, w - 3, h - 3, outline="#38bdf8", width=4)
        text = pulse_state["text"]
        pill_w = min(w - 60, max(220, len(text) * 14 + 54))
        x1 = (w - pill_w) // 2
        y1 = 8
        x2 = x1 + pill_w
        y2 = 40
        canvas.create_rectangle(x1, y1, x2, y2, fill="#14171c", outline="#38bdf8", width=1)
        dot_color = "#38bdf8" if pulse_state["on"] else "#1d4ed8"
        canvas.create_oval(x1 + 14, y1 + 12, x1 + 22, y1 + 20, fill=dot_color, outline="")
        canvas.create_text((x1 + 30 + x2 - 12) // 2, (y1 + y2) // 2, text=text, fill="#f8fafc",
                           font=("Microsoft YaHei UI", 10, "bold"))

    def _poll():
        try:
            while True:
                msg = cmd_queue.get_nowait()
                cmd = msg.get("cmd")
                if cmd == "quit":
                    root.destroy()
                    return
                if cmd == "hide":
                    pulse_state["visible"] = False
                    root.withdraw()
                elif cmd == "show":
                    pulse_state["text"] = str(msg.get("text") or "小圆正在操作电脑")[:72]
                    pulse_state["visible"] = True
                    root.deiconify()
                    root.lift()
                    _draw()
        except queue.Empty:
            pass
        if pulse_state["visible"]:
            pulse_state["on"] = not pulse_state["on"]
            _draw()
        root.after(450, _poll)

    root.after(150, _poll)
    root.mainloop()
    return 0


class ScreenOverlayHUD:
    """Manages an optional out-of-process click-through screen border & status banner."""

    def __init__(self, enabled: bool = True):
        self.enabled = bool(enabled)
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._hide_timer: threading.Timer | None = None
        self._failed = False
        self._cmd_cache: list[str] | None = None

    def _worker_cmd(self) -> list[str] | None:
        if self._cmd_cache is not None:
            return self._cmd_cache
        sys_name = platform.system().lower()
        if sys_name == "darwin":
            binary = _ensure_macos_hud_binary()
            if binary is None:
                return None
            self._cmd_cache = [str(binary)]
            return self._cmd_cache
        if sys_name == "windows":
            self._cmd_cache = [sys.executable, "-m", "desktop_node.overlay", "--hud-worker"]
            return self._cmd_cache
        return None

    def _ensure_proc(self) -> subprocess.Popen[str] | None:
        if not self.enabled or self._failed:
            return None
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        cmd = self._worker_cmd()
        if not cmd:
            self._failed = True
            return None
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
            )
            return self._proc
        except OSError as error:
            logger.debug("HUD launch failed: %s", error)
            self._failed = True
            return None

    def _send(self, payload: dict) -> None:
        proc = self._ensure_proc()
        if proc is None or proc.stdin is None:
            return
        try:
            proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            proc.stdin.flush()
        except OSError:
            self._proc = None

    def _cancel_timer(self) -> None:
        if self._hide_timer is not None:
            self._hide_timer.cancel()
            self._hide_timer = None

    def show(self, label: str, detail: str = "") -> None:
        text = f"小圆正在操作电脑 · {label}" if label else "小圆正在操作电脑"
        clean_detail = (detail or "").strip()
        if clean_detail:
            text = f"{text}（{clean_detail[:32]}）"
        with self._lock:
            self._cancel_timer()
            self._send({"cmd": "show", "text": text})

    def schedule_hide(self, delay: float = 4.5) -> None:
        with self._lock:
            self._cancel_timer()
            if not self.enabled or self._proc is None:
                return
            timer = threading.Timer(max(0.5, float(delay)), self.hide)
            timer.daemon = True
            timer.start()
            self._hide_timer = timer

    def hide(self) -> None:
        with self._lock:
            self._cancel_timer()
            if self._proc is not None and self._proc.poll() is None:
                self._send({"cmd": "hide"})

    def close(self) -> None:
        with self._lock:
            self._cancel_timer()
            proc = self._proc
            self._proc = None
            if proc is not None:
                try:
                    if proc.stdin is not None:
                        proc.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
                        proc.stdin.flush()
                        proc.stdin.close()
                except OSError:
                    pass
                try:
                    proc.wait(timeout=1.5)
                except subprocess.SubprocessError:
                    proc.kill()


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if "--hud-worker" in args and platform.system().lower() == "windows":
        return _run_windows_tk_worker()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
