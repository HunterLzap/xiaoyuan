"""Persistent streaming voice-activity + recognition worker for the device gateway.

The web service runs in .venv and must not carry numpy/av/sherpa; this process stays in
.venv-speech and loads SenseVoice and Silero VAD once per gateway run.

End-of-utterance detection follows the xiaozhi-esp32-server reference implementation:
decode Opus to PCM, feed fixed 512-sample windows to Silero VAD, and treat a run of
trailing silence as the end of the sentence. The firmware never sends listen/stop on its
own, and manual mode must not use VAD at all, so mode is decided by the caller.

Line protocol over stdin/stdout, one response line per request:

  {"cmd": "start", "rate": 24000, "mode": "auto"} -> {"ok": true}
  {"cmd": "frame", "size": N} + N bytes           -> activity, or {"utterance": {...}}
  {"cmd": "stop"}                                 -> {"utterance": {...}} or {"ok": true}
"""
from __future__ import annotations

import json
import os
from collections import deque
from pathlib import Path
import struct
import sys
import time
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = Path(os.environ.get("AI_ASR_MODEL_DIR") or ROOT / "models" / "asr" / "sensevoice")
if not MODEL_DIR.is_absolute():
    MODEL_DIR = ROOT / MODEL_DIR
COMMUNITY_ROOT = ROOT / "third_party" / "xiaozhi-server"
TARGET_RATE = 16000
VAD_WINDOW = 512
MAX_FRAME_BYTES = 12000
VAD_THRESHOLD = 0.5
MIN_SILENCE_SECONDS = 0.5
MAX_SPEECH_SECONDS = 20.0
# Audio kept from before speech is confirmed, so the first syllable is not clipped.
PREROLL_SECONDS = 0.6


def emit(payload: dict) -> None:
    # Windows defaults stdout to the locale code page; the protocol is UTF-8 bytes.
    sys.stdout.buffer.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def read_exactly(stream, size: int) -> bytes:
    chunks, remaining = [], size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise EOFError("stdin closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def load_recognizer(threads: int, language: str):
    import sherpa_onnx

    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(MODEL_DIR / "model.int8.onnx"), tokens=str(MODEL_DIR / "tokens.txt"),
        num_threads=threads, use_itn=False, language=language, debug=False,
    )


def build_vad():
    if str(COMMUNITY_ROOT) not in sys.path:
        sys.path.insert(0, str(COMMUNITY_ROOT))
    from core.providers.vad.silero import VADProvider

    return VADProvider({
        "model_dir": str(COMMUNITY_ROOT / "models" / "snakers4_silero-vad"),
        "threshold": VAD_THRESHOLD, "threshold_low": 0.2,
        "min_silence_duration_ms": int(MIN_SILENCE_SECONDS * 1000),
    })


def vad_state(mode: str):
    return SimpleNamespace(
        client_listen_mode=mode, client_audio_buffer=bytearray(),
        client_voice_window=deque(maxlen=5), last_is_voice=False,
        client_have_voice=False, client_voice_stop=False, vad_last_voice_time=0,
    )


class OpusDecoder:
    """Decode device Opus packets and resample to 16 kHz mono float32.

    libopus must decode at its native 48 kHz. Setting the decoder's sample_rate to 16000
    corrupts frame boundaries (an 11.1s stream then measures 33.4s, exactly 3x), which
    silently starves the VAD and breaks every duration downstream. Resample afterwards.
    """

    def __init__(self):
        import av

        self.context = av.CodecContext.create("libopus", "r")
        self.context.layout = "mono"
        self.context.format = "s16"

    def decode(self, packet: bytes) -> np.ndarray:
        import av

        pieces = []
        for frame in self.context.decode(av.Packet(packet)):
            buffer = frame.to_ndarray()
            if buffer.ndim > 1:
                buffer = buffer.reshape(-1, buffer.shape[-1])[0]
            pieces.append(buffer.astype(np.float32) / 32768.0)
        if not pieces:
            return np.zeros(0, dtype=np.float32)
        samples = np.concatenate(pieces)
        rate = self.context.sample_rate or 48000
        return resample(samples, rate, TARGET_RATE)


def resample(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate or not len(samples):
        return samples
    duration = len(samples) / source_rate
    count = max(1, int(round(duration * target_rate)))
    return np.interp(np.linspace(0.0, duration, count, endpoint=False),
                     np.linspace(0.0, duration, len(samples), endpoint=False),
                     samples).astype(np.float32)


class Utterance:
    """Collect one sentence: PCM for the recognizer plus the VAD verdict on when it ended."""

    def __init__(self, mode: str, vad):
        self.mode = mode
        self.vad = vad
        self.vad_state = vad_state(mode)
        self.decoder = OpusDecoder()
        self.chunks: list[np.ndarray] = []
        self.pending = np.zeros(0, dtype=np.float32)
        self.total_seconds = 0.0
        self.speech_seconds = 0.0
        self.last_voice_at: float | None = None
        self.saw_voice = False
        # Keep only the tail of audio heard before speech starts, so the first syllable
        # (which the VAD confirms slightly late) is not clipped when recording begins.
        self.rolled: list[np.ndarray] = []
        self.rolled_seconds = 0.0

    def feed(self, packet: bytes) -> dict | None:
        samples = self.decoder.decode(packet)
        if not len(samples):
            return None
        if self.mode == "manual":
            # Manual mode buffers everything and waits for the explicit stop.
            self.chunks.append(samples)
            self.total_seconds += len(samples) / TARGET_RATE
            if self.total_seconds >= MAX_SPEECH_SECONDS:
                return {"end_reason": "max_length"}
            return None
        self.pending = np.concatenate([self.pending, samples])
        while len(self.pending) >= VAD_WINDOW:
            window, self.pending = self.pending[:VAD_WINDOW], self.pending[VAD_WINDOW:]
            have_voice = self.vad.is_vad(
                self.vad_state, (np.clip(window, -1, 1) * 32767).astype("<i2").tobytes())
            if have_voice:
                self.speech_seconds += len(window) / TARGET_RATE
                self.last_voice_at = self.total_seconds
            if not self.saw_voice:
                # Nothing said yet: hold a short tail of audio and throw the rest away,
                # so room noise never reaches the recognizer.
                self.rolled.append(window)
                self.rolled_seconds += len(window) / TARGET_RATE
                while self.rolled_seconds > PREROLL_SECONDS and self.rolled:
                    dropped = self.rolled.pop(0)
                    self.rolled_seconds -= len(dropped) / TARGET_RATE
                if have_voice:
                    self.saw_voice = True
                    self.chunks = list(self.rolled)
                    self.total_seconds = self.rolled_seconds
                    self.rolled = []
                    self.rolled_seconds = 0.0
                continue
            self.chunks.append(window)
            self.total_seconds += len(window) / TARGET_RATE
            # sherpa only queues a segment once the speech run ended and the silence
            # window was long enough. Silence that merely closes a word keeps the
            # segment open, so anything queued here is a finished sentence.
            if self.vad_state.client_voice_stop:
                return {"end_reason": "silence"}
            if (self.saw_voice and not have_voice and self.last_voice_at is not None
                    and self.total_seconds - self.last_voice_at >= MIN_SILENCE_SECONDS):
                return {"end_reason": "silence"}
            if self.total_seconds >= MAX_SPEECH_SECONDS:
                return {"end_reason": "max_length"}
        return None

    def audio(self) -> np.ndarray:
        if not self.chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self.chunks)

    def reset(self) -> None:
        self.chunks = []
        self.pending = np.zeros(0, dtype=np.float32)
        self.total_seconds = 0.0
        self.speech_seconds = 0.0
        self.last_voice_at = None
        self.saw_voice = False
        self.rolled = []
        self.rolled_seconds = 0.0
        if self.vad is not None:
            self.vad.release_conn_resources(self.vad_state)
        self.vad_state = vad_state(self.mode)


def recognize(recognizer, samples: np.ndarray) -> dict:
    started = time.perf_counter()
    stream = recognizer.create_stream()
    stream.accept_waveform(TARGET_RATE, samples)
    recognizer.decode_stream(stream)
    elapsed = time.perf_counter() - started
    audio_seconds = len(samples) / TARGET_RATE
    return {"text": stream.result.text.strip(), "audio_seconds": round(audio_seconds, 3),
            "decode_seconds": round(elapsed, 3),
            "real_time_factor": round(elapsed / audio_seconds, 4) if audio_seconds else None}


def finish(recognizer, current: Utterance, reason: str) -> dict:
    samples = current.audio()
    result = recognize(recognizer, samples) if len(samples) else {
        "text": "", "audio_seconds": 0.0, "decode_seconds": 0.0, "real_time_factor": None}
    result.update({"end_reason": reason,
                   "speech_seconds": round(current.speech_seconds, 3),
                   "frames_seconds": round(current.total_seconds, 3),
                   "heard_voice": current.saw_voice})
    current.reset()
    return {"utterance": result}


def handle(command: dict, state: dict, recognizer, vad) -> dict:
    name = command.get("cmd")
    if name == "start":
        rate = command.get("rate", 24000)
        mode = command.get("mode", "auto")
        if not isinstance(rate, int) or not 8000 <= rate <= 48000:
            return {"error": "invalid_rate"}
        if mode not in ("auto", "manual"):
            return {"error": "invalid_mode"}
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
            return {"ok": True}
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
    return {"error": "unknown_command"}


def main() -> None:
    threads = int(sys.argv[sys.argv.index("--threads") + 1]) if "--threads" in sys.argv else 2
    language = sys.argv[sys.argv.index("--language") + 1] if "--language" in sys.argv else "zh"
    for name in ("model.int8.onnx", "tokens.txt"):
        if not (MODEL_DIR / name).is_file():
            emit({"fatal": f"missing model file: {name}"})
            return
    recognizer = load_recognizer(threads, language)
    vad = build_vad()
    emit({"ready": True, "vad": vad is not None})
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
