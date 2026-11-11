"""Opus round-trip check for the device microphone path.

Encodes a local WAV into the same shape the device speaks (mono Opus frames), replays
those frames through a decoder exactly like the gateway will, and runs the local
SenseVoice model on the decoded audio. Entirely offline: no API key, no device, no network.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asr import MODEL_DIR, TARGET_RATE, read_wav, resample  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WAV = ROOT / "output" / "speech" / "kokoro-xiaobei-1x.wav"
DEFAULT_STREAM = ROOT / "output" / "speech" / "device-sim.opusframes"
DEFAULT_OGG = ROOT / "output" / "speech" / "device-sim.opus"
DEVICE_RATE = 24000
DEVICE_FRAME_MS = 60


def load_mono(path: Path, rate: int) -> np.ndarray:
    samples, source_rate = read_wav(path)
    return resample(samples, source_rate, rate)


def encode_frames(samples: np.ndarray, rate: int, frame_ms: int, bitrate: int) -> list[bytes]:
    import av

    frame_size = rate * frame_ms // 1000
    encoder = av.CodecContext.create("libopus", "w")
    encoder.sample_rate = rate
    encoder.layout = "mono"
    encoder.format = "s16"
    encoder.bit_rate = bitrate
    frames: list[bytes] = []
    for start in range(0, len(samples) - frame_size + 1, frame_size):
        chunk = samples[start:start + frame_size]
        frame = av.AudioFrame(format="s16", layout="mono", samples=frame_size)
        frame.sample_rate = rate
        frame.planes[0].update(np.clip(chunk * 32768.0, -32768, 32767).astype("<i2").tobytes())
        for packet in encoder.encode(frame):
            frames.append(bytes(packet))
    for packet in encoder.encode(None):
        frames.append(bytes(packet))
    return frames


def write_frame_stream(path: Path, frames: list[bytes]) -> None:
    """Length-prefixed frames: the same boundaries a WebSocket binary message gives us."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as sink:
        for frame in frames:
            sink.write(struct.pack("<I", len(frame)))
            sink.write(frame)


def read_frame_stream(path: Path) -> list[bytes]:
    frames: list[bytes] = []
    with path.open("rb") as source:
        while True:
            header = source.read(4)
            if not header:
                break
            (size,) = struct.unpack("<I", header)
            payload = source.read(size)
            if len(payload) != size:
                raise ValueError(f"帧数据被截断：{path}")
            frames.append(payload)
    return frames


def decode_frames(frames: list[bytes], rate: int) -> np.ndarray:
    """Decode device-style Opus packets to mono s16 at `rate`.

    libopus always decodes at 48 kHz internally and ignores a requested decoder rate,
    so the resampler is not optional: without it a 24 kHz stream comes back at 48 kHz
    and every downstream duration doubles.
    """
    import av

    decoder = av.CodecContext.create("libopus", "r")
    decoder.sample_rate = rate
    decoder.layout = "mono"
    decoder.format = "s16"
    resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
    chunks: list[np.ndarray] = []

    def collect(produced) -> None:
        if produced is None:
            return
        for frame in ([produced] if not isinstance(produced, (list, tuple)) else produced):
            buffer = frame.to_ndarray()
            if buffer.ndim > 1:
                buffer = buffer.reshape(-1, buffer.shape[-1])[0]
            chunks.append(buffer.astype(np.float32) / 32768.0)

    for payload in frames:
        for frame in decoder.decode(av.Packet(payload)):
            collect(resampler.resample(frame))
    collect(resampler.resample(None))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks)


def mux_ogg(path: Path, frames: list[bytes], rate: int, frame_ms: int) -> None:
    import av

    path.parent.mkdir(parents=True, exist_ok=True)
    container = av.open(str(path), "w")
    stream = container.add_stream("libopus", rate=rate)
    stream.layout = "mono"
    frame_size = rate * frame_ms // 1000
    pcm = decode_frames(frames, rate)
    for index, start in enumerate(range(0, len(pcm) - frame_size + 1, frame_size)):
        chunk = pcm[start:start + frame_size]
        frame = av.AudioFrame(format="s16", layout="mono", samples=frame_size)
        frame.sample_rate = rate
        frame.pts = index * frame_size
        frame.planes[0].update(np.clip(chunk * 32768.0, -32768, 32767).astype("<i2").tobytes())
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode(None):
        container.mux(packet)
    container.close()


def align_and_score(reference: np.ndarray, decoded: np.ndarray, search: int = 480) -> dict:
    """Delay-compensated comparison; Opus adds a short codec delay."""
    size = min(len(reference), len(decoded))
    if size == 0:
        return {"samples": 0}
    reference = reference[:size]
    decoded = decoded[:size]
    window = min(size, 8000)
    best_lag, best_score = 0, -1.0
    for lag in range(-search, search + 1):
        left = reference[max(0, lag):window + max(0, lag)]
        right = decoded[max(0, -lag):window + max(0, -lag)]
        length = min(len(left), len(right))
        if length < window // 2:
            continue
        score = float(np.dot(left[:length], right[:length]) /
                      (np.linalg.norm(left[:length]) * np.linalg.norm(right[:length]) + 1e-9))
        if score > best_score:
            best_lag, best_score = lag, score
    if best_lag >= 0:
        reference_aligned, decoded_aligned = reference[best_lag:], decoded
    else:
        reference_aligned, decoded_aligned = reference, decoded[-best_lag:]
    length = min(len(reference_aligned), len(decoded_aligned))
    reference_aligned = reference_aligned[:length]
    decoded_aligned = decoded_aligned[:length]
    noise = reference_aligned - decoded_aligned
    signal_power = float(np.mean(reference_aligned ** 2) + 1e-12)
    noise_power = float(np.mean(noise ** 2) + 1e-12)
    return {
        "samples": length,
        "lag_samples": best_lag,
        "correlation": round(best_score, 4),
        "snr_db": round(10.0 * np.log10(signal_power / noise_power), 2),
    }


def ffmpeg_decode(path: Path, rate: int) -> np.ndarray | None:
    """Independent decoder for cross-checking PyAV; skipped when ffmpeg is unavailable."""
    try:
        completed = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-acodec", "pcm_s16le",
             "-ac", "1", "-ar", str(rate), "-"],
            capture_output=True, check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return np.frombuffer(completed.stdout, dtype="<i2").astype(np.float32) / 32768.0


def recognize(samples: np.ndarray, rate: int, threads: int, language: str, itn: bool) -> dict:
    import sherpa_onnx

    model = MODEL_DIR / "model.int8.onnx"
    tokens = MODEL_DIR / "tokens.txt"
    for path in (model, tokens):
        if not path.is_file():
            sys.exit(f"缺少模型文件：{path}（先下载 SenseVoice 模型）")
    samples16k = resample(samples, rate, TARGET_RATE)
    started = time.perf_counter()
    recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(model), tokens=str(tokens), num_threads=threads,
        use_itn=itn, language=language, debug=False,
    )
    loaded = time.perf_counter()
    stream = recognizer.create_stream()
    stream.accept_waveform(TARGET_RATE, samples16k)
    recognizer.decode_stream(stream)
    finished = time.perf_counter()
    audio_seconds = len(samples16k) / TARGET_RATE
    decode_seconds = finished - loaded
    return {
        "load_seconds": round(loaded - started, 3),
        "decode_seconds": round(decode_seconds, 3),
        "audio_seconds": round(audio_seconds, 3),
        "real_time_factor": round(decode_seconds / audio_seconds, 3) if audio_seconds else None,
        "text": stream.result.text.strip(),
    }


def write_wav(path: Path, samples: np.ndarray, rate: int) -> None:
    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as sink:
        sink.setnchannels(1)
        sink.setsampwidth(2)
        sink.setframerate(rate)
        sink.writeframes(np.clip(samples * 32768.0, -32768, 32767).astype("<i2").tobytes())


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wav", type=Path, default=DEFAULT_WAV)
    parser.add_argument("--stream", type=Path, default=DEFAULT_STREAM)
    parser.add_argument("--ogg", type=Path, default=DEFAULT_OGG)
    parser.add_argument("--decoded-wav", type=Path, default=None)
    parser.add_argument("--rate", type=int, default=DEVICE_RATE)
    parser.add_argument("--frame-ms", type=int, default=DEVICE_FRAME_MS)
    parser.add_argument("--bitrate", type=int, default=24000)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--language", default="zh")
    parser.add_argument("--itn", action="store_true", help="启用数字/标点规整（实测会误转同音字，默认关闭）")
    args = parser.parse_args()
    if args.frame_ms not in (10, 20, 40, 60):
        parser.error("frame-ms 只支持 10/20/40/60")
    if not args.wav.is_file():
        parser.error(f"找不到音频文件：{args.wav}")

    source_rate = read_wav(args.wav)[1]
    samples = load_mono(args.wav, args.rate)
    frame_size = args.rate * args.frame_ms // 1000
    if len(samples) < frame_size:
        sys.exit("音频短于一个 Opus 帧")

    encoded = time.perf_counter()
    frames = encode_frames(samples, args.rate, args.frame_ms, args.bitrate)
    encode_seconds = time.perf_counter() - encoded
    write_frame_stream(args.stream, frames)

    replay = read_frame_stream(args.stream)
    started = time.perf_counter()
    decoded = decode_frames(replay, args.rate)
    decode_seconds = time.perf_counter() - started

    mux_ogg(args.ogg, frames, args.rate, args.frame_ms)
    independent = ffmpeg_decode(args.ogg, args.rate)
    cross = None
    if independent is not None:
        shared = min(len(independent), len(decoded))
        cross = {
            "ffmpeg_samples": int(len(independent)),
            "correlation": round(float(np.dot(independent[:shared], decoded[:shared]) /
                                        (np.linalg.norm(independent[:shared]) * np.linalg.norm(decoded[:shared]) + 1e-9)), 4),
        }

    if args.decoded_wav:
        write_wav(args.decoded_wav, decoded, args.rate)

    result = {
        "wav": str(args.wav),
        "source_rate": source_rate,
        "encode": {"frame_ms": args.frame_ms, "bitrate": args.bitrate, "frames": len(frames),
                   "mean_frame_bytes": round(float(np.mean([len(f) for f in frames])), 1),
                   "seconds": round(encode_seconds, 3)},
        "decode": {"seconds": round(decode_seconds, 3),
                   "decoded_seconds": round(len(decoded) / args.rate, 3),
                   "realtime_factor": round(decode_seconds / (len(decoded) / args.rate), 4) if len(decoded) else None},
        "fidelity_vs_original": align_and_score(samples, decoded),
        "ffmpeg_crosscheck": cross,
        "asr": recognize(decoded, args.rate, args.threads, args.language, args.itn),
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
