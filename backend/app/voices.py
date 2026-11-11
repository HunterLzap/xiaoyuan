"""Saved cloned voices: processing, naming and lookup.

A cloned voice is just a short reference clip the provider re-learns on every request, so
the stored file is kept small on purpose. The pipeline is: trim leading/trailing silence,
resample to 24 kHz mono, encode MP3 at 48 kbps. Measured on this project, a 397 KB WAV
sample took 11-36s per synthesis while the same voice as a 50 KB MP3 took 2.5-3.2s.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

from .config import ROOT
from .llm import ProviderError

VOICE_DIR = ROOT / "models" / "voice"
INDEX = ROOT / "data" / "voices.json"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
TARGET_RATE = 24000
TARGET_BITRATE = "48k"
PROCESS_TIMEOUT = 60
NAME_LIMIT = 24


def _voice_dir() -> Path:
    """Actual storage directory; read at call time so tests can redirect it."""
    return VOICE_DIR


def _ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if not found:
        raise ProviderError(500, "ffmpeg_missing", "音色处理需要 ffmpeg，当前环境未找到。")
    return found


def validate_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned:
        raise ProviderError(422, "voice_name_required", "请为这个声音起一个名字。")
    if len(cleaned) > NAME_LIMIT:
        raise ProviderError(422, "voice_name_too_long", f"名字最多 {NAME_LIMIT} 个字符。")
    if re.search(r'[\\/\x00-\x1f<>:"|?*]', cleaned):
        raise ProviderError(422, "voice_name_invalid", "名字不能包含斜杠或特殊符号。")
    return cleaned


def _slug(name: str) -> str:
    """Filesystem-safe identifier that stays readable for Chinese names."""
    keep = re.sub(r'[^0-9A-Za-z\u4e00-\u9fff_-]', "", name)
    return keep[:32] or f"voice{int(time.time())}"


def read_index() -> list[dict]:
    if not INDEX.is_file():
        return []
    try:
        data = json.loads(INDEX.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    voices = data.get("voices") if isinstance(data, dict) else None
    if not isinstance(voices, list):
        return []
    return [item for item in voices if isinstance(item, dict) and item.get("id") and item.get("name")]


def write_index(voices: list[dict]) -> None:
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=INDEX.parent,
                                         prefix="voices-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump({"voices": voices}, handle, ensure_ascii=False, indent=1)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, INDEX)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def public_list() -> list[dict]:
    """Voices safe to show in the UI (no absolute paths)."""
    result = []
    for voice in read_index():
        sample = voice.get("sample")
        resolved = (_voice_dir() / Path(sample).name) if sample else None
        if resolved is None or not resolved.is_file():
            continue
        result.append({"id": voice["id"], "name": voice["name"],
                       "kb": round(resolved.stat().st_size / 1024, 1),
                       "created": voice.get("created")})
    return result


def resolve(sample: str | Path) -> Path | None:
    """Resolve a sample path inside the project, refusing anything outside it."""
    if not sample:
        return None
    candidate = Path(sample)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(ROOT.resolve())
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() else None


def find_by_id(voice_id: str) -> dict | None:
    for voice in read_index():
        if voice.get("id") == voice_id:
            return voice
    return None


def sample_for(voice_id: str) -> str:
    """Return the project-relative sample path for a saved voice, or "" if unknown."""
    voice = find_by_id(voice_id)
    if voice is None:
        return ""
    sample = voice.get("sample")
    return sample if resolve(sample) else ""


def process_upload(raw: bytes, source_name: str, name: str) -> dict:
    """Trim, resample and compress an uploaded clip into a storable reference sample."""
    if not raw:
        raise ProviderError(422, "voice_audio_empty", "上传的音频是空的。")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ProviderError(422, "voice_audio_too_large", "音频不能超过 10MB。")
    display = validate_name(name)
    ffmpeg = _ffmpeg()
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    directory = _voice_dir()
    voice_id = _slug(display)
    suffix = 1
    while find_by_id(voice_id) or (directory / f"{voice_id}.mp3").exists():
        suffix += 1
        voice_id = f"{_slug(display)}{suffix}"

    with tempfile.TemporaryDirectory() as scratch:
        source = Path(scratch) / ("in" + (Path(source_name).suffix.lower() or ".wav"))
        source.write_bytes(raw)
        target = directory / f"{voice_id}.mp3"
        # silenceremove trims both ends; the rate/bitrate choice keeps the sample near 50 KB.
        filters = (
            "silenceremove=start_periods=1:start_silence=0.1:start_threshold=-45dB,"
            "areverse,"
            "silenceremove=start_periods=1:start_silence=0.1:start_threshold=-45dB,"
            "areverse"
        )
        completed = subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-i", str(source), "-af", filters,
             "-ac", "1", "-ar", str(TARGET_RATE), "-b:a", TARGET_BITRATE, "-f", "mp3", str(target)],
            capture_output=True, timeout=PROCESS_TIMEOUT,
        )
        if completed.returncode != 0 or not target.is_file():
            message = completed.stderr.decode("utf-8", "replace").strip()[:200]
            raise ProviderError(422, "voice_process_failed",
                                "无法处理这段音频；请确认它是可播放的 wav 或 mp3。" + (f"（{message}）" if message else ""))

    size_kb = round(target.stat().st_size / 1024, 1)
    voice = {"id": voice_id, "name": display,
             "sample": str(Path("models") / "voice" / f"{voice_id}.mp3").replace("\\", "/"),
             "bytes": target.stat().st_size, "created": int(time.time())}
    voices = [item for item in read_index() if item.get("id") != voice_id]
    voices.append(voice)
    write_index(voices)
    return {**voice, "kb": size_kb}


def delete(voice_id: str) -> None:
    voices = read_index()
    remaining = []
    removed_sample = None
    for voice in voices:
        if voice.get("id") == voice_id:
            removed_sample = voice.get("sample")
            continue
        remaining.append(voice)
    if removed_sample is None:
        raise ProviderError(404, "voice_not_found", "没有找到这个声音。")
    # Only the file name is trusted: the stored path is bookkeeping, not authority.
    sample = _voice_dir() / Path(removed_sample).name
    try:
        sample.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        raise ProviderError(500, "voice_delete_failed", "无法删除音频文件，请检查项目目录权限。") from None
    write_index(remaining)
