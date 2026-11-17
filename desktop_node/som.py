"""Set-of-Mark (SoM) visual bounding-box annotator for desktop screenshots."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_PALETTE_RGB = (
    (225, 29, 72),   # rose-600
    (37, 99, 235),   # blue-600
    (5, 150, 105),   # emerald-600
    (217, 119, 6),   # amber-600
    (124, 58, 237),  # violet-600
    (8, 145, 178),   # cyan-600
    (190, 24, 93),   # pink-700
    (22, 163, 74),   # green-600
)

_MACOS_SOM_SWIFT = r"""
import AppKit
import CoreGraphics
import Foundation
import ImageIO

struct BoxItem: Decodable {
    let idx: Int
    let left: Double
    let top: Double
    let width: Double
    let height: Double
    let r: Double
    let g: Double
    let b: Double
}

let args = CommandLine.arguments
if args.count < 4 {
    fputs("usage: som <in.jpg> <boxes.json> <out.jpg>\n", stderr)
    exit(2)
}
let inURL = URL(fileURLWithPath: args[1])
let jsonURL = URL(fileURLWithPath: args[2])
let outURL = URL(fileURLWithPath: args[3])

guard let imgData = try? Data(contentsOf: jsonURL),
      let boxes = try? JSONDecoder().decode([BoxItem].self, from: imgData),
      let src = CGImageSourceCreateWithURL(inURL as CFURL, nil),
      let cgImg = CGImageSourceCreateImageAtIndex(src, 0, nil) else {
    fputs("failed to load screenshot or boxes\n", stderr)
    exit(1)
}

let width = cgImg.width
let height = cgImg.height
guard let rep = NSBitmapImageRep(
    bitmapDataPlanes: nil,
    pixelsWide: width,
    pixelsHigh: height,
    bitsPerSample: 8,
    samplesPerPixel: 4,
    hasAlpha: true,
    isPlanar: false,
    colorSpaceName: .deviceRGB,
    bytesPerRow: 0,
    bitsPerPixel: 0
) else {
    fputs("failed to allocate bitmap\n", stderr)
    exit(1)
}

guard let nsCtx = NSGraphicsContext(bitmapImageRep: rep) else {
    fputs("failed to create graphics context\n", stderr)
    exit(1)
}

NSGraphicsContext.saveGraphicsState()
let rawCtx = nsCtx.cgContext
// Draw base image upright in native bottom-up CoreGraphics coordinates first.
rawCtx.draw(cgImg, in: CGRect(x: 0, y: 0, width: width, height: height))

// Flip CTM once so top-left is (0, 0) for SoM boxes, and mark flipped=true so AppKit draws text upright.
rawCtx.translateBy(x: 0, y: CGFloat(height))
rawCtx.scaleBy(x: 1, y: -1)
let flippedCtx = NSGraphicsContext(cgContext: rawCtx, flipped: true)
NSGraphicsContext.current = flippedCtx

let font = NSFont.boldSystemFont(ofSize: 13)
let attrs: [NSAttributedString.Key: Any] = [
    .font: font,
    .foregroundColor: NSColor.white,
]

var placedBadges: [CGRect] = []
func overlapsPlaced(_ cand: CGRect) -> Bool {
    for p in placedBadges {
        let inter = p.intersection(cand)
        if !inter.isNull && inter.width > 6 && inter.height > 6 {
            return true
        }
    }
    return false
}

for item in boxes {
    let color = NSColor(
        calibratedRed: CGFloat(item.r / 255.0),
        green: CGFloat(item.g / 255.0),
        blue: CGFloat(item.b / 255.0),
        alpha: 0.94
    )
    let rect = CGRect(x: item.left, y: item.top, width: item.width, height: item.height)
    let boxPath = NSBezierPath(roundedRect: rect, xRadius: 3, yRadius: 3)
    boxPath.lineWidth = 2.0
    color.setStroke()
    boxPath.stroke()

    let label = "\(item.idx)" as NSString
    let textSize = label.size(withAttributes: attrs)
    let bw = max(18.0, ceil(textSize.width) + 8.0)
    let bh = max(17.0, ceil(textSize.height) + 2.0)

    let candidates: [CGPoint] = [
        CGPoint(x: max(1.0, min(CGFloat(width) - bw - 1.0, rect.minX)),
                y: max(1.0, rect.minY - bh + 2.0)),
        CGPoint(x: max(1.0, min(CGFloat(width) - bw - 1.0, rect.maxX - bw)),
                y: max(1.0, rect.minY - bh + 2.0)),
        CGPoint(x: max(1.0, min(CGFloat(width) - bw - 1.0, rect.minX + 2.0)),
                y: min(CGFloat(height) - bh - 1.0, rect.minY + 2.0)),
        CGPoint(x: max(1.0, min(CGFloat(width) - bw - 1.0, rect.minX)),
                y: min(CGFloat(height) - bh - 1.0, rect.maxY - 2.0)),
    ]
    var badgeRect = CGRect(origin: candidates[0], size: CGSize(width: bw, height: bh))
    for candOrigin in candidates {
        let cand = CGRect(origin: candOrigin, size: CGSize(width: bw, height: bh))
        if !overlapsPlaced(cand) {
            badgeRect = cand
            break
        }
    }
    placedBadges.append(badgeRect)

    let badgePath = NSBezierPath(roundedRect: badgeRect, xRadius: 3, yRadius: 3)
    color.setFill()
    badgePath.fill()
    NSColor.white.withAlphaComponent(0.9).setStroke()
    badgePath.lineWidth = 1.0
    badgePath.stroke()

    let textPoint = CGPoint(
        x: badgeRect.minX + (bw - textSize.width) / 2.0,
        y: badgeRect.minY + (bh - textSize.height) / 2.0 - 0.5
    )
    label.draw(at: textPoint, withAttributes: attrs)
}

NSGraphicsContext.restoreGraphicsState()

guard let outData = rep.representation(using: .jpeg, properties: [.compressionFactor: 0.82]) else {
    fputs("failed to encode jpeg\n", stderr)
    exit(1)
}
try outData.write(to: outURL)
"""

_WINDOWS_SOM_PS = r"""
param(
    [Parameter(Mandatory=$true)][string]$InputPath,
    [Parameter(Mandatory=$true)][string]$BoxesPath,
    [Parameter(Mandatory=$true)][string]$OutputPath
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$boxes = Get-Content -Raw -Path $BoxesPath -Encoding UTF8 | ConvertFrom-Json
$srcBmp = [System.Drawing.Bitmap]::FromFile($InputPath)
try {
    $bmp = New-Object System.Drawing.Bitmap($srcBmp.Width, $srcBmp.Height, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
    try {
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
        $g.DrawImage($srcBmp, 0, 0, $srcBmp.Width, $srcBmp.Height)
        $font = New-Object System.Drawing.Font('Segoe UI', 10, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
        $whiteBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)
        $whitePen = New-Object System.Drawing.Pen([System.Drawing.Color]::White, 1)
        $placed = New-Object System.Collections.Generic.List[System.Drawing.RectangleF]
        try {
            foreach ($item in $boxes) {
                $col = [System.Drawing.Color]::FromArgb(240, [int]$item.r, [int]$item.g, [int]$item.b)
                $pen = New-Object System.Drawing.Pen($col, 2)
                $brush = New-Object System.Drawing.SolidBrush($col)
                try {
                    $g.DrawRectangle($pen, [float]$item.left, [float]$item.top, [float]$item.width, [float]$item.height)
                    $label = [string]$item.idx
                    $sz = $g.MeasureString($label, $font)
                    $bw = [Math]::Max(18.0, [Math]::Ceiling($sz.Width) + 6.0)
                    $bh = [Math]::Max(16.0, [Math]::Ceiling($sz.Height) + 2.0)
                    $candX = [Math]::Max(1.0, [Math]::Min($srcBmp.Width - $bw - 1.0, [float]$item.left))
                    $candY = [Math]::Max(1.0, [float]$item.top - $bh + 2.0)
                    $badge = New-Object System.Drawing.RectangleF($candX, $candY, $bw, $bh)
                    foreach ($p in $placed) {
                        $inter = [System.Drawing.RectangleF]::Intersect($p, $badge)
                        if ($inter.Width -gt 6 -and $inter.Height -gt 6) {
                            $altY = [Math]::Min($srcBmp.Height - $bh - 1.0, [float]$item.top + 2.0)
                            $badge = New-Object System.Drawing.RectangleF($candX, $altY, $bw, $bh)
                            break
                        }
                    }
                    $placed.Add($badge) | Out-Null
                    $g.FillRectangle($brush, $badge)
                    $g.DrawRectangle($whitePen, $badge.X, $badge.Y, $badge.Width, $badge.Height)
                    $g.DrawString($label, $font, $whiteBrush, ($badge.X + ($bw - $sz.Width) / 2.0), ($badge.Y + ($bh - $sz.Height) / 2.0))
                } finally {
                    $pen.Dispose()
                    $brush.Dispose()
                }
            }
        } finally {
            $font.Dispose()
            $whiteBrush.Dispose()
            $whitePen.Dispose()
            $g.Dispose()
        }
        $jpegCodec = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object { $_.MimeType -eq 'image/jpeg' } | Select-Object -First 1
        if ($jpegCodec) {
            $encParams = New-Object System.Drawing.Imaging.EncoderParameters(1)
            $encParams.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter([System.Drawing.Imaging.Encoder]::Quality, [long]82)
            $bmp.Save($OutputPath, $jpegCodec, $encParams)
        } else {
            $bmp.Save($OutputPath, [System.Drawing.Imaging.ImageFormat]::Jpeg)
        }
    } finally {
        $bmp.Dispose()
    }
} finally {
    $srcBmp.Dispose()
}
"""

_MACOS_SOM_BIN: Path | None = None
_MACOS_SOM_FAILED = False


def build_som_boxes(
    elements: list[dict],
    *,
    image_width: int,
    image_height: int,
    screen_width: int,
    screen_height: int,
) -> list[dict]:
    """Convert raw UI elements into image-space Set-of-Mark boxes preserving exact element_index."""
    if not elements or image_width <= 0 or image_height <= 0:
        return []
    sx = (image_width / float(screen_width)) if screen_width > 0 else 1.0
    sy = (image_height / float(screen_height)) if screen_height > 0 else 1.0
    area_cap = float(image_width * image_height) * 0.72
    boxes: list[dict] = []
    for pos, elem in enumerate(elements):
        if not isinstance(elem, dict):
            continue
        try:
            idx = int(elem.get("index", pos))
            cx = float(elem["x"]) * sx
            cy = float(elem["y"]) * sy
            bw = float(elem.get("width") or 36.0) * sx
            bh = float(elem.get("height") or 24.0) * sy
        except (KeyError, TypeError, ValueError):
            continue
        if bw < 6.0 or bh < 6.0 or (bw * bh) > area_cap:
            continue
        left = max(1.0, cx - bw / 2.0)
        top = max(1.0, cy - bh / 2.0)
        right = min(float(image_width) - 1.0, cx + bw / 2.0)
        bottom = min(float(image_height) - 1.0, cy + bh / 2.0)
        if right - left < 4.0 or bottom - top < 4.0:
            continue
        r, g, b = _PALETTE_RGB[idx % len(_PALETTE_RGB)]
        boxes.append({
            "idx": idx,
            "left": round(left, 1),
            "top": round(top, 1),
            "width": round(right - left, 1),
            "height": round(bottom - top, 1),
            "r": r,
            "g": g,
            "b": b,
        })
    return boxes


def _ensure_macos_som_bin() -> Path | None:
    global _MACOS_SOM_BIN, _MACOS_SOM_FAILED
    if _MACOS_SOM_BIN is not None and _MACOS_SOM_BIN.exists():
        return _MACOS_SOM_BIN
    if _MACOS_SOM_FAILED or sys.platform != "darwin" or not shutil.which("swiftc"):
        return None
    digest = hashlib.sha256(_MACOS_SOM_SWIFT.encode("utf-8")).hexdigest()[:12]
    cache_dir = Path.home() / ".cache" / "xiaodan"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    src = cache_dir / f"desktop-som-{digest}.swift"
    bin_path = cache_dir / f"desktop-som-{digest}"
    if not bin_path.exists():
        src.write_text(_MACOS_SOM_SWIFT, encoding="utf-8")
        res = subprocess.run(
            ["swiftc", "-O", str(src), "-o", str(bin_path)],
            capture_output=True, text=True, check=False, timeout=60,
        )
        if res.returncode != 0 or not bin_path.exists():
            _MACOS_SOM_FAILED = True
            return None
    _MACOS_SOM_BIN = bin_path
    return bin_path


def _annotate_pil(image_bytes: bytes, boxes: list[dict]) -> bytes | None:
    if importlib.util.find_spec("PIL") is None:
        return None
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFont

    with Image.open(BytesIO(image_bytes)) as img:
        rgb = img.convert("RGB")
        draw = ImageDraw.Draw(rgb)
        font = ImageFont.load_default()
        for item in boxes:
            col = (int(item["r"]), int(item["g"]), int(item["b"]))
            x0, y0 = float(item["left"]), float(item["top"])
            x1, y1 = x0 + float(item["width"]), y0 + float(item["height"])
            draw.rectangle([x0, y0, x1, y1], outline=col, width=2)
            label = str(item["idx"])
            bw = max(18, len(label) * 8 + 8)
            bh = 16
            bx = max(1.0, min(rgb.width - bw - 1.0, x0))
            by = max(1.0, y0 - bh + 2.0)
            draw.rectangle([bx, by, bx + bw, by + bh], fill=col, outline=(255, 255, 255))
            draw.text((bx + 4, by + 2), label, fill=(255, 255, 255), font=font)
        buf = BytesIO()
        rgb.save(buf, format="JPEG", quality=82)
        return buf.getvalue()


def _run_external_annotator(cmd_builder, image_bytes: bytes, boxes: list[dict]) -> bytes | None:
    tmp_dir = tempfile.mkdtemp(prefix="xiaodan-som-")
    try:
        in_path = os.path.join(tmp_dir, "in.jpg")
        boxes_path = os.path.join(tmp_dir, "boxes.json")
        out_path = os.path.join(tmp_dir, "out.jpg")
        with open(in_path, "wb") as f:
            f.write(image_bytes)
        with open(boxes_path, "w", encoding="utf-8") as f:
            json.dump(boxes, f, ensure_ascii=False)
        cmd = cmd_builder(in_path, boxes_path, out_path, tmp_dir)
        if not cmd:
            return None
        res = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=15)
        if res.returncode != 0 or not os.path.exists(out_path):
            return None
        with open(out_path, "rb") as f:
            data = f.read()
        return data or None
    except Exception:
        return None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def annotate_screenshot_som(
    image_bytes: bytes,
    elements: list[dict],
    *,
    image_width: int,
    image_height: int,
    screen_width: int,
    screen_height: int,
) -> tuple[bytes, bool]:
    """Draw Set-of-Mark numbered bounding boxes matching ui_elements indices.

    Returns `(annotated_jpeg_bytes, True)` on success, or `(image_bytes, False)`
    if there are no drawable boxes or no local renderer is available.
    """
    if not image_bytes:
        return image_bytes, False
    boxes = build_som_boxes(
        elements,
        image_width=image_width,
        image_height=image_height,
        screen_width=screen_width,
        screen_height=screen_height,
    )
    if not boxes:
        return image_bytes, False

    pil_out = _annotate_pil(image_bytes, boxes)
    if pil_out:
        return pil_out, True

    if sys.platform == "darwin":
        som_bin = _ensure_macos_som_bin()
        if som_bin is not None:
            out = _run_external_annotator(
                lambda i, b, o, _d: [str(som_bin), i, b, o],
                image_bytes,
                boxes,
            )
            if out:
                return out, True

    if sys.platform == "win32":
        def _win_cmd(i: str, b: str, o: str, tmp_dir: str) -> list[str]:
            ps_path = os.path.join(tmp_dir, "draw_som.ps1")
            with open(ps_path, "w", encoding="utf-8") as f:
                f.write(_WINDOWS_SOM_PS)
            return [
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", ps_path,
                "-InputPath", i, "-BoxesPath", b, "-OutputPath", o,
            ]

        out = _run_external_annotator(_win_cmd, image_bytes, boxes)
        if out:
            return out, True

    return image_bytes, False
