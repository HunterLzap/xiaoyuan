import asyncio
from contextlib import aclosing, suppress
import json
import logging
from uuid import uuid4

import anyio
from fastapi.responses import StreamingResponse
from starlette.requests import ClientDisconnect

from .audio_codec import DeviceCodec
from .community import AudioRateController, handleAbortMessage
from .llm import ProviderError
from .schemas import ChatRequest

logger = logging.getLogger(__name__)


def sse(event: str, payload: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


class VoiceStreamingResponse(StreamingResponse):
    async def __call__(self, scope, receive, send):
        async with anyio.create_task_group() as group:
            async def stream():
                try:
                    await self.stream_response(send)
                except (OSError, ClientDisconnect):
                    pass
                finally:
                    group.cancel_scope.cancel()

            group.start_soon(stream)
            await self.listen_for_disconnect(receive)
            group.cancel_scope.cancel()
        if self.background is not None:
            await self.background()

    async def stream_response(self, send):
        try:
            await super().stream_response(send)
        finally:
            with anyio.CancelScope(shield=True):
                await self.body_iterator.aclose()


class DeviceSocket:
    def __init__(self, connection):
        self.connection = connection

    async def send(self, payload):
        await self.connection.send(json.loads(payload))


class DeviceVoice:
    """Device protocol and PCM/Opus transport for the shared session service."""

    def __init__(self, hub, service, tts_factory):
        self.hub = hub
        self.service = service
        self.tts_factory = tts_factory

    def submit(self, text, connection):
        previous = connection.voice_task
        if previous is not None:
            previous.cancel()
        connection.voice_task = asyncio.create_task(self._handle(text, connection))

    async def interrupt(self, connection):
        task = connection.voice_task
        turn_id = connection.voice_turn_id
        await handleAbortMessage(connection)
        if task is not None and task is not asyncio.current_task():
            with suppress(asyncio.CancelledError):
                await task
            if connection.voice_session_id is not None and turn_id is not None:
                await self.service.playback(connection.voice_session_id, turn_id, "interrupted")

    async def _handle(self, text, connection):
        async with connection.voice_lock:
            await self._run(text, connection)

    async def _run(self, text, connection):
        if connection is not self.hub.connection:
            return
        connection.stopped = False
        connection.client_abort = False
        identity = uuid4()
        connection.voice_turn_id = identity
        controller = AudioRateController(frame_duration=60)
        connection.audio_controller = controller
        codec = None
        completed = False
        try:
            await connection.send({"type": "stt", "text": text})
            await connection.send({"type": "tts", "state": "start"})
            try:
                codec = DeviceCodec(decode=False)
            except RuntimeError:
                raise ProviderError(503, "opus_unavailable", "设备语音编码尚不可用。") from None
            controller.start_sending(connection.send_audio)
            async with aclosing(self.service.turn(
                ChatRequest(message=text, session_id=connection.voice_session_id),
                source="device_voice", tts_factory=self.tts_factory, turn_id=identity,
            )) as events:
                async for kind, payload in events:
                    if connection.stopped or connection is not self.hub.connection:
                        raise asyncio.CancelledError()
                    if kind == "session":
                        from uuid import UUID
                        connection.voice_session_id = UUID(payload["session_id"])
                    elif kind == "sentence":
                        sentence = payload["text"]

                        async def announce(text=sentence):
                            await connection.send({"type": "tts", "state": "sentence_start", "text": text})

                        controller.add_message(announce)
                    elif kind == "audio":
                        for packet in codec.encode(payload):
                            controller.add_audio(packet)
                    elif kind == "warning":
                        self.hub.last_error = payload["message"]
                    elif kind == "done":
                        completed = True
            for packet in codec.encode(b"", True):
                controller.add_audio(packet)
            await controller.wait_finished()
            if completed and not connection.stopped:
                await connection.send({"type": "tts", "state": "stop"})
        except ProviderError as error:
            self.hub.last_error = error.message
            logger.warning("device_voice_failed code=%s", error.code)
        except (OSError, ValueError, RuntimeError) as error:
            self.hub.last_error = "设备语音回合未完成。"
            logger.warning("device_voice_failed error=%s", type(error).__name__)
        finally:
            controller.stop_sending()
            if controller.pending_send_task is not None:
                with suppress(asyncio.CancelledError, ProviderError, OSError, RuntimeError):
                    await controller.pending_send_task
            if codec is not None:
                codec.close()
            if not completed and connection is self.hub.connection:
                with suppress(ProviderError):
                    await connection.send({"type": "tts", "state": "stop"})
            if connection.voice_session_id is not None and not completed:
                await self.service.playback(connection.voice_session_id, identity, "interrupted")
            if connection.voice_task is asyncio.current_task():
                connection.voice_task = None
