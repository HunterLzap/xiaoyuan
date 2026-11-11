"""Browser-facing voice conversation: hold to talk, get text and spoken audio back.

This is the standalone conversation agent the device later plugs into. It shares the same
model→sentence→TTS→Opus pipeline as the device path, but streams everything to the browser
so each stage's cost is visible while it happens instead of guessing from silence.

Protocol (Server-Sent Events over POST /api/voice/turn):
    event: stage   data: {"stage":"asr","ms":120}
    event: stage   data: {"stage":"llm_first","ms":2100}
    event: text    data: {"delta":"你好呀"}
    event: audio   data: {"pcm":"<base64 24kHz mono s16le>"}
    event: done    data: {"reply":"...", "ms":3400, "first_ms":2400}
    event: error   data: {"message":"...", "code":"..."}
"""
from __future__ import annotations

import asyncio
import base64
from contextlib import aclosing, suppress
import json
import logging
import time

from .llm import ProviderError
from .prompt_builder import build_system_prompt

logger = logging.getLogger(__name__)

# Sentences are cut at these marks; the first one also breaks on commas so speech starts
# as early as the model allows.
SENTENCE_ENDS = "。！？!?；;\n"
FIRST_ENDS = "，,、~" + SENTENCE_ENDS
FIRST_MAX_CHARS = 12
MAX_BUFFER = 40


class SentenceSplitter:
    """Turn streamed model output into speakable sentences."""

    def __init__(self):
        self.buffer = ""
        self.first = True

    def feed(self, piece: str) -> list[str]:
        self.buffer += piece
        ready = []
        while True:
            cut = self._cut()
            if cut is None:
                break
            sentence = self.buffer[:cut + 1].strip()
            self.buffer = self.buffer[cut + 1:]
            if sentence:
                ready.append(sentence)
                self.first = False
        return ready

    def _cut(self) -> int | None:
        marks = FIRST_ENDS if self.first else SENTENCE_ENDS
        for index, char in enumerate(self.buffer):
            if char in marks:
                return index
        if self.first and len(self.buffer) >= FIRST_MAX_CHARS:
            return FIRST_MAX_CHARS - 1
        if len(self.buffer) >= MAX_BUFFER:
            return len(self.buffer) - 1
        return None

    def flush(self) -> list[str]:
        remainder = self.buffer.strip()
        self.buffer = ""
        return [remainder] if remainder else []


def sse(event: str, payload: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


async def run_turn(settings, service, tts_factory, speech, text: str, history: list[dict],
                   max_seconds: float = 60):
    """Yield SSE events for one question-answer exchange."""
    started = time.perf_counter()
    reply_parts: list[str] = []
    audio_packets = 0
    first_audio_ms: int | None = None
    tts_ok = False

    messages = [{"role": "system", "content": build_system_prompt(settings, "voice", [], None)}]
    messages += history
    messages.append({"role": "user", "content": text})

    try:
        provider = service.provider
        if provider is None:
            raise ProviderError(503, "not_configured", "模型尚未配置。")

        stream = getattr(provider, "complete_stream", None)
        splitter = SentenceSplitter()
        queue: asyncio.Queue = asyncio.Queue(maxsize=8)

        async def produce_sentences() -> None:
            """Read model tokens, emit sentences into the queue."""
            try:
                if stream is None:
                    result = await provider.complete(messages)
                    reply_parts.append(result.reply or "")
                    for sentence in splitter.feed(result.reply or ""):
                        await queue.put(sentence)
                else:
                    async with aclosing(stream(messages)) as pieces:
                        async for piece in pieces:
                            if not piece:
                                continue
                            reply_parts.append(piece)
                            for sentence in splitter.feed(piece):
                                await queue.put(sentence)
                for sentence in splitter.flush():
                    await queue.put(sentence)
            except ProviderError as error:
                await queue.put(("error", error))
            except (OSError, ValueError, RuntimeError) as error:
                await queue.put(("error", ProviderError(502, "stream_failed", type(error).__name__)))
            await queue.put(None)

        producer = asyncio.create_task(produce_sentences())
        llm_start = time.perf_counter()
        try:
            while True:
                remaining = max_seconds - (time.perf_counter() - started)
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                item = await asyncio.wait_for(queue.get(), timeout=remaining)
                if item is None:
                    break
                if isinstance(item, tuple) and item[0] == "error":
                    raise item[1]
                yield sse("text", {"full": "".join(reply_parts).strip()})
                if first_audio_ms is None:
                    # First sentence exists; report how long the model took to produce it.
                    yield sse("stage", {"stage": "llm_first",
                                        "ms": int((time.perf_counter() - llm_start) * 1000)})

                if not tts_ok:
                    tts_ok = await speech.start_pcm()
                adapter = tts_factory(settings)
                try:
                    async for chunk in adapter.synthesize_stream(item):
                        # The browser plays raw PCM directly; Opus is only needed for the
                        # device, and a browser cannot decode bare Opus packets.
                        if first_audio_ms is None:
                            first_audio_ms = int((time.perf_counter() - started) * 1000)
                            yield sse("stage", {"stage": "first_audio", "ms": first_audio_ms})
                        audio_packets += len(chunk)
                        yield sse("audio", {"pcm": base64.b64encode(chunk).decode("ascii")})
                except ProviderError as error:
                    logger.warning("voice_tts_failed code=%s", error.code)
                    yield sse("warning", {"code": error.code,
                                          "message": "语音合成未完成，文字回答仍会保留；请检查语音配置或网络。"})
                    continue
                finally:
                    with suppress(Exception):
                        await adapter.close()
                if time.perf_counter() - started > max_seconds:
                    raise asyncio.TimeoutError()
        finally:
            producer.cancel()
            with suppress(asyncio.CancelledError):
                await producer

        text_out = "".join(reply_parts).strip()
        if not text_out:
            raise ProviderError(502, "empty_reply", "模型没有返回内容。")
        yield sse("text", {"full": text_out})
        yield sse("done", {
            "reply": text_out,
            "ms": int((time.perf_counter() - started) * 1000),
            "first_ms": first_audio_ms,
            "packets": audio_packets,
        })
    except ProviderError as error:
        yield sse("error", {"code": error.code, "message": error.message})
    except asyncio.TimeoutError:
        yield sse("error", {"code": "timeout", "message": "本次回答超时。"})
    except (OSError, ValueError, RuntimeError) as error:
        yield sse("error", {"code": type(error).__name__, "message": "处理这次对话时出错。"})
