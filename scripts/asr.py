"""Transcribe a WAV file with the local SenseVoice model.

Runs entirely offline against models/asr/sensevoice; no API key, no device, no network.
Reports wall-clock cost and real-time factor so the 2-core deployment budget can be judged.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models" / "asr" / "sensevoice"
DEFAULT_WAV = ROOT / "output" / "speech" / "kokoro-xiaobei-1x.wav"
TARGET_RATE = 16000


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as source:
        if source.getsampwidth() != 2:
            raise ValueError("仅支持 16-bit PCM WAV")
        channels = source.getnchannels()
        rate = source.getframerate()
        frames = source.readframes(source.getnframes())
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, rate


def resample(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate:
        return samples
    duration = len(samples) / source_rate
    count = int(round(duration * target_rate))
    old_axis = np.linspace(0.0, duration, len(samples), endpoint=False)
    new_axis = np.linspace(0.0, duration, count, endpoint=False)
    return np.interp(new_axis, old_axis, samples).astype(np.float32)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wav", type=Path, default=DEFAULT_WAV)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--language", default="zh")
    parser.add_argument("--itn", action="store_true", help="启用数字/标点规整（实测会误转同音字，默认关闭）")
    args = parser.parse_args()
    if not 1 <= args.threads <= 8:
        parser.error("threads must be between 1 and 8")
    if not args.wav.is_file():
        parser.error(f"找不到音频文件：{args.wav}")

    model = MODEL_DIR / "model.int8.onnx"
    tokens = MODEL_DIR / "tokens.txt"
    for path in (model, tokens):
        if not path.is_file():
            sys.exit(f"缺少模型文件：{path}（先下载 SenseVoice 模型）")

    samples, rate = read_wav(args.wav)
    if not len(samples):
        sys.exit("音频为空")
    audio_seconds = len(samples) / rate
    samples = resample(samples, rate, TARGET_RATE)

    started = time.perf_counter()
    recognizer = sherpa_onnx_recognizer(model, tokens, args.threads, args.language, args.itn)
    loaded = time.perf_counter()
    stream = recognizer.create_stream()
    stream.accept_waveform(TARGET_RATE, samples)
    recognizer.decode_stream(stream)
    finished = time.perf_counter()

    text = stream.result.text.strip()
    decode_seconds = finished - loaded
    result = {
        "wav": str(args.wav),
        "source_rate": rate,
        "audio_seconds": round(audio_seconds, 3),
        "load_seconds": round(loaded - started, 3),
        "decode_seconds": round(decode_seconds, 3),
        "real_time_factor": round(decode_seconds / audio_seconds, 3) if audio_seconds else None,
        "threads": args.threads,
        "itn": args.itn,
        "text": text,
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)


def sherpa_onnx_recognizer(model: Path, tokens: Path, threads: int, language: str, itn: bool):
    import sherpa_onnx

    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(model), tokens=str(tokens), num_threads=threads,
        use_itn=itn, language=language, debug=False,
    )


if __name__ == "__main__":
    main()
