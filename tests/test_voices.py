"""Cloned voice library and audio shaping.

The clone pipeline and the volume/speed/pitch filters are the parts that silently change
what the user hears, so they get behavioural checks that do not depend on a paid provider.
"""
import io
import math
from pathlib import Path
import struct
import wave

import pytest

from backend.app import audio_fx, voices
from backend.app.llm import ProviderError


def tone(seconds: float = 1.0, rate: int = 24000, freq: float = 440.0) -> bytes:
    count = int(seconds * rate)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as sink:
        sink.setnchannels(1)
        sink.setsampwidth(2)
        sink.setframerate(rate)
        sink.writeframes(b"".join(
            struct.pack("<h", int(math.sin(2 * math.pi * freq * index / rate) * 0.2 * 32767))
            for index in range(count)))
    return buffer.getvalue()


def stats(raw: bytes) -> tuple[float, float]:
    """Duration and RMS, computed with the standard library only."""
    with wave.open(io.BytesIO(raw), "rb") as source:
        rate = source.getframerate()
        frames = source.getnframes()
        data = source.readframes(frames)
    samples = struct.unpack(f"<{len(data) // 2}h", data)
    total = sum(value * value for value in samples) / max(1, len(samples))
    return round(frames / rate, 2), round(math.sqrt(total) / 32768.0, 4)


def test_shaping_is_skipped_when_neutral():
    assert audio_fx.is_neutral(1.0, 1.0, 0.0)
    assert not audio_fx.is_neutral(1.5, 1.0, 0.0)
    assert not audio_fx.is_neutral(1.0, 1.2, 0.0)
    assert not audio_fx.is_neutral(1.0, 1.0, 2.0)


def test_volume_changes_loudness_without_changing_length():
    source = tone()
    base_duration, base_rms = stats(source)
    loud = __import__("asyncio").run(audio_fx.apply(source, volume=1.8))
    duration, rms = stats(loud)
    assert abs(duration - base_duration) < 0.05, (duration, base_duration)
    assert rms > base_rms * 1.4, (rms, base_rms)


def test_speed_changes_length_but_not_loudness():
    source = tone()
    base_duration, base_rms = stats(source)
    faster = __import__("asyncio").run(audio_fx.apply(source, speed=1.5))
    duration, rms = stats(faster)
    assert duration < base_duration * 0.8, (duration, base_duration)
    assert abs(rms - base_rms) < base_rms * 0.25, (rms, base_rms)


def test_pitch_keeps_length():
    source = tone()
    base_duration, _ = stats(source)
    shifted = __import__("asyncio").run(audio_fx.apply(source, pitch=5.0))
    duration, _ = stats(shifted)
    # Restoring duration is why pitch uses asetrate + atempo rather than atempo alone.
    assert abs(duration - base_duration) < 0.08, (duration, base_duration)


def test_ffmpeg_rejects_unknown_audio_gracefully():
    """Not a WAV: pass-through beats crashing the reply."""
    result = __import__("asyncio").run(audio_fx.apply(b"not audio", volume=1.5))
    assert result == b"not audio"


def test_voice_name_validation():
    assert voices.validate_name("  塔菲  ") == "塔菲"
    with pytest.raises(ProviderError):
        voices.validate_name("")
    with pytest.raises(ProviderError):
        voices.validate_name("a/b")
    with pytest.raises(ProviderError):
        voices.validate_name("x" * 40)


def test_resolve_refuses_paths_outside_project(tmp_path):
    outside = tmp_path / "outside.wav"
    outside.write_bytes(tone())
    assert voices.resolve(outside) is None
    assert voices.resolve("../secrets.wav") is None


def test_uploaded_clip_is_trimmed_and_compressed(monkeypatch, tmp_path):
    """The stored sample must shrink, because size is what made cloning slow."""
    monkeypatch.setattr(voices, "VOICE_DIR", tmp_path / "voice")
    monkeypatch.setattr(voices, "INDEX", tmp_path / "voices.json")
    # Two seconds of tone with silence padded on both ends.
    padded = tone(0.6)
    with wave.open(io.BytesIO(padded), "rb") as source:
        rate, frames = source.getframerate(), source.readframes(source.getnframes())
    silence = b"\x00\x00" * int(rate * 0.3)
    upload = io.BytesIO()
    with wave.open(upload, "wb") as sink:
        sink.setnchannels(1)
        sink.setsampwidth(2)
        sink.setframerate(rate)
        sink.writeframes(silence + frames + silence)
    raw = upload.getvalue()

    created = voices.process_upload(raw, "clip.wav", "测试音色")
    stored = tmp_path / "voice" / f"{created['id']}.mp3"
    assert stored.is_file()
    assert stored.stat().st_size < len(raw), (stored.stat().st_size, len(raw))
    listed = voices.public_list()
    assert [item["name"] for item in listed] == ["测试音色"]

    voices.delete(created["id"])
    assert voices.public_list() == []
    assert not stored.exists()
