"""Gateway-side device audio: listen start -> Opus frames -> text.

Drives the real gateway socket against the real local recognizer, so one path covers
frame streaming, energy-based end-of-utterance detection and the worker protocol.
The firmware never sends listen/stop, so tests must not rely on it either.
"""
import asyncio
from contextlib import asynccontextmanager, suppress
import json
from pathlib import Path
import socket
import struct

import pytest
import uvicorn
from websockets.asyncio.client import connect

from backend.app.devices import DeviceHub, DeviceSetup, DevicePreferences, create_gateway
from backend.run_devices import Server

ROOT = Path(__file__).resolve().parents[1]
STREAM = ROOT / "output" / "speech" / "device-stream.opusframes"
# Speech that stops mid-sentence: no trailing silence, so only the disconnect can end it.
NO_TAIL_STREAM = ROOT / "output" / "speech" / "no-tail.opusframes"
SILENCE_STREAM = ROOT / "output" / "speech" / "silence.opusframes"
EXPECTED = "你好我是小蛋这是本地语音测试我们可以选择声音也可以调整说话速度"
MAC = "aa:bb:cc:dd:ee:ff"
SETUP = {"lan_host": "192.168.1.20", "device_id": MAC,
         "original_ota_url": "", "original_recorded": True}

pytestmark = pytest.mark.skipif(
    not STREAM.is_file() or not SILENCE_STREAM.is_file() or not NO_TAIL_STREAM.is_file()
    or not (ROOT / ".venv-speech" / "Scripts" / "python.exe").is_file(),
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


def load_frames() -> list[bytes]:
    return read_stream(STREAM)


def with_trailing_silence(frames: list[bytes], count: int = 20) -> list[bytes]:
    """Append encoder silence: without it this firmware-style stream never ends.

    The frames are pre-encoded in .venv-speech because the web environment deliberately
    has no Opus/FFmpeg bindings.
    """
    return list(frames) + read_stream(SILENCE_STREAM)[:count]


@asynccontextmanager
async def bridge(tmp_path):
    hub = DeviceHub(tmp_path / "device.json")
    await hub.configure(DeviceSetup(**SETUP))
    await hub.save_preferences(DevicePreferences(volume=30))
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
    tools = ["self.get_device_status", "self.audio_speaker.set_volume"]
    try:
        async for raw in ws:
            message = json.loads(raw)
            if message.get("type") != "mcp":
                continue
            rpc = message["payload"]
            if rpc["method"] == "initialize":
                result = {"serverInfo": {"name": "fixture", "version": "2.2.6"}}
            elif rpc["method"] == "tools/list":
                result = {"tools": [{"name": name} for name in tools]}
            else:
                result = {"content": [{"type": "text", "text": "{}"}], "isError": False}
            await ws.send(json.dumps({"type": "mcp", "payload": {
                "jsonrpc": "2.0", "id": rpc["id"], "result": result}}))
    except Exception:
        pass


async def wait_ready(hub):
    async with asyncio.timeout(20):
        while hub.connection is None or not hub.connection.ready:
            await asyncio.sleep(0.01)


async def stream_frames(hub, ws, frames, expect_utterance=True, pace=True):
    """Send frames the way the firmware does: audio arrives over real time, not in a burst."""
    for payload in frames:
        await ws.send(payload)
        if pace:
            await asyncio.sleep(0)
    if not expect_utterance:
        return None
    async with asyncio.timeout(60):
        while hub.last_utterance is None:
            await asyncio.sleep(0.02)
    return hub.last_utterance


def test_device_frames_become_text(tmp_path):
    frames = with_trailing_silence(load_frames())
    assert len(frames) > 100

    async def scenario():
        async with bridge(tmp_path) as (hub, url):
            ws = await handshake(url, hub.token)
            emulator = asyncio.create_task(mcp_emulator(ws))
            try:
                await wait_ready(hub)
                await ws.send(json.dumps({"type": "listen", "state": "start", "mode": "auto"}))
                result = await stream_frames(hub, ws, frames)
                assert result["state"] == "recognized", result
                assert result["text"] == EXPECTED
                assert result["metrics"]["end_reason"] == "silence"
                assert result["metrics"]["audio_seconds"] > 8.0
                assert result["metrics"]["speech_seconds"] > 6.0
                assert hub.speech.public()["utterances"] == 1
            finally:
                emulator.cancel()
                with suppress(asyncio.CancelledError):
                    await emulator
                await ws.close()

    asyncio.run(scenario())


def test_frames_without_listen_start_are_dropped(tmp_path):
    """Idle frames must not reach the recognizer or kill the socket."""
    frames = load_frames()[:120]

    async def scenario():
        async with bridge(tmp_path) as (hub, url):
            ws = await handshake(url, hub.token)
            emulator = asyncio.create_task(mcp_emulator(ws))
            try:
                await wait_ready(hub)
                for payload in frames:
                    await ws.send(payload)  # no listen/start: dropped by design
                async with asyncio.timeout(10):
                    while hub.connection.frames_dropped < len(frames):
                        await asyncio.sleep(0.01)
                assert hub.connection.frames_dropped == len(frames)
                assert hub.speech.public()["utterances"] == 0
            finally:
                emulator.cancel()
                with suppress(asyncio.CancelledError):
                    await emulator
                await ws.close()

    asyncio.run(scenario())


def test_speech_without_trailing_silence_is_flushed_on_disconnect(tmp_path):
    """The firmware can close the channel mid-utterance; that audio must still be recognised."""
    frames = read_stream(NO_TAIL_STREAM)

    async def scenario():
        async with bridge(tmp_path) as (hub, url):
            ws = await handshake(url, hub.token)
            emulator = asyncio.create_task(mcp_emulator(ws))
            try:
                await wait_ready(hub)
                await ws.send(json.dumps({"type": "listen", "state": "start", "mode": "auto"}))
                for payload in frames:
                    await ws.send(payload)
                # Let the gateway consume the whole burst before the socket goes away;
                # closing instantly drops frames that are still in flight.
                async with asyncio.timeout(20):
                    while hub.connection is None or hub.connection.frames_received < len(frames):
                        await asyncio.sleep(0.01)
                await ws.close()
                async with asyncio.timeout(60):
                    while hub.last_utterance is None:
                        await asyncio.sleep(0.02)
                result = hub.last_utterance
                assert result["state"] == "recognized", result
                assert result["text"] == EXPECTED
                assert result["metrics"]["end_reason"] == "stop"
            finally:
                emulator.cancel()
                with suppress(asyncio.CancelledError):
                    await emulator

    asyncio.run(scenario())


def test_silence_only_produces_no_text(tmp_path):
    """Pure room noise must not be turned into an invented sentence."""

    async def scenario():
        async with bridge(tmp_path) as (hub, url):
            ws = await handshake(url, hub.token)
            emulator = asyncio.create_task(mcp_emulator(ws))
            try:
                await wait_ready(hub)
                await ws.send(json.dumps({"type": "listen", "state": "start", "mode": "auto"}))
                for payload in with_trailing_silence([], 60):
                    await ws.send(payload)
                await ws.close()
                async with asyncio.timeout(30):
                    while hub.connection is not None:
                        await asyncio.sleep(0.02)
                assert (hub.last_utterance or {}).get("text") in (None, "")
            finally:
                emulator.cancel()
                with suppress(asyncio.CancelledError):
                    await emulator

    asyncio.run(scenario())
