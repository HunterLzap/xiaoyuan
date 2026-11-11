"""Full device turn: heard speech -> model reply -> Opus audio back to the device.

Drives the real gateway socket with real Opus frames and asserts the protocol order the
firmware depends on: stt, tts/start, tts/sentence_start, binary audio, tts/stop.
The model and TTS providers are replaced with deterministic fakes: this test proves the
transport and ordering, not a paid upstream call.
"""
import asyncio
from contextlib import asynccontextmanager, suppress
import io
import json
from pathlib import Path
import socket
import struct
import wave

import pytest
import uvicorn
from websockets.asyncio.client import connect

from backend.app.devices import DeviceHub, DeviceSetup, DevicePreferences, create_gateway
from backend.app.conversation import DeviceConversation, THINKING_TEXT
from backend.run_devices import Server

ROOT = Path(__file__).resolve().parents[1]
STREAM = ROOT / "output" / "speech" / "device-stream.opusframes"
EXPECTED = "你好我是小蛋这是本地语音测试我们可以选择声音也可以调整说话速度"
MAC = "aa:bb:cc:dd:ee:ff"
SETUP = {"lan_host": "192.168.1.20", "device_id": MAC,
         "original_ota_url": "", "original_recorded": True}
REPLY = "这是测试回复"

pytestmark = pytest.mark.skipif(
    not STREAM.is_file() or not (ROOT / ".venv-speech" / "Scripts" / "python.exe").is_file(),
    reason="deliberate: local recognizer assets are not present",
)


def read_stream(path: Path) -> list[bytes]:
    data = path.read_bytes()
    frames, offset = [], 0
    while offset < len(data):
        (size,) = struct.unpack("<I", data[offset:offset + 4])
        offset += 4
        frames.append(data[offset:offset + size])
        offset += size
    return frames


def make_wav(seconds: float = 0.6, rate: int = 24000) -> bytes:
    """A short tone; stands in for whatever the TTS provider returns.

    Written by hand because the web environment deliberately has no numpy.
    """
    import math

    count = int(rate * seconds)
    samples = bytearray()
    for index in range(count):
        value = int(math.sin(2 * math.pi * 440 * index / rate) * 0.3 * 32767)
        samples += struct.pack("<h", value)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as sink:
        sink.setnchannels(1)
        sink.setsampwidth(2)
        sink.setframerate(rate)
        sink.writeframes(bytes(samples))
    return buffer.getvalue()


class FakeReply:
    def __init__(self, reply):
        self.reply = reply


class FakeProvider:
    """Streaming provider stub: yields the reply one word-like piece at a time."""

    def __init__(self, reply=REPLY):
        self.reply = reply
        self.seen: list[list[dict]] = []

    def complete_stream(self, messages):
        self.seen.append(messages)
        return self._produce()

    async def _produce(self):
        # Split so the sentence streamer has real work to do.
        step = 4
        for start in range(0, len(self.reply), step):
            yield self.reply[start:start + step]

    async def complete(self, messages):
        return FakeReply(self.reply)

    async def close(self):
        pass


class FakeService:
    """Minimal stand-in for ChatService; carries settings and the provider."""

    def __init__(self, reply=REPLY):
        self.settings = None
        self.provider = FakeProvider(reply)


class FakeTTS:
    """Returns the same short tone for both the batch and streaming paths."""

    def __init__(self, settings=None):
        pass

    async def synthesize(self, text: str) -> bytes:
        return make_wav()

    async def synthesize_stream(self, text: str):
        """Yield raw PCM16 mono 24 kHz, which is what the provider streams."""
        wav = make_wav()
        with wave.open(io.BytesIO(wav), "rb") as source:
            raw = source.readframes(source.getnframes())
        # Uneven chunks so the encoder has to buffer partial frames.
        step = 3000
        for start in range(0, len(raw), step):
            yield raw[start:start + step]

    async def close(self):
        pass


@asynccontextmanager
async def bridge(tmp_path, service=None):
    hub = DeviceHub(tmp_path / "device.json")
    await hub.configure(DeviceSetup(**SETUP))
    await hub.save_preferences(DevicePreferences(volume=30))
    hub.speech = hub.speech  # real recognizer and encoder
    hub.conversation = DeviceConversation(hub, service or FakeService(), FakeTTS)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    hub.port = sock.getsockname()[1]
    server = Server(uvicorn.Config(create_gateway(hub), host="127.0.0.1", log_level="error",
                                   access_log=False, ws_max_size=12000, lifespan="off"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if task.done():
                    await task
                await asyncio.sleep(0.01)
        hub.gateway_running = True
        yield hub, f"ws://127.0.0.1:{hub.port}/xiaozhi/v1/"
    finally:
        await hub.disconnect()
        await hub.speech.close()
        server.should_exit = True
        await task
        sock.close()


async def handshake(url: str, token: str):
    headers = {"Authorization": f"Bearer {token}", "Device-Id": MAC, "Protocol-Version": "1"}
    ws = await connect(url, additional_headers=headers)
    await ws.send(json.dumps({"type": "hello", "transport": "websocket", "version": 1,
                              "features": {"mcp": True}}))
    hello = json.loads(await ws.recv())
    assert hello["type"] == "hello"
    return ws


async def mcp_emulator(ws):
    tools = ["self.get_device_status"]
    try:
        async for raw in ws:
            if isinstance(raw, bytes):
                continue
            message = json.loads(raw)
            if message.get("type") != "mcp":
                continue
            rpc = message["payload"]
            if rpc["method"] == "initialize":
                result = {"serverInfo": {"name": "fixture", "version": "2.2.6"}}
            elif rpc["method"] == "tools/list":
                result = {"tools": [{"name": name} for name in tools]}
            else:
                result = {"content": [], "isError": False}
            await ws.send(json.dumps({"type": "mcp", "payload": {
                "jsonrpc": "2.0", "id": rpc["id"], "result": result}}))
    except Exception:
        pass


async def answer_mcp(ws, rpc):
    """Reply to an MCP request; the gateway needs this to reach ready."""
    result = {"content": [], "isError": False}
    if rpc.get("method") == "initialize":
        result = {"serverInfo": {"name": "fixture", "version": "2.2.6"}}
    elif rpc.get("method") == "tools/list":
        result = {"tools": [{"name": "self.get_device_status"}]}
    await ws.send(json.dumps({"type": "mcp", "payload": {
        "jsonrpc": "2.0", "id": rpc["id"], "result": result}}))


async def wait_ready(hub):
    async with asyncio.timeout(20):
        while hub.connection is None or not hub.connection.ready:
            await asyncio.sleep(0.01)


def test_full_turn_speaks_back_and_keeps_protocol_order(tmp_path):
    """The device hears an answer: text first, then audio, then the stop marker."""

    async def scenario():
        service = FakeService()
        async with bridge(tmp_path, service) as (hub, url):
            ws = await handshake(url, hub.token)
            events, audio_packets = [], []
            try:
                # Serve MCP and gather the turn in one reader: two concurrent recv loops
                # are a protocol error on the client side.
                async def pump(until_stop=True):
                    async with asyncio.timeout(120):
                        while True:
                            raw = await ws.recv()
                            if isinstance(raw, bytes):
                                audio_packets.append(raw)
                                continue
                            message = json.loads(raw)
                            if message.get("type") == "mcp":
                                await answer_mcp(ws, message["payload"])
                                continue
                            if message.get("type") in {"stt", "tts"}:
                                events.append(message)
                                if (until_stop and message.get("type") == "tts"
                                        and message.get("state") == "stop"):
                                    return

                # Bring the control channel up first (MCP handshake).
                await ws.send(json.dumps({"type": "listen", "state": "start", "mode": "auto"}))
                for payload in read_stream(STREAM):
                    await ws.send(payload)
                await pump()
                await ws.close()
                # No system prompt is configured on the fake service, so only the user
                # message should reach the model.
                assert service.provider.seen == [[{"role": "user", "content": EXPECTED}]], \
                    service.provider.seen
                assert hub.conversation.last_reply == REPLY
                kinds = [(event["type"], event.get("state")) for event in events]
                # No transcript is shown on screen by request.
                assert ("stt", None) not in kinds
                # The channel is held open before the model answers: the firmware closes it
                # after ~10 quiet seconds, and thinking alone can take longer.
                first = kinds[0]
                assert first == ("tts", "start"), kinds[:3]
                assert events[1].get("text") == THINKING_TEXT, events[:2]
                assert ("tts", "sentence_start") in kinds
                # The answer's own sentence_start comes after the thinking placeholder.
                answer_texts = [e.get("text") for e in events
                                if e.get("type") == "tts" and e.get("state") == "sentence_start"]
                assert answer_texts[0] == THINKING_TEXT
                assert REPLY in answer_texts, answer_texts
                assert kinds[-1] == ("tts", "stop"), kinds
                assert len(audio_packets) >= 8, len(audio_packets)
                assert all(isinstance(packet, bytes) and 0 < len(packet) < 400
                           for packet in audio_packets)
            finally:
                with suppress(Exception):
                    await ws.close()

    asyncio.run(scenario())


def test_failed_model_still_answers_with_notice(tmp_path):
    """A broken turn must be audible, not silent."""
    class BrokenProvider(FakeProvider):
        def complete_stream(self, messages):
            from backend.app.llm import ProviderError
            raise ProviderError(502, "upstream", "boom")

    class BrokenService(FakeService):
        def __init__(self, reply=REPLY):
            super().__init__(reply)
            self.provider = BrokenProvider(reply)

    async def scenario():
        async with bridge(tmp_path, BrokenService()) as (hub, url):
            ws = await handshake(url, hub.token)
            audio_packets = 0
            stopped = False
            try:
                await ws.send(json.dumps({"type": "listen", "state": "start", "mode": "auto"}))
                for payload in read_stream(STREAM):
                    await ws.send(payload)
                async with asyncio.timeout(120):
                    while not stopped:
                        raw = await ws.recv()
                        if isinstance(raw, bytes):
                            audio_packets += 1
                            continue
                        message = json.loads(raw)
                        if message.get("type") == "mcp":
                            await answer_mcp(ws, message["payload"])
                            continue
                        if message.get("type") == "tts" and message.get("state") == "stop":
                            stopped = True
                assert audio_packets > 0, "failure notice must be spoken"
                assert hub.conversation.last_error is not None
            finally:
                with suppress(Exception):
                    await ws.close()

    asyncio.run(scenario())
