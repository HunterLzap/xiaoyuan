"""Bridge from the device gateway to the local streaming recognition worker.

The gateway runs in .venv, which deliberately has no numpy/av/sherpa-onnx; the worker
lives in .venv-speech. Frames are forwarded one by one over stdin/stdout so the model
loads once per gateway run and end-of-utterance is decided on decoded energy rather than
on frame sizes. Every failure path returns None: audio recognition is an add-on and must
never take down the control connection.
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path

from .config import ROOT

WORKER = ROOT / "scripts" / "speech_worker.py"
SPEECH_PYTHON = ROOT / ".venv-speech" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
SOURCE_RATE = 24000
MAX_FRAME_BYTES = 12000
START_TIMEOUT = 40
FRAME_TIMEOUT = 10
ENCODE_TIMEOUT = 60
TRANSCRIBE_TIMEOUT = 60


class SpeechUnavailable(RuntimeError):
    pass


class SpeechRecognizer:
    """One long-lived worker process; a crashed worker is restarted on the next use."""

    def __init__(self, python: Path = SPEECH_PYTHON, worker: Path = WORKER, threads: int = 2,
                 model_dir: Path = ROOT / "models" / "asr" / "sensevoice"):
        self.python = python if python.is_absolute() else ROOT / python
        self.worker = worker if worker.is_absolute() else ROOT / worker
        self.model_dir = model_dir if model_dir.is_absolute() else ROOT / model_dir
        self.threads = threads
        self.process: asyncio.subprocess.Process | None = None
        self.lock = asyncio.Lock()
        self.streaming = False
        self.mode = "auto"
        self.vad_ready = False
        self.voice_active = False
        self.last_error: str | None = None
        self.utterances = 0
        self.last_text: str | None = None
        self.last_metrics: dict | None = None
        self.available = self.python.is_file() and self.worker.is_file()

    async def _start(self) -> None:
        if not self.available:
            raise SpeechUnavailable("local_speech_env_missing")
        environment = dict(os.environ)
        # The worker is local-only; inherited proxy variables only add failure modes.
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy"):
            environment.pop(name, None)
        for name in ("AI_API_KEY", "AI_TTS_API_KEY", "AI_ADMIN_PROXY_TOKEN"):
            environment.pop(name, None)
        environment["AI_ASR_MODEL_DIR"] = str(self.model_dir)
        self.process = await asyncio.create_subprocess_exec(
            str(self.python), str(self.worker), "--threads", str(self.threads),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, env=environment, cwd=ROOT,
        )
        line = await asyncio.wait_for(self.process.stdout.readuntil(b"\n"), START_TIMEOUT)
        if not line:
            raise SpeechUnavailable("worker_exited")
        hello = json.loads(line.decode("utf-8"))
        if not hello.get("ready"):
            raise SpeechUnavailable(str(hello.get("fatal") or "worker_not_ready"))

    async def _stop(self) -> None:
        process = self.process
        self.process = None
        self.streaming = False
        if process is None:
            return
        with suppress(Exception):
            if process.stdin is not None:
                process.stdin.close()
        with suppress(Exception):
            await asyncio.wait_for(process.wait(), 5)
        if process.returncode is None:
            with suppress(Exception):
                process.kill()
            with suppress(Exception):
                await process.wait()

    async def _call(self, command: dict, payload: bytes | None = None) -> dict:
        process = self.process
        if process is None or process.stdin is None or process.stdout is None:
            raise SpeechUnavailable("worker_not_started")
        process.stdin.write(json.dumps(command).encode("utf-8") + b"\n")
        if payload is not None:
            # Raw bytes only: the frame command already carries its length.
            process.stdin.write(payload)
        await process.stdin.drain()
        # Read bytes: asyncio decodes pipes with the locale code page on Windows, which
        # mangles the worker's UTF-8 Chinese text before json can see it.
        line = await process.stdout.readuntil(b"\n")
        if not line:
            raise EOFError("worker_closed")
        return json.loads(line.decode("utf-8"))

    async def ensure_ready(self, mode: str = "auto") -> bool:
        """Start the worker and open a stream; safe to call repeatedly."""
        async with self.lock:
            if (self.streaming and self.mode == mode
                    and self.process is not None and self.process.returncode is None):
                return True
            try:
                if self.process is None or self.process.returncode is not None:
                    await self._stop()
                    await self._start()
                if self.streaming:
                    await asyncio.wait_for(self._call({"cmd": "stop"}), FRAME_TIMEOUT)
                response = await asyncio.wait_for(
                    self._call({"cmd": "start", "rate": SOURCE_RATE, "mode": mode}), FRAME_TIMEOUT)
                if response.get("error"):
                    raise SpeechUnavailable(str(response["error"]))
                self.streaming = True
                self.mode = mode
                self.vad_ready = bool(response.get("vad"))
                self.voice_active = False
                return True
            except (SpeechUnavailable, asyncio.TimeoutError, OSError, ValueError, EOFError) as error:
                self.last_error = _describe(error)
                await self._stop()
                return False

    async def push(self, frame: bytes) -> dict | None:
        """Forward one frame; returns an utterance dict when the sentence ended."""
        if not self.streaming:
            if not await self.ensure_ready(self.mode):
                return None
        if len(frame) > MAX_FRAME_BYTES:
            return None
        async with self.lock:
            try:
                response = await asyncio.wait_for(
                    self._call({"cmd": "frame", "size": len(frame)}, frame), FRAME_TIMEOUT)
            except (SpeechUnavailable, asyncio.TimeoutError, OSError, ValueError, EOFError) as error:
                self.last_error = _describe(error)
                await self._stop()
                return None
        if "error" in response:
            self.last_error = str(response["error"])
            return None
        self.voice_active = bool(response.get("voice"))
        if "utterance" in response:
            return self._record(response["utterance"])
        return None

    async def finish(self) -> dict | None:
        """Close the current stream; returns a final utterance if one was in progress."""
        if not self.streaming:
            return None
        async with self.lock:
            try:
                response = await asyncio.wait_for(self._call({"cmd": "stop"}), 30)
            except (SpeechUnavailable, asyncio.TimeoutError, OSError, ValueError, EOFError) as error:
                self.last_error = _describe(error)
                await self._stop()
                return None
            finally:
                self.streaming = False
        if "utterance" in response:
            return self._record(response["utterance"])
        return None

    async def encode(self, wav_path: Path) -> list[bytes] | None:
        """Turn a synthesized WAV into device-ready Opus frames.

        The worker writes the frames to a file because carrying audio through the JSON
        line protocol would require escaping megabytes of binary.
        """
        async with self.lock:
            try:
                if self.process is None or self.process.returncode is not None:
                    await self._stop()
                    await self._start()
                response = await asyncio.wait_for(
                    self._call({"cmd": "encode", "path": str(wav_path)}), ENCODE_TIMEOUT)
            except (SpeechUnavailable, asyncio.TimeoutError, OSError, ValueError, EOFError) as error:
                self.last_error = _describe(error)
                await self._stop()
                return None
        if "error" in response:
            self.last_error = str(response["error"])
            return None
        frames_path = response.get("frames_path")
        if not isinstance(frames_path, str):
            self.last_error = "encode_missing_path"
            return None
        try:
            return _read_frame_file(Path(frames_path))
        except (OSError, ValueError) as error:
            self.last_error = type(error).__name__
            return None
        finally:
            with suppress(OSError):
                Path(frames_path).unlink(missing_ok=True)

    async def transcribe(self, wav_bytes: bytes) -> dict | None:
        """Transcribe a browser-recorded WAV blob."""
        if not wav_bytes:
            return None
        async with self.lock:
            try:
                if self.process is None or self.process.returncode is not None:
                    await self._stop()
                    await self._start()
                response = await asyncio.wait_for(
                    self._call({"cmd": "recognize_wav", "size": len(wav_bytes)}, wav_bytes),
                    TRANSCRIBE_TIMEOUT)
            except (SpeechUnavailable, asyncio.TimeoutError, OSError, ValueError, EOFError) as error:
                self.last_error = _describe(error)
                await self._stop()
                return None
        if "error" in response:
            self.last_error = str(response["error"])
            return None
        return response

    async def start_pcm(self) -> bool:
        """Open a streaming PCM→Opus encode on the worker."""
        async with self.lock:
            try:
                if self.process is None or self.process.returncode is not None:
                    await self._stop()
                    await self._start()
                response = await asyncio.wait_for(self._call({"cmd": "pcm_start"}), FRAME_TIMEOUT)
                if response.get("error"):
                    raise SpeechUnavailable(str(response["error"]))
                return True
            except (SpeechUnavailable, asyncio.TimeoutError, OSError, ValueError, EOFError) as error:
                self.last_error = _describe(error)
                await self._stop()
                return False

    async def push_pcm(self, chunk: bytes) -> list[bytes]:
        """Encode one PCM chunk; returns the complete Opus frames it produced."""
        if not chunk:
            return []
        async with self.lock:
            try:
                response = await asyncio.wait_for(
                    self._call({"cmd": "pcm", "size": len(chunk)}, chunk), FRAME_TIMEOUT)
            except (SpeechUnavailable, asyncio.TimeoutError, OSError, ValueError, EOFError) as error:
                self.last_error = _describe(error)
                await self._stop()
                raise SpeechUnavailable(self.last_error) from None
        if response.get("error"):
            self.last_error = str(response["error"])
            raise SpeechUnavailable(self.last_error)
        return _decode_packets(response)

    async def end_pcm(self) -> list[bytes]:
        """Flush the final partial frame."""
        async with self.lock:
            try:
                response = await asyncio.wait_for(self._call({"cmd": "pcm_end"}), FRAME_TIMEOUT)
            except (SpeechUnavailable, asyncio.TimeoutError, OSError, ValueError, EOFError) as error:
                self.last_error = _describe(error)
                await self._stop()
                raise SpeechUnavailable(self.last_error) from None
        if response.get("error"):
            self.last_error = str(response["error"])
            raise SpeechUnavailable(self.last_error)
        return _decode_packets(response)

    def _record(self, utterance: dict) -> dict:
        self.last_error = None
        self.utterances += 1
        self.last_text = utterance.get("text")
        self.last_metrics = {key: utterance.get(key) for key in
                             ("audio_seconds", "speech_seconds", "decode_seconds",
                              "real_time_factor", "end_reason", "noise_db")}
        return utterance

    def public(self) -> dict:
        process = self.process
        return {"available": self.available,
                "running": bool(process is not None and process.returncode is None),
                "streaming": self.streaming, "mode": self.mode, "vad": self.vad_ready,
                "utterances": self.utterances, "last_text": self.last_text,
                "last_metrics": self.last_metrics,
                "last_error": self.last_error, "source_rate": SOURCE_RATE}

    async def close(self) -> None:
        async with self.lock:
            await self._stop()


def _decode_packets(response: dict) -> list[bytes]:
    """Opus frames arrive base64-encoded because the worker protocol is JSON lines."""
    import base64
    import binascii

    encoded = response.get("packets")
    if not isinstance(encoded, list):
        return []
    packets: list[bytes] = []
    for item in encoded:
        if not isinstance(item, str):
            continue
        try:
            packets.append(base64.b64decode(item, validate=True))
        except (binascii.Error, ValueError):
            continue
    return packets


def _read_frame_file(path: Path) -> list[bytes]:
    """Read the length-prefixed frame file the worker writes."""
    import struct

    data = path.read_bytes()
    packets: list[bytes] = []
    offset = 0
    while offset + 4 <= len(data):
        (size,) = struct.unpack("<I", data[offset:offset + 4])
        offset += 4
        if size <= 0 or offset + size > len(data):
            raise ValueError("truncated frame file")
        packets.append(data[offset:offset + size])
        offset += size
    return packets


def _describe(error: Exception) -> str:
    return str(error) if isinstance(error, SpeechUnavailable) else type(error).__name__
