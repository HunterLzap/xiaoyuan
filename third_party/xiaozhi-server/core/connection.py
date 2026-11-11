import asyncio
from contextlib import aclosing, suppress
from time import perf_counter

from backend.app.llm import Completion
from core.providers.tts.base import TTSProviderBase


class ConnectionHandler:
    """Narrowed streaming turn: LLM text queue, sentence TTS, cancellable audio."""

    def __init__(self, provider, messages, tts=None, timeout=120):
        self.provider = provider
        self.messages = messages
        self.tts = tts
        self.timeout = timeout
        self.client_abort = False
        self.reply_parts = []
        self.result = None
        self.llm_complete = False
        self.audio_failed = False
        self.audio_bytes = 0
        self.first_audio_ms = None
        self.events = asyncio.Queue(maxsize=16)
        self.sentences = asyncio.Queue(maxsize=8)
        self.tasks = []
        self.started = perf_counter()
        self.driver = None
        self.closed = False

    @property
    def reply(self):
        return "".join(self.reply_parts).strip()

    async def _read_model(self):
        splitter = TTSProviderBase()
        if self.tts is None:
            self.result = await self.provider.complete(self.messages)
            piece = self.result.reply or ""
            self.reply_parts.append(piece)
            await self.events.put(("text", {"full": self.reply}))
        else:
            async with aclosing(self.provider.complete_stream(self.messages)) as stream:
                async for piece in stream:
                    if self.client_abort:
                        return
                    if isinstance(piece, Completion):
                        self.result = piece
                        self.result.reply = self.reply
                        continue
                    self.reply_parts.append(piece)
                    await self.events.put(("text", {"full": self.reply}))
                    for sentence in splitter.feed(piece):
                        await self.sentences.put(sentence)
            for sentence in splitter.flush():
                await self.sentences.put(sentence)
        self.llm_complete = True
        await self.events.put(("generated", {"reply": self.reply}))
        await self.sentences.put(None)

    async def _speak(self):
        while True:
            sentence = await self.sentences.get()
            if sentence is None:
                return
            if self.audio_failed:
                continue
            await self.events.put(("sentence", {"text": sentence}))
            if self.first_audio_ms is None:
                await self.events.put(("stage", {
                    "stage": "llm_first", "ms": int((perf_counter() - self.started) * 1000),
                }))
            try:
                received = 0
                async with aclosing(self.tts.synthesize_stream(sentence)) as audio:
                    async for chunk in audio:
                        if self.client_abort:
                            return
                        if self.first_audio_ms is None:
                            self.first_audio_ms = int((perf_counter() - self.started) * 1000)
                            await self.events.put(("stage", {
                                "stage": "first_audio", "ms": self.first_audio_ms,
                            }))
                        self.audio_bytes += len(chunk)
                        received += len(chunk)
                        await self.events.put(("audio", chunk))
                if not received:
                    from backend.app.llm import ProviderError
                    raise ProviderError(502, "tts_empty_audio", "语音服务未返回音频。")
            except Exception as error:
                from backend.app.llm import ProviderError
                if not isinstance(error, ProviderError):
                    raise
                self.audio_failed = True
                await self.events.put(("warning", {
                    "code": error.code,
                    "message": "语音合成未完成，文字回答仍会保存；请检查语音配置或网络。",
                }))

    async def _drive(self):
        try:
            async with asyncio.timeout(self.timeout):
                async with asyncio.TaskGroup() as group:
                    self.tasks = [group.create_task(self._read_model())]
                    if self.tts is not None:
                        self.tasks.append(group.create_task(self._speak()))
            await self.events.put(("finished", None))
        except asyncio.CancelledError:
            raise
        except ExceptionGroup as errors:
            error = errors
            while isinstance(error, BaseExceptionGroup):
                error = error.exceptions[0]
            await self.events.put(("failure", error))
        except Exception as error:
            await self.events.put(("failure", error))

    async def run(self):
        self.driver = asyncio.create_task(self._drive())
        try:
            while True:
                kind, payload = await self.events.get()
                if kind == "failure":
                    raise payload
                if kind == "finished":
                    return
                yield kind, payload
        finally:
            await self.close()

    async def close(self):
        if self.closed:
            return
        self.closed = True
        self.client_abort = True
        if self.driver is not None:
            self.driver.cancel()
            with suppress(asyncio.CancelledError):
                await self.driver
        if self.tts is not None:
            await self.tts.close()
