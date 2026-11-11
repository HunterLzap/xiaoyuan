"""Device conversation loop: recognised speech -> model reply -> spoken reply.

The gateway owns the WebSocket; this module owns what happens between "the device said
something" and "the device hears an answer". Message order and send pacing follow the
reference xiaozhi server: tts/start, sentence_start with the text, audio packets at the
frame rate, then tts/stop.

Two deliberate departures from that reference:
  * the reply text is shown while waiting (stt + a "thinking" placeholder), because the
    firmware has no thinking state of its own;
  * failures are spoken as a short notice instead of being silent, so a broken turn is
    distinguishable from a device that simply did not hear anything.
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
import io
import logging
from pathlib import Path
import tempfile
import time
import wave

from .config import ROOT
from .device_turn import DeviceTurn
from .llm import ProviderError
from .prompt_builder import build_system_prompt

logger = logging.getLogger(__name__)

# 60 ms frames: the device negotiates this in its hello and expects it back.
FRAME_SECONDS = 0.060
PREBUFFER_PACKETS = 5
REPLY_TIMEOUT = 60
WORK_DIR = ROOT / "output" / "replies"
# Spoken when a turn fails; keeps the user from waiting in silence.
FAILURE_NOTICE = "抱歉，我这边出了点问题，请再说一次。"
# Shown on the device screen while the model is thinking. The firmware has no dedicated
# thinking state, so this rides along with the tts/start that keeps the channel alive.
THINKING_TEXT = "让我想想喵…"
# Sentence ends used to split a reply for incremental synthesis.
SENTENCE_ENDS = "。！？!?；;\n"
# The opening piece is spoken while the user is still waiting, so keep it short.
FIRST_PIECE_CHARS = 12
# Synthesis is far slower than playback, so several pieces are prepared in parallel to
# avoid audible gaps between sentences.
PREFETCH = 3


class DeviceConversation:
    """One gateway run; holds the talking pieces supplied by the admin app."""

    def __init__(self, hub, service, tts_factory, speak_timeout: float = REPLY_TIMEOUT):
        self.hub = hub
        self.service = service
        self.tts_factory = tts_factory
        self.speak_timeout = speak_timeout
        self.turn = 0
        self.busy = False
        self.last_reply: str | None = None
        self.last_error: str | None = None
        # Bounded segment history so follow-up questions keep their context; a new
        # wake-up starts a fresh segment (see reset()).
        self.history: list[dict[str, str]] = []

    async def handle_utterance(self, text: str, connection) -> None:
        """Run one full turn; never raises, so the control socket stays usable."""
        text = (text or "").strip()
        if not text or connection is None:
            return
        if self.busy:
            # A second sentence while answering would interleave audio; drop it loudly.
            logger.info("device_turn_skipped busy turn=%s text=%s", self.turn, text[:40])
            return
        self.busy = True
        self.turn += 1
        turn = self.turn
        started = time.perf_counter()
        try:
            # Hold the channel open while thinking. The firmware drops the socket after
            # roughly ten silent seconds, so the device is told immediately that an
            # answer is coming, before the model has produced anything.
            connection.stopped = False
            await self._announce_thinking(connection)
            await self._stream_turn(text, connection, turn, started)
        except ProviderError as error:
            self.last_error = error.message
            logger.warning("device_turn_failed turn=%s code=%s", turn, error.code)
            await self._speak_failure(connection, turn)
        except (asyncio.TimeoutError, OSError, RuntimeError, ValueError) as error:
            self.last_error = type(error).__name__
            logger.warning("device_turn_failed turn=%s error=%s", turn, type(error).__name__)
            await self._speak_failure(connection, turn)
        finally:
            self.busy = False

    async def _stream_turn(self, text: str, connection, turn: int, started: float) -> None:
        """Drive the model→TTS→device pipeline for one question."""
        messages = self._build_messages(text)
        turn_state = DeviceTurn(connection, lambda: self.tts_factory(self.service.settings),
                                self.hub.speech)
        await connection.send({"type": "tts", "state": "start"})
        await turn_state.run(self._token_stream(messages))
        reply = turn_state.reply
        if not reply:
            raise ProviderError(502, "empty_reply", "模型没有返回内容。")
        if turn != self.turn:
            return
        self.last_reply = reply
        self._remember(text, reply)
        logger.info("device_turn %s", {
            "turn": turn, "heard": text, "reply": reply,
            "first_audio_seconds": round(turn_state.first_audio_at, 2)
            if turn_state.first_audio_at else None,
            "packets": turn_state.packets_sent,
            "total_seconds": round(time.perf_counter() - started, 2)})
        if turn_state.failed and not turn_state.packets_sent:
            raise ProviderError(502, "tts_failed", "语音合成失败。")
        await connection.send({"type": "tts", "state": "stop"})

    async def _token_stream(self, messages):
        """Yield model tokens, falling back to one block when streaming is unavailable."""
        provider = self.service.provider
        if provider is None:
            raise ProviderError(503, "not_configured", "模型尚未配置。")
        stream = getattr(provider, "complete_stream", None)
        if stream is None:
            result = await self.service.provider.complete(messages)
            if result.reply:
                yield result.reply
            return
        async for piece in stream(messages):
            yield piece

    def _build_messages(self, text: str) -> list[dict[str, str]]:
        """System prompt plus the current conversation segment."""
        settings = getattr(self.service, "settings", None)
        prompt = build_system_prompt(settings, "voice", [], None)
        messages = [{"role": "system", "content": prompt}]
        messages += self.history
        messages.append({"role": "user", "content": text})
        return messages

    def _remember(self, question: str, reply: str) -> None:
        """Keep a bounded segment history for follow-up questions."""
        self.history += [
            {"role": "user", "content": question},
            {"role": "assistant", "content": reply},
        ]
        settings = getattr(self.service, "settings", None)
        turns = getattr(settings, "history_turns", 6) or 6
        limit = max(1, int(turns)) * 2
        self.history = self.history[-limit:]

    async def _announce_thinking(self, connection) -> None:
        """Switch the device into its speaking state and show a short placeholder.

        tts/start moves the firmware from listening to speaking; without it the turn is
        treated as idle and the channel is closed before the answer exists. The sentence
        text doubles as the on-screen status, which is the only way to show thinking.
        """
        try:
            await connection.send({"type": "tts", "state": "start"})
            await connection.send({"type": "tts", "state": "sentence_start", "text": THINKING_TEXT})
        except Exception:
            # A closed socket will fail again on the real answer; do not mask that here.
            logger.info("device_thinking_notice_failed")


    async def _synthesize(self, text: str) -> list[bytes] | None:
        if not text.strip():
            return None
        adapter = self.tts_factory(self.service.settings)
        try:
            audio = await adapter.synthesize(text[:500])
        except ProviderError:
            raise
        finally:
            with suppress(Exception):
                await adapter.close()
        return await self._encode(audio)

    async def _encode(self, wav_bytes: bytes) -> list[bytes] | None:
        """Persist the WAV so the speech worker can encode it in its own environment."""
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile("wb", dir=WORK_DIR, prefix="reply-",
                                             suffix=".wav", delete=False)
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as source:
                if source.getnframes() < 1:
                    raise ValueError("empty_tts_audio")
            handle.write(wav_bytes)
            handle.flush()
            path = Path(handle.name)
        finally:
            handle.close()
        try:
            return await self.hub.speech.encode(path)
        finally:
            with suppress(OSError):
                path.unlink(missing_ok=True)


    async def _play(self, connection, packets: list[bytes], text: str, first: bool) -> None:
        """Announce one sentence and stream its audio."""
        # tts/start was already sent as the thinking notice; sending it again would
        # restart the firmware's speaking state mid-turn. Only the text and the audio go
        # out here, and the turn is closed once with a single tts/stop by the caller.
        await connection.send({"type": "tts", "state": "sentence_start", "text": text})
        sent = 0
        for index, packet in enumerate(packets):
            if connection.stopped:
                logger.info("device_playback_interrupted sent=%s/%s", sent, len(packets))
                return
            await connection.send_audio(packet)
            sent += 1
            # Pace every sentence after the first, and the tail of the first, so the device
            # buffer neither starves nor overflows.
            if not first or index >= PREBUFFER_PACKETS:
                await asyncio.sleep(FRAME_SECONDS)
        logger.info("device_playback_done sent=%s duration=%.2fs first=%s",
                    sent, sent * FRAME_SECONDS, first)

    async def _speak_failure(self, connection, turn: int) -> None:
        if connection is None or turn != self.turn:
            return
        try:
            # The thinking notice already opened the speaking state; only speak the notice
            # if synthesis works, otherwise just close the turn so the device returns idle.
            packets = await self._synthesize(FAILURE_NOTICE)
            if packets:
                await self._play(connection, packets, FAILURE_NOTICE, first=True)
            await connection.send({"type": "tts", "state": "stop"})
        except (ProviderError, asyncio.TimeoutError, OSError, ValueError):
            # Even the failure notice can fail; drop the turn rather than wedge the socket.
            with suppress(Exception):
                await connection.send({"type": "tts", "state": "stop"})

    def public(self) -> dict:
        return {"busy": self.busy, "turn": self.turn,
                "last_reply": self.last_reply, "last_error": self.last_error}
