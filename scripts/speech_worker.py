"""Persistent local speech worker: Opus decode, Silero VAD, SenseVoice, and Opus encode.

Runs inside .venv-speech, which is the only environment allowed to carry numpy/av/sherpa.
The gateway (.venv) talks to it over stdin/stdout so models load once per run.

Commands are one JSON line each; a response line follows every command. Commands that
carry audio are followed by exactly `size` raw bytes.

  {"cmd":"start","rate":24000,"mode":"auto"}  -> {"ok":true,"vad":true,"mode":"auto"}
  {"cmd":"frame","size":N} + N bytes          -> activity, or {"utterance":{...}}
  {"cmd":"stop"}                              -> {"utterance":{...}} or {"ok":true}
  {"cmd":"encode","path":"...wav"}            -> {"packets_template":"...","seconds":2.4}

Encoding is split into a temporary frame file so the reply never has to carry audio
through a JSON line; the caller reads the file.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import struct
import sys
import tempfile
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from asr_worker import (  # noqa: E402
    MAX_SPEECH_SECONDS, MODEL_DIR, TARGET_RATE, VAD_WINDOW, Utterance, build_vad,
    emit, finish, load_recognizer, read_exactly, recognize, resample,
)
from tts_opus import DEVICE_RATE, FRAME_MS, encode_wav, opus_available  # noqa: E402

MAX_FRAME_BYTES = 12000
# Uploaded browser recordings can be several MB of WAV.
MAX_WAV_BYTES = 20 * 1024 * 1024
ENCODE_DIR = ROOT / "output" / "tts-frames"


class PcmStreamer:
    """Encode a PCM16 stream to Opus frames as data arrives.

    Streaming TTS returns raw PCM in uneven chunks; Opus needs exact 60 ms frames, so
    partial frames are buffered here and only complete ones are emitted. This is what lets
    the device start speaking while the provider is still generating.
    """

    def __init__(self, rate: int = DEVICE_RATE, frame_ms: int = FRAME_MS):
        __import__("tts_opus", fromlist=["load_opus"]).load_opus()
        community_root = ROOT / "third_party" / "xiaozhi-server"
        if str(community_root) not in sys.path:
            sys.path.insert(0, str(community_root))
        from core.utils.opus_encoder_utils import OpusEncoderUtils
        self.encoder = OpusEncoderUtils(rate, 1, frame_ms)
        self.pending = b""

    def reset(self) -> None:
        """Drop any partial frame so the next sentence starts clean."""
        self.encoder.reset_state()
        self.pending = b""

    def feed(self, chunk: bytes) -> list[bytes]:
        raw = self.pending + chunk
        size = len(raw) // 2 * 2
        self.pending = raw[size:]
        packets: list[bytes] = []
        self.encoder.encode_pcm_to_opus_stream(raw[:size], False, packets.append)
        return packets

    def flush(self) -> list[bytes]:
        if self.pending:
            raise ValueError("incomplete_pcm_sample")
        packets = []
        self.encoder.encode_pcm_to_opus_stream(b"", True, packets.append)
        return packets


def handle_recognize_wav(command: dict, recognizer) -> dict:
    """Transcribe a WAV blob sent from the browser.

    The browser records whatever the microphone gives it (often 44.1 or 48 kHz), so the
    audio is resampled to the 16 kHz the model expects before recognition.
    """
    size = command.get("size")
    if not isinstance(size, int) or not 0 < size <= MAX_WAV_BYTES:
        return {"error": "invalid_wav_size"}
    raw = read_exactly(sys.stdin.buffer, size)
    try:
        import io
        import wave

        with wave.open(io.BytesIO(raw), "rb") as source:
            channels = source.getnchannels()
            rate = source.getframerate()
            width = source.getsampwidth()
            frames = source.readframes(source.getnframes())
    except (wave.Error, EOFError, OSError):
        return {"error": "invalid_wav"}
    if width != 2:
        return {"error": "unsupported_width"}
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if not len(samples):
        return {"error": "empty_audio"}
    started = time.perf_counter()
    samples = resample(samples, rate, TARGET_RATE)
    stream = recognizer.create_stream()
    stream.accept_waveform(TARGET_RATE, samples)
    recognizer.decode_stream(stream)
    elapsed = time.perf_counter() - started
    audio_seconds = len(samples) / TARGET_RATE
    return {"text": stream.result.text.strip(),
            "audio_seconds": round(audio_seconds, 3),
            "decode_seconds": round(elapsed, 3),
            "real_time_factor": round(elapsed / audio_seconds, 4) if audio_seconds else None}


def handle_encode(command: dict) -> dict:
    source = command.get("path")
    if not isinstance(source, str) or not source:
        return {"error": "invalid_path"}
    path = Path(source)
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        return {"error": "file_missing"}
    packets = encode_wav(path, rate=DEVICE_RATE, frame_ms=FRAME_MS)
    if not packets:
        return {"error": "empty_audio"}
    ENCODE_DIR.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("wb", dir=ENCODE_DIR, prefix="reply-",
                                         suffix=".opusframes", delete=False)
    try:
        for packet in packets:
            handle.write(struct.pack("<I", len(packet)))
            handle.write(packet)
        handle.flush()
        target = Path(handle.name)
    finally:
        handle.close()
    return {"packets": len(packets), "frame_ms": FRAME_MS, "rate": DEVICE_RATE,
            "seconds": round(len(packets) * FRAME_MS / 1000, 3),
            "mean_bytes": round(float(np.mean([len(p) for p in packets])), 1),
            "frames_path": str(target)}


def handle(command: dict, state: dict, recognizer, vad) -> dict:
    name = command.get("cmd")
    if name == "start":
        rate = command.get("rate", DEVICE_RATE)
        mode = command.get("mode", "auto")
        if not isinstance(rate, int) or not 8000 <= rate <= 48000:
            return {"error": "invalid_rate"}
        if mode not in ("auto", "manual"):
            return {"error": "invalid_mode"}
        if mode == "auto":
            if state.get("vad") is None:
                try:
                    state["vad"] = build_vad()
                except ModuleNotFoundError:
                    return {"error": "community_vad_dependencies_missing"}
            vad = state["vad"]
        else:
            vad = None
        state["utterance"] = Utterance(mode, vad)
        return {"ok": True, "vad": vad is not None, "mode": mode}
    if name == "frame":
        current: Utterance | None = state.get("utterance")
        if current is None:
            return {"error": "no_stream"}
        size = command.get("size")
        if not isinstance(size, int) or not 0 < size <= MAX_FRAME_BYTES:
            return {"error": "invalid_frame_size"}
        payload = read_exactly(sys.stdin.buffer, size)
        ended = current.feed(payload)
        if ended is None:
            return {"ok": True, "voice": current.vad_state.client_have_voice}
        return finish(recognizer, current, ended["end_reason"])
    if name == "stop":
        current = state.get("utterance")
        state["utterance"] = None
        if current is None:
            return {"ok": True}
        # Nothing but room noise must never become a sentence.
        if not current.saw_voice and current.mode == "auto":
            current.reset()
            return {"ok": True, "discarded": True}
        return finish(recognizer, current, "stop")
    if name == "encode":
        return handle_encode(command)
    if name == "recognize_wav":
        # Browser uploads arrive as a WAV file rather than Opus frames.
        return handle_recognize_wav(command, recognizer)
    if name == "pcm_start":
        # Begin a streaming encode: PCM arrives in pieces and is emitted as Opus frames.
        # The encoder is created once per worker so starting a sentence is cheap.
        streamer = state.get("pcm_encoder")
        if streamer is None:
            streamer = PcmStreamer()
            state["pcm_encoder"] = streamer
        streamer.reset()
        state["pcm"] = streamer
        return {"ok": True, "frame_ms": FRAME_MS, "rate": DEVICE_RATE}
    if name == "pcm":
        streamer: PcmStreamer | None = state.get("pcm")
        if streamer is None:
            return {"error": "no_pcm_stream"}
        size = command.get("size")
        if not isinstance(size, int) or not 0 < size <= MAX_FRAME_BYTES * 8:
            return {"error": "invalid_pcm_size"}
        chunk = read_exactly(sys.stdin.buffer, size)
        packets = streamer.feed(chunk)
        # Opus packets are bytes; the protocol is JSON lines, so they travel as base64.
        return {"packets": [base64.b64encode(p).decode("ascii") for p in packets]}
    if name == "pcm_end":
        streamer = state.pop("pcm", None)
        if streamer is None:
            return {"packets": []}
        return {"packets": [base64.b64encode(p).decode("ascii") for p in streamer.flush()]}
    if name == "ping":
        return {"ok": True}
    return {"error": "unknown_command"}


def main() -> None:
    threads = int(sys.argv[sys.argv.index("--threads") + 1]) if "--threads" in sys.argv else 2
    language = sys.argv[sys.argv.index("--language") + 1] if "--language" in sys.argv else "zh"
    for name in ("model.int8.onnx", "tokens.txt"):
        if not (MODEL_DIR / name).is_file():
            emit({"fatal": f"missing model file: {name}"})
            return
    recognizer = load_recognizer(threads, language)
    vad = None
    emit({"ready": True, "vad": False,
          "encode": opus_available()})
    state: dict = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return
        try:
            command = json.loads(line)
            result = handle(command, state, recognizer, vad)
        except EOFError:
            return
        except Exception as error:
            result = {"error": type(error).__name__}
        emit(result)


if __name__ == "__main__":
    main()
