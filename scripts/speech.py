"""Download official local TTS packages and synthesize offline preview WAV files.

All model downloads, archives, and generated audio stay inside this project.
No model API keys, cloud speech calls, device changes, or automatic playback.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tarfile
import time
import urllib.request
import wave


ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models" / "tts"
ARCHIVES = ROOT / "models" / "downloads"
PREVIEWS = ROOT / "output" / "speech"
PACKAGES = {
    "kokoro": {
        "asset": "kokoro-int8-multi-lang-v1_0.tar.bz2",
        "bytes": 132303094,
        "license": "Apache-2.0",
    },
    "melo": {
        "asset": "vits-melo-tts-zh_en.tar.bz2",
        "bytes": 167006755,
        "license": "MIT",
    },
}
# Speaker IDs are for the v1_0 package, from sherpa-onnx's Kokoro documentation.
VOICES = {
    "xiaobei": 45, "xiaoni": 46, "xiaoxiao": 47, "xiaoyi": 48,
    "yunjian": 49, "yunxi": 50, "yunxia": 51, "yunyang": 52,
}
DEFAULT_TEXT = "你好，我是小蛋。这是本地语音测试，我们可以选择声音，也可以调整说话速度。"


def download(name: str) -> None:
    package = PACKAGES[name]
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    target = MODELS / name
    target.mkdir(parents=True, exist_ok=True)
    archive = ARCHIVES / str(package["asset"])
    expected = int(package["bytes"])
    if not archive.exists() or archive.stat().st_size != expected:
        partial = archive.with_suffix(archive.suffix + ".part")
        url = (
            "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
            + str(package["asset"])
        )
        request = urllib.request.Request(url, headers={"User-Agent": "AtomS3R-local-speech"})
        received = 0
        last_report = time.monotonic()
        with urllib.request.urlopen(request, timeout=30) as response, partial.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                received += len(chunk)
                if time.monotonic() - last_report >= 5:
                    print(f"{name}: {received / 1048576:.1f}/{expected / 1048576:.1f} MiB", flush=True)
                    last_report = time.monotonic()
        if received != expected:
            raise ValueError(f"{name}: incomplete or changed release asset ({received} != {expected})")
        partial.replace(archive)
    # Python 3.12's data filter blocks paths and links escaping this model directory.
    with tarfile.open(archive, "r:bz2") as source:
        source.extractall(target, filter="data")
    if len(list(target.rglob("*.onnx"))) != 1:
        raise ValueError(f"{name}: expected one ONNX model after extraction")
    print(f"{name}: downloaded and extracted to {target}; license {package['license']}", flush=True)


def preview(name: str, voice: str, speed: float, text: str, threads: int) -> None:
    import numpy as np
    import sherpa_onnx

    candidates = list((MODELS / name).rglob("*.onnx"))
    if len(candidates) != 1:
        raise ValueError(f"Run download --model {name} first")
    model = candidates[0]
    folder = model.parent
    if name == "kokoro":
        model_config = sherpa_onnx.OfflineTtsModelConfig(
            kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                model=str(model), voices=str(folder / "voices.bin"),
                tokens=str(folder / "tokens.txt"), data_dir=str(folder / "espeak-ng-data"),
                lexicon=",".join(str(folder / p) for p in ("lexicon-us-en.txt", "lexicon-zh.txt")),
            ),
            num_threads=threads, provider="cpu", debug=False,
        )
        sid = VOICES[voice]
        rules = [folder / "date-zh.fst", folder / "number-zh.fst"]
    else:
        model_config = sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=str(model), lexicon=str(folder / "lexicon.txt"),
                tokens=str(folder / "tokens.txt"), dict_dir=str(folder / "dict"),
            ),
            num_threads=threads, provider="cpu", debug=False,
        )
        sid = 0
        voice = "zh"
        rules = [folder / "date.fst", folder / "number.fst"]
    config = sherpa_onnx.OfflineTtsConfig(
        model=model_config,
        rule_fsts=",".join(str(p) for p in rules if p.is_file()),
        max_num_sentences=1,
    )
    if not config.validate():
        raise ValueError("Invalid TTS model configuration")
    start = time.perf_counter()
    engine = sherpa_onnx.OfflineTts(config)
    loaded = time.perf_counter()
    generation = sherpa_onnx.GenerationConfig()
    generation.sid = sid
    generation.speed = speed
    audio = engine.generate(text, generation)
    elapsed = time.perf_counter() - loaded
    samples = np.asarray(audio.samples, dtype=np.float32)
    if not len(samples) or not np.isfinite(samples).all() or float(np.max(np.abs(samples))) <= 0:
        raise ValueError("Generated audio is empty, invalid, or silent")
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    output = PREVIEWS / f"{name}-{voice}-{speed:g}x.wav"
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(output), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(audio.sample_rate)
        writer.writeframes(pcm.tobytes())
    duration = len(samples) / audio.sample_rate
    with wave.open(str(output), "rb") as check:
        if check.getnframes() != len(samples) or check.getsampwidth() != 2:
            raise ValueError("Output WAV validation failed")
    result = {
        "model": name, "voice": voice, "speed": speed,
        "output": str(output), "sample_rate": audio.sample_rate,
        "audio_seconds": round(duration, 3), "load_seconds": round(loaded - start, 3),
        "synthesis_seconds": round(elapsed, 3), "real_time_factor": round(elapsed / duration, 3),
    }
    output.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("download", "preview"))
    parser.add_argument("--model", choices=tuple(PACKAGES), default="kokoro")
    parser.add_argument("--voice", choices=tuple(VOICES), default="xiaobei")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--text", default=DEFAULT_TEXT)
    args = parser.parse_args()
    if not 0.5 <= args.speed <= 2.0:
        parser.error("speed must be between 0.5 and 2.0")
    if not 1 <= args.threads <= 8:
        parser.error("threads must be between 1 and 8")
    if args.action == "download":
        download(args.model)
    else:
        if not args.text.strip() or len(args.text) > 1000:
            parser.error("text must contain 1 to 1000 characters")
        preview(args.model, args.voice, args.speed, args.text, args.threads)


if __name__ == "__main__":
    main()
