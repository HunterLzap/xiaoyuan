"""Streaming conversation pipeline for the device.

Mirrors the reference xiaozhi server: the model's output is consumed as it arrives and
each complete sentence is handed to TTS immediately, so speech starts while the model is
still writing. The previous design waited for the whole reply (4-5s) and then synthesised
it (2-4s), which made the first sound arrive after seven seconds.

Flow:
    model tokens -> sentence buffer -> TTS worker queue -> audio queue -> device

Each stage runs independently so a slow provider only delays its own sentence.
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
import time

from .llm import ProviderError

logger = logging.getLogger(__name__)

# Punctuation that ends a speakable sentence. The first sentence also breaks on commas so
# speech can start sooner, matching the reference implementation's first-sentence rule.
SENTENCE_ENDS = "。！？!?；;\n"
FIRST_SENTENCE_ENDS = "，,、~" + SENTENCE_ENDS
# The opening sentence is what the user waits for in silence, so it is capped hard: even
# a short line costs ~1.1s to synthesise, and a 20-character opener pushed the first sound
# past seven seconds in testing.
FIRST_SENTENCE_MAX = 10
# Stop buffering if the model writes a long run without punctuation.
MAX_BUFFER_CHARS = 40
# Cap on queued sentences so a runaway model cannot flood TTS.
MAX_QUEUE = 6


class SentenceStreamer:
    """Turn a token stream into complete sentences."""

    def __init__(self):
        self.buffer = ""
        self.first = True

    def feed(self, piece: str) -> list[str]:
        """Add a token and return any sentences that are now complete."""
        self.buffer += piece
        ready: list[str] = []
        while True:
            cut = self._find_cut()
            if cut is None:
                break
            sentence = self.buffer[:cut + 1].strip()
            self.buffer = self.buffer[cut + 1:]
            if sentence:
                ready.append(sentence)
                self.first = False
        return ready

    def _find_cut(self) -> int | None:
        marks = FIRST_SENTENCE_ENDS if self.first else SENTENCE_ENDS
        for index, char in enumerate(self.buffer):
            if char in marks:
                return index
        # Cut the opening sentence early even without punctuation, so the first sound is
        # not held back by a long clause.
        if self.first and len(self.buffer) >= FIRST_SENTENCE_MAX:
            return FIRST_SENTENCE_MAX - 1
        # A long run without punctuation still has to be spoken eventually.
        if len(self.buffer) >= MAX_BUFFER_CHARS:
            return len(self.buffer) - 1
        return None

    def flush(self) -> list[str]:
        """Return whatever is left when the model finishes."""
        remainder = self.buffer.strip()
        self.buffer = ""
        return [remainder] if remainder else []


class DeviceTurn:
    """One question-answer exchange with the device."""

    def __init__(self, connection, tts, speech, on_reply_done=None):
        self.connection = connection
        self.tts = tts
        self.speech = speech
        self.on_reply_done = on_reply_done
        self.sentences: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE)
        self.audio: asyncio.Queue = asyncio.Queue()
        self.text_parts: list[str] = []
        self.started = time.perf_counter()
        self.first_audio_at: float | None = None
        self.packets_sent = 0
        self.failed = False
        self.text_sent = False

    async def run(self, token_stream) -> None:
        """Consume model tokens, synthesise and play, all concurrently."""
        synth = asyncio.create_task(self._synthesis_loop())
        play = asyncio.create_task(self._playback_loop())
        streamer = SentenceStreamer()
        try:
            async for piece in token_stream:
                self.text_parts.append(piece)
                for sentence in streamer.feed(piece):
                    if not self.text_sent:
                        # Show the sentence as soon as it exists; the firmware renders it
                        # while the matching audio is still being synthesised.
                        await self.connection.send(
                            {"type": "tts", "state": "sentence_start", "text": sentence})
                        self.text_sent = True
                    await self.sentences.put(sentence)
            for sentence in streamer.flush():
                if not self.text_sent:
                    await self.connection.send(
                        {"type": "tts", "state": "sentence_start", "text": sentence})
                    self.text_sent = True
                await self.sentences.put(sentence)
        finally:
            # Always close the sentence queue so synthesis can finish.
            await self.sentences.put(None)
        try:
            await synth
            await self.audio.put(None)
            await play
        finally:
            for task in (synth, play):
                if not task.done():
                    task.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await task

    @property
    def reply(self) -> str:
        return "".join(self.text_parts).strip()

    async def _synthesis_loop(self) -> None:
        """Synthesise queued sentences one at a time, in order."""
        while True:
            sentence = await self.sentences.get()
            if sentence is None:
                return
            if self.connection.stopped:
                continue
            if not await self.speech.start_pcm():
                self.failed = True
                continue
            adapter = self.tts()
            try:
                async for chunk in adapter.synthesize_stream(sentence):
                    if self.connection.stopped:
                        break
                    for packet in await self.speech.push_pcm(chunk):
                        await self.audio.put(packet)
            except ProviderError as error:
                logger.warning("device_tts_failed code=%s", error.code)
                self.failed = True
            except (OSError, ValueError, RuntimeError) as error:
                logger.warning("device_tts_failed error=%s", type(error).__name__)
                self.failed = True
            finally:
                with suppress(Exception):
                    await adapter.close()
                for packet in await self.speech.end_pcm():
                    await self.audio.put(packet)

    async def _playback_loop(self) -> None:
        """Send audio frames at the pace the device consumes them."""
        frame_seconds = 0.060
        while True:
            packet = await self.audio.get()
            if packet is None:
                return
            if self.connection.stopped:
                continue
            if self.first_audio_at is None:
                self.first_audio_at = time.perf_counter() - self.started
            await self.connection.send_audio(packet)
            self.packets_sent += 1
            await asyncio.sleep(frame_seconds)
