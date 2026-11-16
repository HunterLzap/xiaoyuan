"""Shared libopus codec and lightweight PCM/WAV utilities."""
from __future__ import annotations

import ctypes as c
from ctypes.util import find_library
from io import BytesIO
from array import array
from math import sqrt
import os
import wave

from .config import ROOT


def pcm_rms(pcm: bytes) -> float:
    """Compute root-mean-square amplitude of little-endian signed PCM16."""
    usable = len(pcm) - (len(pcm) % 2)
    if usable <= 0:
        return 0.0
    samples = array("h")
    samples.frombytes(pcm[:usable])
    if not samples:
        return 0.0
    return sqrt(sum(sample * sample for sample in samples) / len(samples))


def pcm_to_wav(pcm: bytes, sample_rate: int = 16000, channels: int = 1) -> bytes:
    """Wrap raw little-endian PCM16 bytes in a RIFF WAV container."""
    buffer = BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm)
    return buffer.getvalue()


def strip_wav_header(raw: bytes) -> tuple[bytes, int, int] | None:
    """Extract PCM16 frames, sample rate, and channels from a WAV payload if valid."""
    if not raw.startswith(b"RIFF"):
        return None
    try:
        with wave.open(BytesIO(raw), "rb") as audio_file:
            if audio_file.getsampwidth() != 2:
                return None
            rate = audio_file.getframerate()
            channels = audio_file.getnchannels()
            frames = audio_file.readframes(audio_file.getnframes())
            return frames, rate, channels
    except (wave.Error, EOFError):
        return None


def resample_pcm16_mono(pcm: bytes, src_rate: int, dst_rate: int, channels: int = 1) -> bytes:
    """Convert PCM16 to mono at dst_rate using linear interpolation when rates differ."""
    if not pcm or (src_rate == dst_rate and channels == 1):
        return pcm
    samples = array("h")
    usable = len(pcm) - (len(pcm) % (2 * max(1, channels)))
    if usable <= 0:
        return b""
    samples.frombytes(pcm[:usable])
    if channels > 1:
        mono = array("h")
        for idx in range(0, len(samples), channels):
            mono.append(sum(samples[idx:idx + channels]) // channels)
        samples = mono
    if src_rate == dst_rate or not samples:
        return samples.tobytes()
    out_len = max(1, int(round(len(samples) * dst_rate / src_rate)))
    out = array("h")
    last = len(samples) - 1
    for i in range(out_len):
        pos = i * (src_rate / dst_rate)
        lo = min(int(pos), last)
        hi = min(lo + 1, last)
        frac = pos - lo
        val = samples[lo] * (1.0 - frac) + samples[hi] * frac
        out.append(max(-32768, min(32767, int(round(val)))))
    return out.tobytes()


class DeviceCodec:
    """In-process 16 kHz Opus decoder and 24 kHz Opus encoder using libopus."""

    def __init__(self, *, decode: bool = True, encode: bool = True):
        self.decoder = self.encoder = None
        name = str(ROOT / "models" / "codecs" / "opus.dll") if os.name == "nt" else find_library("opus")
        if not name:
            raise RuntimeError("libopus unavailable")
        self.lib = c.CDLL(name)
        p, i = c.c_void_p, c.c_int
        for fn, args, ret in (
            ("opus_decoder_create", [i, i, c.POINTER(i)], p),
            ("opus_encoder_create", [i, i, i, c.POINTER(i)], p),
            ("opus_decode", [p, c.c_char_p, i, p, i, i], i),
            ("opus_encode", [p, c.c_char_p, i, p, i], i),
            ("opus_decoder_destroy", [p], None),
            ("opus_encoder_destroy", [p], None),
        ):
            method = getattr(self.lib, fn)
            method.argtypes, method.restype = args, ret
        err = i()
        if decode:
            self.decoder = self.lib.opus_decoder_create(16000, 1, c.byref(err))
            if not self.decoder:
                self.close()
                raise RuntimeError("opus init failed")
        if encode:
            self.encoder = self.lib.opus_encoder_create(24000, 1, 2049, c.byref(err))
            if not self.encoder:
                self.close()
                raise RuntimeError("opus init failed")
        self.pending = bytearray()

    def decode(self, data: bytes) -> bytes:
        if not self.decoder:
            raise RuntimeError("opus decoder disabled")
        out = c.create_string_buffer(3840)
        size = self.lib.opus_decode(self.decoder, data, len(data), out, 1920, 0)
        if size < 0:
            raise ValueError("invalid opus frame")
        return out.raw[:2 * size]

    def encode(self, data: bytes, finish: bool = False):
        if not self.encoder:
            raise RuntimeError("opus encoder disabled")
        self.pending.extend(data)
        frame = 2880
        if finish:
            self.pending.extend(bytes((-len(self.pending)) % frame))
        while len(self.pending) >= frame:
            out = c.create_string_buffer(4096)
            size = self.lib.opus_encode(self.encoder, bytes(self.pending[:frame]), 1440, out, len(out))
            if size < 0:
                raise ValueError("opus encode failed")
            del self.pending[:frame]
            yield out.raw[:size]

    def close(self) -> None:
        if self.decoder:
            self.lib.opus_decoder_destroy(self.decoder)
            self.decoder = None
        if self.encoder:
            self.lib.opus_encoder_destroy(self.encoder)
            self.encoder = None
