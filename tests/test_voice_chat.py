import asyncio
import json
from types import SimpleNamespace

from backend.app.config import Settings
from backend.app.llm import ProviderError
from backend.app.voice_chat import run_turn
from test_api import HEADERS, running


class Speech:
    async def start_pcm(self):
        return True


class TTS:
    closed = 0

    def __init__(self, settings):
        pass

    async def synthesize_stream(self, text):
        yield b"\x01\x00" * 240

    async def close(self):
        type(self).closed += 1


def config():
    return Settings(_env_file=None, m5stack_enabled=False, history_db_path=None, usage_log_path=None)


def decode(chunk):
    event, data = chunk.decode().strip().split("\n", 1)
    return event[7:], json.loads(data[6:])


def test_first_audio_precedes_model_completion_and_cancel_releases_full_queue():
    async def check():
        released = asyncio.Event()
        first = asyncio.Event()

        class Provider:
            async def complete_stream(self, messages):
                try:
                    yield "第一句。"
                    first.set()
                    for index in range(30):
                        yield f"后续句子{index}。"
                finally:
                    released.set()

        service = SimpleNamespace(provider=Provider())
        events = run_turn(config(), service, TTS, Speech(), "问题", [])
        async for chunk in events:
            if decode(chunk)[0] == "audio":
                break
        await first.wait()
        await asyncio.sleep(0)
        assert not released.is_set()
        await asyncio.wait_for(events.aclose(), timeout=1)
        assert released.is_set()
        assert TTS.closed > 0

    asyncio.run(check())


def test_nonstream_provider_and_tts_failure_preserve_text_without_retry():
    async def check():
        class Provider:
            calls = 0

            async def complete(self, messages):
                self.calls += 1
                return SimpleNamespace(reply="你好。")

        class FailedTTS(TTS):
            async def synthesize_stream(self, text):
                raise ProviderError(502, "tts_connection", "连接失败")
                yield

        provider = Provider()
        events = [decode(chunk) async for chunk in run_turn(
            config(), SimpleNamespace(provider=provider), FailedTTS, Speech(), "问题", [])]
        assert provider.calls == 1
        assert any(name == "warning" for name, data in events)
        assert ("text", {"full": "你好。"}) in events
        assert events[-1][0] == "done"
        assert events[-1][1]["packets"] == 0

    asyncio.run(check())


def test_incomplete_model_reports_error_and_cleans_up():
    async def check():
        class Provider:
            async def complete_stream(self, messages):
                yield "第一句。"
                raise ProviderError(502, "stream_failed", "模型连接中断")

        events = [decode(chunk) async for chunk in run_turn(
            config(), SimpleNamespace(provider=Provider()), TTS, Speech(), "问题", [])]
        assert events[-1][0] == "error"
        assert not any(name == "done" for name, data in events)

    asyncio.run(check())


def test_voice_routes_require_same_origin_local_header(tmp_path):
    with running(tmp_path) as (client, gateway, app):
        assert client.post("/api/voice/reset").status_code == 403
        assert client.post("/api/voice/reset", headers=HEADERS | {"Origin": "https://other.test"}).status_code == 403
        assert client.post("/api/voice/reset", headers=HEADERS).status_code == 200


def test_reset_invalidates_inflight_history_and_closes_generator(tmp_path, monkeypatch):
    from backend.app import main
    from backend.app.voice_chat import sse

    closed = []

    async def fake_turn(*args):
        try:
            yield sse("text", {"full": "旧回答"})
            yield sse("done", {"reply": "旧回答"})
        finally:
            closed.append(True)

    monkeypatch.setattr(main, "run_turn", fake_turn)
    with running(tmp_path) as (client, gateway, app):
        endpoints = {route.path: route.endpoint for route in app.routes}

        async def check():
            async def body():
                return {"text": "测试"}

            response = await endpoints["/api/voice/turn"](SimpleNamespace(json=body))
            await anext(response.body_iterator)
            await endpoints["/api/voice/reset"]()
            assert [chunk async for chunk in response.body_iterator] == []
            assert app.state.voice_history == []
            assert closed

        asyncio.run(check())


def test_http_disconnect_cancels_tts_and_does_not_commit_history(tmp_path):
    import socket
    import httpx
    import uvicorn
    from backend.app.main import create_app
    from backend.app.settings_store import SettingsStore

    async def check():
        closed = asyncio.Event()

        class Provider:
            async def complete_stream(self, messages):
                yield "测试回答。"

            async def close(self):
                pass

        class SlowTTS(TTS):
            async def synthesize_stream(self, text):
                yield b"\x00\x00" * 240
                await asyncio.Event().wait()

            async def close(self):
                closed.set()

        app = create_app(config(), provider=Provider(), tts_factory=SlowTTS,
                         settings_store=SettingsStore(tmp_path / ".env"))
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
        task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            async with asyncio.timeout(5):
                while not server.started:
                    await asyncio.sleep(0.01)
                async with httpx.AsyncClient(trust_env=False) as client:
                    async with client.stream("POST", f"http://127.0.0.1:{port}/api/voice/turn",
                                             headers={"X-Local-Settings": "1"}, json={"text": "测试"}) as response:
                        assert response.status_code == 200
                        async for line in response.aiter_lines():
                            if line == "event: audio":
                                break
                await closed.wait()
                assert app.state.voice_history == []
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, timeout=5)

    asyncio.run(check())
