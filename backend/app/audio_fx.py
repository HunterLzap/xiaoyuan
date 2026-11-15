"""Post-process synthesized speech: volume, speed and pitch.

These three are applied to the returned WAV rather than described in the prompt, because
an instruction like "speak faster" is only a suggestion to the model while a filter is
deterministic. Filters are only invoked when a value differs from neutral, so the common
path keeps the provider's original bytes untouched.
"""
from __future__ import annotations

import asyncio
from contextlib import aclosing, suppress
from io import BytesIO
from pathlib import Path
import shutil
import subprocess
import tempfile
import wave

from .config import ROOT
from .audio_metrics import AudioFxMetrics
# Bounds mirror the Settings fields; callers pass already-validated values.
VOLUME_MIN, VOLUME_MAX = 0.2, 3.0
RATE_MIN, RATE_MAX = 0.5, 2.0
PITCH_MIN, PITCH_MAX = -8.0, 8.0
PROCESS_TIMEOUT = 30


class RealtimeAudio:
    def __init__(self, settings, emit):
        # settings is either a Settings object or a zero-arg callable returning the
        # current effective Settings. A segment pins tts_rate/tts_pitch on its first
        # chunk and every later chunk of that same segment reuses them, so a change
        # applies only on the next segment of the same realtime connection without
        # reconnecting; the segment already streaming never jumps. finish()/close()
        # clear the pinned segment.
        self._settings = settings if callable(settings) else (lambda: settings)
        self.emit = emit
        self.queue = None
        self.task = None
        self.segment = None
        self.metrics = AudioFxMetrics()

    def _params(self):
        settings = self._settings()
        return settings.tts_rate, settings.tts_pitch

    async def push(self, data):
        if self.segment is None:
            speed, pitch = self._params()
            self.metrics.start_segment(speed, pitch)
            self.segment = (None, None) if is_neutral(1.0, speed, pitch) else (speed, pitch)
            if self.segment[0] is not None:
                self.queue = asyncio.Queue(maxsize=32)
                self.task = asyncio.create_task(self._run(speed, pitch))
        self.metrics.record_pcm("input", data)
        if self.segment[0] is None:
            self.metrics.record_pcm("output", data)
            await self.emit(data)
            return
        if self.task is None:
            speed, pitch = self.segment
            self.queue = asyncio.Queue(maxsize=32)
            self.task = asyncio.create_task(self._run(speed, pitch))
        if self.task.done():
            await self.task
        await self.queue.put(data)

    async def _run(self, speed, pitch):
        async def chunks():
            while True:
                data = await self.queue.get()
                if data is None:
                    return
                yield data
        async with aclosing(stream_pcm(chunks(), speed, pitch)) as audio:
            async for chunk in audio:
                self.metrics.record_pcm("output", chunk)
                await self.emit(chunk)

    async def finish(self):
        if self.task is not None:
            if self.task.done():
                await self.task
            else:
                await self.queue.put(None)
                await self.task
            self.task = None
            self.queue = None
        self.segment = None

    async def close(self):
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
            self.queue = None
        self.segment = None


async def stream_pcm(chunks, speed: float, pitch: float):
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        from .llm import ProviderError
        raise ProviderError(503, "ffmpeg_missing", "当前语速或音调需要 FFmpeg，请恢复默认值或安装后再用。")
    process = await asyncio.create_subprocess_exec(
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", "pipe:0",
        "-af", build_filters(24000, 1.0, speed, pitch),
        "-f", "s16le", "-ar", "24000", "-ac", "1", "pipe:1",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )

    async def feed():
        try:
            async with aclosing(chunks):
                async for chunk in chunks:
                    process.stdin.write(chunk)
                    await process.stdin.drain()
        finally:
            process.stdin.close()

    writer = asyncio.create_task(feed())
    try:
        while chunk := await process.stdout.read(8192):
            yield chunk
        await writer
        if await process.wait() != 0:
            from .llm import ProviderError
            raise ProviderError(502, "audio_processing_failed", "语速或音调处理未完成。")
    finally:
        writer.cancel()
        with suppress(asyncio.CancelledError, BrokenPipeError, ConnectionResetError):
            await writer
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()


def is_neutral(volume: float, rate: float, pitch: float) -> bool:
    return abs(volume - 1.0) < 0.01 and abs(rate - 1.0) < 0.01 and abs(pitch) < 0.05


def wav_params(raw: bytes) -> tuple[int, int] | None:
    """Return (rate, channels) for a WAV blob, or None when it is not readable."""
    try:
        with wave.open(BytesIO(raw), "rb") as source:
            return source.getframerate(), source.getnchannels()
    except (wave.Error, EOFError, OSError):
        return None


def build_filters(rate: int, volume: float, speed: float, pitch: float) -> str:
    """Compose the ffmpeg filter chain.

    Pitch shifting multiplies the sample rate and then restores the original duration
    with atempo, which moves pitch without changing length. Speed then applies on top.
    """
    filters = []
    if abs(pitch) >= 0.05:
        factor = 2.0 ** (pitch / 12.0)
        filters.append(f"asetrate={int(rate * factor)}")
        filters.append(f"aresample={rate}")
        filters.append(f"atempo={1.0 / factor:.6f}")
    if abs(speed - 1.0) >= 0.01:
        # atempo only accepts 0.5..2.0 per instance; chain for larger factors.
        remaining = speed
        while remaining > 2.0:
            filters.append("atempo=2.0")
            remaining /= 2.0
        while remaining < 0.5:
            filters.append("atempo=0.5")
            remaining /= 0.5
        filters.append(f"atempo={remaining:.6f}")
    if abs(volume - 1.0) >= 0.01:
        filters.append(f"volume={volume:.3f}")
    return ",".join(filters)


def _run_ffmpeg(source: Path, target: Path, filter_chain: str) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError("ffmpeg")
    completed = subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-i", str(source), "-af", filter_chain,
         "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(target)],
        capture_output=True, timeout=PROCESS_TIMEOUT,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", "replace").strip()[:200]
        raise ValueError(message or "ffmpeg failed")


async def apply(raw: bytes, volume: float = 1.0, speed: float = 1.0, pitch: float = 0.0) -> bytes:
    """Return the WAV with the requested shaping applied."""
    if is_neutral(volume, speed, pitch) or not raw:
        return raw
    params = wav_params(raw)
    if params is None:
        return raw
    rate, _channels = params
    chain = build_filters(rate, volume, speed, pitch)
    if not chain:
        return raw

    def work() -> bytes:
        temporary_root = ROOT / ".cache" / "speech"
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root, prefix="audio-fx-") as directory:
            source = Path(directory) / "in.wav"
            target = Path(directory) / "out.wav"
            source.write_bytes(raw)
            _run_ffmpeg(source, target, chain)
            return target.read_bytes()

    # ffmpeg is a blocking subprocess; keep it off the event loop.
    return await asyncio.get_running_loop().run_in_executor(None, work)
