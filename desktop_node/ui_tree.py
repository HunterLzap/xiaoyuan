"""Cross-platform OS accessibility UI tree inspection & post-action focus read-back."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import platform
import shutil
import subprocess

logger = logging.getLogger("desktop_node.ui_tree")

_MACOS_SWIFT_UITREE = r'''
import AppKit
import ApplicationServices
import Foundation

func strAttr(_ el: AXUIElement, _ attr: String) -> String {
    var val: AnyObject?
    guard AXUIElementCopyAttributeValue(el, attr as CFString, &val) == .success else { return "" }
    if let s = val as? String { return s.trimmingCharacters(in: .whitespacesAndNewlines) }
    if let n = val as? NSNumber { return n.stringValue }
    return ""
}

func rectAttr(_ el: AXUIElement) -> CGRect? {
    var pVal: AnyObject?; var sVal: AnyObject?
    guard AXUIElementCopyAttributeValue(el, kAXPositionAttribute as CFString, &pVal) == .success,
          AXUIElementCopyAttributeValue(el, kAXSizeAttribute as CFString, &sVal) == .success else { return nil }
    var pt = CGPoint.zero; var sz = CGSize.zero
    if AXValueGetValue(pVal as! AXValue, .cgPoint, &pt) && AXValueGetValue(sVal as! AXValue, .cgSize, &sz) {
        return CGRect(origin: pt, size: sz)
    }
    return nil
}

func focusSummary(_ appEl: AXUIElement) -> [String: Any]? {
    var fObj: AnyObject?
    guard AXUIElementCopyAttributeValue(appEl, kAXFocusedUIElementAttribute as CFString, &fObj) == .success,
          let fObj = fObj else { return nil }
    let fEl = fObj as! AXUIElement
    let role = strAttr(fEl, kAXRoleAttribute)
    let title = strAttr(fEl, kAXTitleAttribute)
    let desc = strAttr(fEl, kAXDescriptionAttribute)
    let ph = strAttr(fEl, kAXPlaceholderValueAttribute)
    let val = strAttr(fEl, kAXValueAttribute)
    let name = [title, desc, ph].first(where: { !$0.isEmpty }) ?? ""
    var info: [String: Any] = ["role": role, "name": String(name.prefix(60)), "value": String(val.prefix(120))]
    if let r = rectAttr(fEl), r.width >= 4 && r.height >= 4 {
        info["x"] = Int(r.midX)
        info["y"] = Int(r.midY)
    }
    return info
}

let args = CommandLine.arguments
let focusOnly = args.contains("--focus-only")
var maxItems = 70
if let idx = args.firstIndex(of: "--max"), idx + 1 < args.count, let parsed = Int(args[idx + 1]) {
    maxItems = max(10, min(parsed, 150))
}

var output: [String: Any] = ["app": "", "focused": NSNull(), "elements": []]
if let app = NSWorkspace.shared.frontmostApplication {
    output["app"] = app.localizedName ?? ""
    let appEl = AXUIElementCreateApplication(app.processIdentifier)
    AXUIElementSetAttributeValue(appEl, "AXManualAccessibility" as CFString, kCFBooleanTrue)
    AXUIElementSetAttributeValue(appEl, "AXEnhancedUserInterface" as CFString, kCFBooleanTrue)

    let focused = focusSummary(appEl)
    if let focused = focused {
        output["focused"] = focused
    }
    let focusX = (focused?["x"] as? Int) ?? -9999
    let focusY = (focused?["y"] as? Int) ?? -9999

    if !focusOnly {
        var roots: [AXUIElement] = []
        var winObj: AnyObject?
        if AXUIElementCopyAttributeValue(appEl, kAXFocusedWindowAttribute as CFString, &winObj) == .success, let w = winObj {
            roots.append(w as! AXUIElement)
        }
        var winsObj: AnyObject?
        if AXUIElementCopyAttributeValue(appEl, kAXWindowsAttribute as CFString, &winsObj) == .success,
           let wins = winsObj as? [AXUIElement] {
            for w in wins.prefix(3) {
                if !roots.contains(where: { CFEqual($0, w) }) {
                    roots.append(w)
                }
            }
        }
        if roots.isEmpty { roots = [appEl] }
        let interactive: Set<String> = [
            "AXButton", "AXTextField", "AXTextArea", "AXSearchField", "AXComboBox",
            "AXPopUpButton", "AXCheckBox", "AXRadioButton", "AXMenuItem", "AXLink",
            "AXRow", "AXCell", "AXTab", "AXStaticText", "AXList", "AXHeading"
        ]
        var results: [[String: Any]] = []
        var seen = Set<String>()
        var queue: [(AXUIElement, Int)] = roots.map { ($0, 0) }
        var visited = 0
        while !queue.isEmpty && visited < 1500 && results.count < maxItems {
            let (cur, depth) = queue.removeFirst()
            visited += 1
            let role = strAttr(cur, kAXRoleAttribute)
            let title = strAttr(cur, kAXTitleAttribute)
            let desc = strAttr(cur, kAXDescriptionAttribute)
            let ph = strAttr(cur, kAXPlaceholderValueAttribute)
            let val = strAttr(cur, kAXValueAttribute)
            let rawName = [title, desc, ph].first(where: { !$0.isEmpty }) ?? val
            if let r = rectAttr(cur), r.width >= 6 && r.height >= 6 && r.width < 1400 && r.height < 900 && r.midX > 0 && r.midY > 0 {
                let isInput = role.contains("Text") || role.contains("Search") || role == "AXComboBox"
                let isLabeledCard = role == "AXGroup" && !rawName.isEmpty && r.width >= 24 && r.height >= 18 && r.width <= 760 && r.height <= 160
                if (interactive.contains(role) || isLabeledCard) && (!rawName.isEmpty || isInput) {
                    let cx = Int(r.midX)
                    let cy = Int(r.midY)
                    let shortName = String(rawName.replacingOccurrences(of: "\n", with: " ").prefix(64))
                    let dedupKey = "\(role)|\(shortName)|\(cx / 8)|\(cy / 8)"
                    if !seen.contains(dedupKey) {
                        seen.insert(dedupKey)
                        results.append([
                            "index": results.count,
                            "role": role,
                            "name": shortName,
                            "value": isInput ? String(val.prefix(80)) : "",
                            "x": cx,
                            "y": cy,
                            "width": Int(r.width),
                            "height": Int(r.height),
                            "focused": abs(cx - focusX) <= 4 && abs(cy - focusY) <= 4,
                        ])
                    }
                }
            }
            if depth < 18 {
                var chObj: AnyObject?
                if AXUIElementCopyAttributeValue(cur, kAXChildrenAttribute as CFString, &chObj) == .success,
                   let ch = chObj as? [AXUIElement] {
                    for c in ch.prefix(64) {
                        queue.append((c, depth + 1))
                    }
                }
            }
        }
        output["elements"] = results
    }
}

if let data = try? JSONSerialization.data(withJSONObject: output, options: []),
   let txt = String(data: data, encoding: .utf8) {
    print(txt)
}
'''


def _ensure_macos_uitree_binary() -> Path | None:
    swiftc = shutil.which("swiftc")
    if not swiftc:
        return None
    digest = hashlib.sha256(_MACOS_SWIFT_UITREE.encode("utf-8")).hexdigest()[:12]
    cache_dir = Path.home() / ".cache" / "xiaodan"
    binary = cache_dir / f"desktop-uitree-{digest}"
    if binary.exists() and binary.is_file():
        return binary
    cache_dir.mkdir(parents=True, exist_ok=True)
    src = cache_dir / f"desktop-uitree-{digest}.swift"
    tmp_bin = cache_dir / f"desktop-uitree-{digest}.tmp"
    try:
        src.write_text(_MACOS_SWIFT_UITREE, encoding="utf-8")
        proc = subprocess.run(
            [swiftc, "-O", str(src), "-o", str(tmp_bin)],
            capture_output=True, text=True, timeout=45,
        )
        if proc.returncode != 0 or not tmp_bin.exists():
            logger.debug("swiftc uitree build failed: %s", proc.stderr.strip())
            return None
        tmp_bin.replace(binary)
        return binary
    except (OSError, subprocess.SubprocessError) as error:
        logger.debug("macos uitree build error: %s", error)
        return None
    finally:
        src.unlink(missing_ok=True)
        tmp_bin.unlink(missing_ok=True)


def _inspect_macos_ui(*, focus_only: bool = False, max_elements: int = 70) -> dict:
    empty = {"app": "", "focused": None, "elements": []}
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return empty
    binary = _ensure_macos_uitree_binary()
    if binary is None:
        return empty
    cmd = [str(binary), "--max", str(max(10, min(int(max_elements), 150)))]
    if focus_only:
        cmd.append("--focus-only")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=4)
        if proc.returncode != 0 or not proc.stdout.strip():
            return empty
        data = json.loads(proc.stdout.strip())
        if isinstance(data, dict):
            return {
                "app": str(data.get("app") or ""),
                "focused": data.get("focused") if isinstance(data.get("focused"), dict) else None,
                "elements": data.get("elements") if isinstance(data.get("elements"), list) else [],
            }
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        logger.debug("macos uitree inspect error: %s", error)
    return empty


def _inspect_windows_ui(*, focus_only: bool = False, max_elements: int = 70) -> dict:
    empty = {"app": "", "focused": None, "elements": []}
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return empty
    max_n = max(10, min(int(max_elements), 150))
    focus_flag = "$true" if focus_only else "$false"
    ps = f'''
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$ErrorActionPreference = 'SilentlyContinue'
$focusedObj = $null
$el = [System.Windows.Automation.AutomationElement]::FocusedElement
if ($el) {{
    $valText = ""
    $vp = $null
    if ($el.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$vp)) {{
        $valText = [string]$vp.Current.Value
    }}
    $fr = $el.Current.BoundingRectangle
    $focusedObj = @{{
        role = [string]$el.Current.ControlType.ProgrammaticName
        name = ([string]$el.Current.Name).Substring(0, [Math]::Min(60, ([string]$el.Current.Name).Length))
        value = $valText.Substring(0, [Math]::Min(120, $valText.Length))
    }}
    if (-not [double]::IsInfinity($fr.Width) -and $fr.Width -gt 0) {{
        $focusedObj.x = [int][Math]::Round($fr.Left + $fr.Width / 2)
        $focusedObj.y = [int][Math]::Round($fr.Top + $fr.Height / 2)
    }}
}}
$items = New-Object System.Collections.ArrayList
$appName = ""
if (-not {focus_flag} -and $el) {{
    $walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
    $win = $el
    while ($win) {{
        $parent = $walker.GetParent($win)
        if (-not $parent -or $parent -eq [System.Windows.Automation.AutomationElement]::RootElement) {{ break }}
        $win = $parent
    }}
    if ($win) {{
        $appName = [string]$win.Current.Name
        $q = New-Object System.Collections.Queue
        $q.Enqueue(@{{ el = $win; depth = 0 }})
        $visited = 0
        $seen = New-Object System.Collections.Generic.HashSet[string]
        while ($q.Count -gt 0 -and $visited -lt 600 -and $items.Count -lt {max_n}) {{
            $node = $q.Dequeue()
            $cur = $node.el; $depth = $node.depth
            $visited++
            $c = $cur.Current
            $rect = $c.BoundingRectangle
            if (-not $c.IsOffscreen -and -not [double]::IsInfinity($rect.Width) -and $rect.Width -ge 6 -and $rect.Height -ge 6 -and $rect.Width -lt 1800) {{
                $role = [string]$c.ControlType.ProgrammaticName
                $name = ([string]$c.Name) -replace "[\\r\\n]+", " "
                $isInput = ($role -like "*Edit*" -or $role -like "*Document*" -or $role -like "*ComboBox*")
                $valTxt = ""
                if ($isInput) {{
                    $vp2 = $null
                    if ($cur.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$vp2)) {{
                        $valTxt = [string]$vp2.Current.Value
                    }}
                }}
                if (($name.Length -gt 0 -or $isInput) -and ($role -match "Button|Edit|Document|Text|ListItem|TreeItem|MenuItem|Hyperlink|TabItem|ComboBox|CheckBox")) {{
                    $cx = [int][Math]::Round($rect.Left + $rect.Width / 2)
                    $cy = [int][Math]::Round($rect.Top + $rect.Height / 2)
                    $sn = $name.Substring(0, [Math]::Min(64, $name.Length))
                    $key = "$role|$sn|$([int]($cx/8))|$([int]($cy/8))"
                    if ($seen.Add($key)) {{
                        [void]$items.Add(@{{
                            index = $items.Count
                            role = $role
                            name = $sn
                            value = $valTxt.Substring(0, [Math]::Min(80, $valTxt.Length))
                            x = $cx
                            y = $cy
                            width = [int][Math]::Round($rect.Width)
                            height = [int][Math]::Round($rect.Height)
                            focused = ($el -and $cur -eq $el)
                        }})
                    }}
                }}
            }}
            if ($depth -lt 10) {{
                $child = $walker.GetFirstChild($cur)
                $cnt = 0
                while ($child -and $cnt -lt 40) {{
                    $q.Enqueue(@{{ el = $child; depth = ($depth + 1) }})
                    $child = $walker.GetNextSibling($child)
                    $cnt++
                }}
            }}
        }}
    }}
}}
@{{ app = $appName; focused = $focusedObj; elements = $items }} | ConvertTo-Json -Depth 4 -Compress
'''
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=6,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return empty
        data = json.loads(proc.stdout.strip())
        if isinstance(data, dict):
            return {
                "app": str(data.get("app") or ""),
                "focused": data.get("focused") if isinstance(data.get("focused"), dict) else None,
                "elements": data.get("elements") if isinstance(data.get("elements"), list) else [],
            }
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        logger.debug("windows uitree inspect error: %s", error)
    return empty


def inspect_ui_tree(*, os_name: str | None = None, focus_only: bool = False, max_elements: int = 70) -> dict:
    target_os = (os_name or platform.system()).lower()
    if target_os in {"darwin", "macos"}:
        return _inspect_macos_ui(focus_only=focus_only, max_elements=max_elements)
    if target_os == "windows":
        return _inspect_windows_ui(focus_only=focus_only, max_elements=max_elements)
    return {"app": "", "focused": None, "elements": []}
