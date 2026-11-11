"""Neutral greeting sources and parameter-specific local audio_fx derivatives."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import aclosing
from dataclasses import dataclass, replace
from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import uuid4

from . import audio_fx
from .config import ROOT

ACK_DIR = ROOT / "data" / "acks"
DERIVED_DIR = ROOT / "data" / "ack-derived"
FX_VERSION = "ack-pcm24-v1:" + sha256(Path(audio_fx.__file__).read_bytes()).hexdigest()
_MEMORY = OrderedDict()
_BUILD_LOCK = asyncio.Lock()


@dataclass(frozen=True)
class AckSource:
    index: int
    voice: str
    phrase: str
    pcm: bytes
    source_hash: str


@dataclass(frozen=True)
class AckAudio:
    pcm: bytes
    key: str
    metadata: dict
    cache_hit: bool


def load_sources(voice: str) -> list[AckSource]:
    manifest = json.loads((ACK_DIR / "manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("voice") != voice or manifest.get("sample_rate") != 24000
            or manifest.get("channels") != 1 or manifest.get("format") != "pcm_s16le"
            or manifest.get("neutral") is not True or manifest.get("audio_fx_applied") is not False):
        return []
    clips = []
    for entry in manifest.get("files", []):
        phrase = entry.get("normalized_input", entry.get("synthesis_text", entry.get("phrase", "")))
        name = entry.get("file", "")
        if entry.get("voice", voice) != voice or not phrase or any(symbol in phrase for symbol in ("~", "～")):
            continue
        if not name or Path(name).name != name:
            continue
        pcm = (ACK_DIR / name).read_bytes()
        if not pcm or len(pcm) % 2 or entry.get("bytes") != len(pcm):
            continue
        digest = sha256(pcm).hexdigest()
        if entry.get("sha256", digest) != digest:
            continue
        clips.append(AckSource(int(entry["index"]), voice, phrase, pcm, digest))
    return clips


def _identity(source: AckSource, rate: float, pitch: float) -> tuple[str, dict]:
    metadata = {
        "voice": source.voice, "normalized_input": source.phrase,
        "source_sha256": source.source_hash, "tts_rate": float(rate), "tts_pitch": float(pitch),
        "processing_version": FX_VERSION, "sample_rate": 24000, "channels": 1,
        "format": "pcm_s16le", "volume": 1.0,
    }
    key = sha256(json.dumps(metadata, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return key, metadata


def _read_derived(key: str, identity: dict) -> AckAudio | None:
    try:
        meta = json.loads((DERIVED_DIR / (key + ".json")).read_text(encoding="utf-8"))
        if any(meta.get(name) != value for name, value in identity.items()):
            return None
        pcm = (DERIVED_DIR / (key + ".pcm")).read_bytes()
        if (not pcm or len(pcm) % 2 or meta.get("bytes") != len(pcm)
                or meta.get("sha256") != sha256(pcm).hexdigest()):
            return None
        return AckAudio(pcm, key, meta, True)
    except (OSError, ValueError):
        return None


def _write_derived(audio: AckAudio):
    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    for suffix, content in ((".pcm", audio.pcm), (".json", json.dumps(
            audio.metadata, ensure_ascii=False, indent=2).encode("utf-8"))):
        target = (DERIVED_DIR / (audio.key + suffix)).resolve()
        if target.parent != DERIVED_DIR.resolve():
            raise ValueError("invalid_ack_cache_path")
        temporary = target.with_name(target.name + "." + uuid4().hex + ".tmp")
        try:
            temporary.write_bytes(content)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)


def _remember(audio: AckAudio) -> AckAudio:
    _MEMORY[audio.key] = audio
    _MEMORY.move_to_end(audio.key)
    while len(_MEMORY) > 56:
        _MEMORY.popitem(last=False)
    return audio


async def derive(source: AckSource, rate: float, pitch: float) -> AckAudio:
    key, identity = _identity(source, rate, pitch)
    if key in _MEMORY:
        _MEMORY.move_to_end(key)
        return replace(_MEMORY[key], cache_hit=True)
    async with _BUILD_LOCK:
        if key in _MEMORY:
            return replace(_MEMORY[key], cache_hit=True)
        cached = await asyncio.to_thread(_read_derived, key, identity)
        if cached is not None:
            return _remember(cached)
        if audio_fx.is_neutral(1.0, rate, pitch):
            pcm = source.pcm
        else:
            async def chunks():
                yield source.pcm
            async with aclosing(audio_fx.stream_pcm(chunks(), rate, pitch)) as stream:
                pcm = b"".join([chunk async for chunk in stream])
        if not pcm or len(pcm) % 2:
            raise ValueError("invalid_ack_derivative")
        metadata = dict(identity, bytes=len(pcm), sha256=sha256(pcm).hexdigest(),
                        source_seconds=len(source.pcm) / 48000, duration_seconds=len(pcm) / 48000,
                        filter_chain=audio_fx.build_filters(24000, 1.0, rate, pitch))
        audio = AckAudio(pcm, key, metadata, False)
        await asyncio.to_thread(_write_derived, audio)
        return _remember(audio)


async def warm(voice: str, rate: float, pitch: float) -> list[AckAudio]:
    sources = await asyncio.to_thread(load_sources, voice)
    return [await derive(source, rate, pitch) for source in sources]
