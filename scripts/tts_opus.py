"""Encode synthesized speech into device-ready Opus frames.

The gateway runs in .venv, which has no audio bindings, so encoding lives here and is
invoked by the speech worker process in .venv-speech. Frame shape must match what the
device streams upward: mono, 24 kHz, 60 ms per packet. opuslib_next is the same binding
the reference xiaozhi server uses; PyAV's libopus wrapper does not produce one packet per
call and was abandoned after it tripled every duration.
"""
from __future__ import annotations

import os
from ctypes.util import find_library
from pathlib import Path
import sys
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OPUS_DLL_DIR = ROOT / "models" / "codecs"
FRAME_MS = 60
# The device negotiates 24 kHz in its hello; its decoder expects that rate on the way back.
DEVICE_RATE = 24000


def opus_available() -> bool:
    return (OPUS_DLL_DIR / "opus.dll").is_file() if os.name == "nt" else bool(find_library("opus"))


def load_opus():
    """Import opuslib_next with the bundled libopus DLL made visible."""
    if os.name == "nt":
        directory = str(OPUS_DLL_DIR)
        if directory not in os.environ.get("PATH", ""):
            os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(directory)
    import opuslib_next

    return opuslib_next


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as source:
        if source.getsampwidth() != 2:
            raise ValueError("only 16-bit PCM WAV is supported")
        channels = source.getnchannels()
        rate = source.getframerate()
        frames = source.readframes(source.getnframes())
    samples = np.frombuffer(frames, dtype="<i2")
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1).astype("<i2")
    return samples, rate


def resample(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate or not len(samples):
        return samples
    duration = len(samples) / source_rate
    count = max(1, int(round(duration * target_rate)))
    axis_old = np.linspace(0.0, duration, len(samples), endpoint=False)
    axis_new = np.linspace(0.0, duration, count, endpoint=False)
    return np.interp(axis_new, axis_old, samples.astype(np.float32)).astype("<i2")


def encode_wav(path: Path, rate: int = DEVICE_RATE, frame_ms: int = FRAME_MS) -> list[bytes]:
    """Return one Opus packet per frame_ms slice; the last frame is zero-padded."""
    opuslib = load_opus()
    samples, source_rate = read_wav(path)
    samples = resample(samples, source_rate, rate)
    frame_size = rate * frame_ms // 1000
    encoder = opuslib.Encoder(rate, 1, opuslib.APPLICATION_AUDIO)
    packets: list[bytes] = []
    for start in range(0, len(samples), frame_size):
        chunk = samples[start:start + frame_size]
        if len(chunk) < frame_size:
            chunk = np.pad(chunk, (0, frame_size - len(chunk)))
        packets.append(encoder.encode(chunk.tobytes(), frame_size))
    return packets


def decode_packets(packets: list[bytes], rate: int = DEVICE_RATE, frame_ms: int = FRAME_MS) -> np.ndarray:
    """Decode back for verification; proves the packets are well formed."""
    opuslib = load_opus()
    frame_size = rate * frame_ms // 1000
    decoder = opuslib.Decoder(rate, 1)
    pieces = [np.frombuffer(decoder.decode(packet, frame_size), dtype="<i2") for packet in packets]
    if not pieces:
        return np.zeros(0, dtype="<i2")
    return np.concatenate(pieces)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        print("usage: tts_opus.py <wav> [--frames-out FILE]")
        return
    import json

    path = Path(sys.argv[1])
    packets = encode_wav(path)
    back = decode_packets(packets)
    rates = load_opus()
    result = {"wav": str(path), "packets": len(packets),
              "seconds": round(len(back) / DEVICE_RATE, 3),
              "frame_ms": FRAME_MS, "rate": DEVICE_RATE,
              "mean_bytes": round(float(np.mean([len(p) for p in packets])), 1) if packets else 0}
    if "--frames-out" in sys.argv:
        import struct

        target = Path(sys.argv[sys.argv.index("--frames-out") + 1])
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as sink:
            for packet in packets:
                sink.write(struct.pack("<I", len(packet)) + packet)
        result["frames_out"] = str(target)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
