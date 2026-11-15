import argparse
import hashlib
import json
import struct
import zlib
from pathlib import Path


def read_png(path):
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Not a PNG: {path}")
    compressed = bytearray()
    cursor = 8
    while cursor < len(data):
        length = struct.unpack_from(">I", data, cursor)[0]
        kind = data[cursor + 4:cursor + 8]
        payload = data[cursor + 8:cursor + 8 + length]
        if kind == b"IHDR":
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
            if (depth, color, compression, filtering, interlace) != (8, 6, 0, 0, 0):
                raise ValueError(f"Expected non-interlaced RGBA8 PNG: {path}")
        elif kind == b"IDAT":
            compressed.extend(payload)
        cursor += length + 12
    encoded = zlib.decompress(compressed)
    stride = width * 4
    pixels = bytearray()
    previous = bytearray(stride)
    for row_index in range(height):
        offset = row_index * (stride + 1)
        filter_type = encoded[offset]
        row = bytearray(encoded[offset + 1:offset + 1 + stride])
        for column in range(stride):
            left = row[column - 4] if column >= 4 else 0
            above = previous[column]
            upper_left = previous[column - 4] if column >= 4 else 0
            if filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = above
            elif filter_type == 3:
                predictor = (left + above) // 2
            elif filter_type == 4:
                estimate = left + above - upper_left
                distances = (abs(estimate - left), abs(estimate - above), abs(estimate - upper_left))
                predictor = (left, above, upper_left)[distances.index(min(distances))]
            elif filter_type == 0:
                predictor = 0
            else:
                raise ValueError(f"Unsupported PNG row filter: {filter_type}")
            row[column] = (row[column] + predictor) & 255
        pixels.extend(row)
        previous = row
    return width, height, pixels


def compress_rle(data):
    output = bytearray()
    cursor = 0
    while cursor < len(data):
        run = 1
        while cursor + run < len(data) and run < 127 and data[cursor + run] == data[cursor]:
            run += 1
        if run >= 3:
            output.extend((run, data[cursor]))
            cursor += run
            continue
        start = cursor
        while cursor < len(data) and cursor - start < 127:
            if cursor + 2 < len(data) and data[cursor] == data[cursor + 1] == data[cursor + 2]:
                break
            cursor += 1
        output.append(0x80 | (cursor - start))
        output.extend(data[start:cursor])
    return output


def indexed_image(frame, width, height):
    colors = sorted({frame[offset:offset + 4] for offset in range(0, len(frame), 4)})
    if len(colors) > 16:
        raise ValueError(f"Animation frame exceeds I4 palette: {len(colors)} colors")
    palette = b"".join(bytes((color[2], color[1], color[0], color[3])) for color in colors)
    palette += bytes((16 - len(colors)) * 4)
    indices = {color: index for index, color in enumerate(colors)}
    bitmap = bytearray()
    for offset in range(0, len(frame), 8):
        bitmap.append((indices[frame[offset:offset + 4]] << 4) | indices[frame[offset + 4:offset + 8]])
    raw = palette + bitmap
    compressed = compress_rle(raw)
    header = struct.pack("<BBHHHHH", 0x19, 0x09, 0x0008, width, height, width // 2, 0)
    return header + struct.pack("<III", 1, len(compressed), len(raw)) + compressed


def enum_name(name):
    return "".join(part.capitalize() for part in name.split("_"))


def build(source, assets, header):
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    width, height = manifest["frame_width"], manifest["frame_height"]
    columns = manifest["columns"]
    assets.mkdir(parents=True, exist_ok=True)
    header.parent.mkdir(parents=True, exist_ok=True)
    unique = {}
    sequences = []
    total_bytes = 0
    for animation in manifest["animations"]:
        sheet_width, sheet_height, pixels = read_png(source / f"{animation['name']}.png")
        if sheet_width != width * columns or sheet_height % height:
            raise ValueError(f"Invalid spritesheet grid: {animation['name']}")
        sequence = []
        for frame_index in range((sheet_width // width) * (sheet_height // height)):
            left = frame_index % columns * width
            top = frame_index // columns * height
            frame = bytes().join(
                pixels[((top + row) * sheet_width + left) * 4:((top + row) * sheet_width + left + width) * 4]
                for row in range(height)
            )
            alpha = frame[3::4]
            if frame_index >= animation["frames"]:
                if any(alpha):
                    raise ValueError(f"Nonempty unused cell: {animation['name']}/{frame_index}")
                continue
            if not any(alpha) or any(alpha[:18 * width]) or any(alpha[106 * width:]):
                raise ValueError(f"Invalid content or reserved area: {animation['name']}/{frame_index}")
            if set(alpha) - {0, 255}:
                raise ValueError(f"Unexpected partial alpha: {animation['name']}/{frame_index}")
            digest = hashlib.sha256(frame).digest()
            if digest not in unique:
                index = len(unique)
                unique[digest] = index
                encoded = indexed_image(frame, width, height)
                (assets / f"robot-{index:03d}.bin").write_bytes(encoded)
                total_bytes += len(encoded)
            sequence.append(unique[digest])
        if len(sequence) != animation["frames"]:
            raise ValueError(f"Frame count mismatch: {animation['name']}")
        sequences.append(sequence)
    for path in assets.glob("robot-*.bin"):
        if int(path.stem.split("-")[1]) >= len(unique):
            path.unlink()
    lines = [
        "#pragma once", "#include <cstdint>", "",
        "namespace DeviceAnimations {",
        "enum class State { " + ", ".join(enum_name(item["name"]) for item in manifest["animations"]) + ", Count };",
        "enum class Playback { Loop, Once, Hold };",
        "struct Animation { const char* label; const uint16_t* frames; uint16_t count; Playback playback; State next; };",
        f"inline constexpr uint32_t kFrameMs = {manifest['frame_ms']};",
        "inline constexpr const char* kFrameNames[] = {",
    ]
    lines.extend(f'    "robot-{index:03d}.bin",' for index in range(len(unique)))
    lines.append("};")
    for animation, sequence in zip(manifest["animations"], sequences):
        lines.append(f"inline constexpr uint16_t k{enum_name(animation['name'])}Frames[] = {{ "
                     + ", ".join(map(str, sequence)) + " };")
    lines.append("inline constexpr Animation kAnimations[] = {")
    for animation in manifest["animations"]:
        lines.append(f'    {{"{animation["label"]}", k{enum_name(animation["name"])}Frames, '
                     f'{animation["frames"]}, Playback::{animation["playback"]}, State::{enum_name(animation["next"])} }},')
    lines.extend(["};", "}"])
    header.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Device animations: {sum(map(len, sequences))} frames, {len(unique)} unique, {total_bytes} bytes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--header", type=Path, required=True)
    options = parser.parse_args()
    build(options.source, options.assets, options.header)
