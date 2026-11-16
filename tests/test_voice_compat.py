"""Tests for multi-provider voice compatibility, shared audio codec, and voice profile retention."""
from __future__ import annotations

import asyncio
import base64
from io import BytesIO
import json
from types import SimpleNamespace
import wave

from fastapi.testclient import TestClient
import httpx

from backend.app.asr import BailianASRProvider, OpenAICompatibleASRProvider, transcribe_browser_wav
from backend.app.audio_codec import pcm_rms, pcm_to_wav, resample_pcm16_mono
from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.realtime import RealtimeTurn, _is_end_intent
from backend.app.service import ChatService
from backend.app.settings_store import SettingsStore
from backend.app.tts import BailianTTSProvider, OpenAITTSProvider, build_tts_provider
from backend.app.voice_profiles import realtime_scope, tts_scope
from backend.app.voice_transport import DeviceVoice
from test_api import HEADERS


def _wav_bytes(rate: int = 16000, frames: int = 160) -> bytes:
    return pcm_to_wav(b"\x00\x01" * frames, sample_rate=rate, channels=1)


def test_end_intent_precision_avoids_false_disconnects():
    assert _is_end_intent("闭嘴") is True
    assert _is_end_intent("塔菲，退下吧。") is True
    assert _is_end_intent("塔菲退下") is True
    assert _is_end_intent("太妃，关闭对话") is True
    assert _is_end_intent("关闭") is True
    assert _is_end_intent("好了，你先退下吧") is True
    assert _is_end_intent("进入待机") is True
    assert _is_end_intent("好的，再见") is True
    assert _is_end_intent("帮我关闭客厅灯") is False
    assert _is_end_intent("今天几点关闭") is False
    assert _is_end_intent("你去休息一下吗") is False
    assert _is_end_intent("这个项目什么时候结束") is False
    assert _is_end_intent("你不用管别人怎么说，直接查天气") is False
    assert _is_end_intent("刚才那句停止说话是什么意思") is False


def test_audio_helpers_resample_and_rms():
    silent = b"\x00\x00" * 160
    assert pcm_rms(silent) == 0.0
    pcm_16k = b"\x00\x10" * 160
    pcm_24k = resample_pcm16_mono(pcm_16k, 16000, 24000)
    assert len(pcm_24k) == 240 * 2
    wav = _wav_bytes()
    with wave.open(BytesIO(wav), "rb") as reader:
        assert reader.getframerate() == 16000
        assert reader.getnframes() == 160


def test_openai_compatible_asr_and_voice_route(tmp_path, monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": "今天上海天气怎么样"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cfg = Settings(
        _env_file=None,
        voice_mode="pipeline",
        asr_provider="openai",
        asr_base_url="https://api.example.com/v1",
        asr_api_key="asr-secret",
        asr_model="whisper-1",
        api_key="chat-secret",
        model="chat-model",
        m5stack_enabled=False,
        personal_kb_enabled=False,
        history_db_path=None,
        personal_kb_db_path=None,
        usage_log_path=None,
        assistant_db_path=None,
    )
    provider = OpenAICompatibleASRProvider(cfg, http_client=client)
    result = asyncio.run(provider.transcribe_wav(_wav_bytes()))
    asyncio.run(client.aclose())
    assert result["text"] == "今天上海天气怎么样"
    assert str(seen[0].url) == "https://api.example.com/v1/audio/transcriptions"
    assert seen[0].headers["authorization"] == "Bearer asr-secret"

    monkeypatch.setattr(
        "backend.app.main.transcribe_browser_wav",
        lambda *_args, **_kwargs: asyncio.sleep(0, result={"text": "识别成功", "provider": "openai", "model": "whisper-1"}),
    )
    app = create_app(cfg, settings_store=SettingsStore(tmp_path / ".env"))
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as web:
        resp = web.post("/api/voice/asr", content=_wav_bytes(), headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["text"] == "识别成功"


def test_bailian_asr_and_tts_ws_protocols():
    sent_asr: list[dict] = []

    class FakeASRSocket:
        def __init__(self):
            self.incoming = iter([
                json.dumps({"type": "session.created"}),
                json.dumps({"type": "session.updated"}),
                json.dumps({"type": "conversation.item.input_audio_transcription.completed", "transcript": "百炼识别测试"}),
                json.dumps({"type": "session.finished"}),
            ])

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def send(self, raw: str):
            sent_asr.append(json.loads(raw))

        async def recv(self) -> str:
            return next(self.incoming)

    cfg = Settings(
        _env_file=None,
        rt_workspace="ws-123",
        rt_api_key="bailian-secret",
        asr_provider="bailian",
        asr_model="qwen3-asr-flash-realtime",
        tts_provider="bailian",
        tts_model="qwen3-tts-flash-realtime",
        tts_voice="Cherry",
    )
    asr = BailianASRProvider(cfg, ws_connect=lambda *_a, **_kw: FakeASRSocket())
    asr_res = asyncio.run(asr.transcribe_wav(_wav_bytes()))
    assert asr_res["text"] == "百炼识别测试"
    assert sent_asr[0]["type"] == "session.update"
    assert sent_asr[0]["session"]["input_audio_format"] == "pcm"

    sent_tts: list[dict] = []
    sample_pcm = b"\x02\x00" * 120

    class FakeTTSSocket:
        def __init__(self):
            self.incoming = iter([
                json.dumps({"type": "session.created"}),
                json.dumps({"type": "session.updated"}),
                json.dumps({"type": "response.audio.delta", "delta": base64.b64encode(sample_pcm).decode("ascii")}),
                json.dumps({"type": "session.finished"}),
            ])

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def send(self, raw: str):
            sent_tts.append(json.loads(raw))

        async def recv(self) -> str:
            return next(self.incoming)

    tts = BailianTTSProvider(cfg, ws_connect=lambda *_a, **_kw: FakeTTSSocket())
    wav_out = asyncio.run(tts.synthesize("你好。"))
    assert sent_tts[0]["session"]["response_format"] == "pcm"
    assert sent_tts[1]["type"] == "input_text_buffer.append"
    with wave.open(BytesIO(wav_out), "rb") as reader:
        assert reader.readframes(reader.getnframes()) == sample_pcm


def test_openai_tts_provider_stream_and_factory():
    requests_seen: list[httpx.Request] = []
    pcm = b"\x03\x00" * 200

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        body = json.loads(request.content)
        if body["response_format"] == "pcm":
            return httpx.Response(200, content=pcm)
        return httpx.Response(200, content=pcm_to_wav(pcm, sample_rate=24000))

    cfg = Settings(
        _env_file=None,
        tts_provider="openai",
        tts_base_url="https://speech.example.com/v1",
        tts_api_key="tts-secret",
        tts_use_text_connection=False,
        tts_model="tts-1",
        tts_voice="nova",
    )
    provider = build_tts_provider(cfg, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert isinstance(provider, OpenAITTSProvider)

    async def collect():
        chunks = []
        async for item in provider.synthesize_stream("测试一下。"):
            chunks.append(item)
        await provider.close()
        return b"".join(chunks)

    assert asyncio.run(collect()) == pcm
    assert str(requests_seen[0].url) == "https://speech.example.com/v1/audio/speech"


def test_compatible_realtime_ga_session_and_24k_resample():
    cfg = Settings(
        _env_file=None,
        voice_mode="realtime",
        rt_provider="compatible",
        rt_endpoint="wss://api.openai.com/v1/realtime",
        rt_model="gpt-realtime",
        rt_voice="alloy",
        rt_api_key="rt-secret",
        history_db_path=None,
        personal_kb_db_path=None,
        usage_log_path=None,
        m5stack_enabled=False,
        personal_kb_enabled=False,
    )
    svc = ChatService(cfg, None)
    turn = RealtimeTurn(svc, None, "web_voice", lambda *_a: asyncio.sleep(0), False)
    ga_session = turn._build_session_config({"audio": {"input": {}}})
    assert ga_session["type"] == "realtime"
    assert ga_session["audio"]["output"]["voice"] == "alloy"
    assert turn._compatible_ga is True

    sent = []

    class FakeWS:
        async def send(self, raw):
            sent.append(json.loads(raw))

    turn.ws = FakeWS()
    turn.reader = SimpleNamespace(done=lambda: False)
    pcm_16k = b"\x01\x00" * 160
    asyncio.run(turn.append(pcm_16k))
    decoded = base64.b64decode(sent[-1]["audio"])
    assert len(decoded) == 240 * 2


def test_voice_profiles_retained_across_mode_and_provider_switches(tmp_path):
    cfg = Settings(
        _env_file=None,
        voice_mode="realtime",
        rt_provider="bailian",
        rt_workspace="ws-1",
        rt_model="qwen3.8-omni-flash-realtime",
        rt_voice="qwen-taffy-id",
        rt_api_key="rt-secret",
        tts_rate=1.2,
        tts_pitch=3.0,
        history_db_path=None,
        personal_kb_db_path=None,
        usage_log_path=None,
        m5stack_enabled=False,
        personal_kb_enabled=False,
        assistant_db_path=tmp_path / "assistant_state.sqlite3",
    )
    app = create_app(cfg, settings_store=SettingsStore(tmp_path / ".env"))
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        # 1) Switch to pipeline + OpenAI TTS with new voice & neutral rate/pitch.
        switch_pipeline = client.put(
            "/api/settings/api",
            json={
                "voice_mode": "pipeline",
                "base_url": "https://api.openai.com/v1",
                "api_key": "chat-key",
                "model": "gpt-4o-mini",
                "tts_provider": "openai",
                "tts_model": "tts-1",
                "tts_voice": "nova",
                "tts_rate": 1.0,
                "tts_pitch": 0.0,
            },
            headers=HEADERS,
        )
        assert switch_pipeline.status_code == 200, switch_pipeline.text
        profiles = switch_pipeline.json()["text"]["voice_profiles"]
        rt_key = realtime_scope("bailian", "qwen3.8-omni-flash-realtime")
        tts_key = tts_scope("openai", "tts-1")
        assert profiles[rt_key]["voice"] == "qwen-taffy-id"
        assert profiles[rt_key]["rate"] == 1.2
        assert profiles[rt_key]["pitch"] == 3.0
        assert profiles[tts_key]["voice"] == "nova"

        # 2) Switch back to realtime; Taffy profile stays intact in SQLite.
        switch_back = client.put(
            "/api/settings/api",
            json={
                "voice_mode": "realtime",
                "base_url": "https://api.openai.com/v1",
                "rt_provider": "bailian",
                "rt_workspace": "ws-1",
                "rt_model": "qwen3.8-omni-flash-realtime",
                "rt_voice": profiles[rt_key]["voice"],
                "tts_rate": profiles[rt_key]["rate"],
                "tts_pitch": profiles[rt_key]["pitch"],
            },
            headers=HEADERS,
        )
        assert switch_back.status_code == 200
        restored = switch_back.json()["text"]
        assert restored["rt_voice"] == "qwen-taffy-id"
        assert restored["voice_profiles"][tts_key]["voice"] == "nova"


def test_device_voice_uses_in_process_codec_without_local_speech_worker(monkeypatch):
    encoded_packets: list[bytes] = []

    class FakeCodec:
        def __init__(self, *, decode=True, encode=True):
            assert decode is False and encode is True

        def encode(self, data: bytes, finish: bool = False):
            if data:
                return [b"opus-frame"]
            return [b"opus-tail"] if finish else []

        def close(self):
            return None

    monkeypatch.setattr("backend.app.voice_transport.DeviceCodec", FakeCodec)
    hub = SimpleNamespace(
        speech=SimpleNamespace(start_pcm=lambda: (_ for _ in ()).throw(AssertionError("must not call local speech worker"))),
        last_error=None,
    )

    class FakeService:
        async def playback(self, *_args):
            return None

        async def turn(self, *_args, **_kwargs):
            yield "session", {"session_id": "00000000-0000-0000-0000-000000000001"}
            yield "sentence", {"text": "你好"}
            yield "audio", b"\x01\x00" * 100
            yield "done", {}

    sent_json: list[dict] = []

    class FakeConn:
        voice_session_id = None
        stopped = False
        client_abort = False
        voice_turn_id = None
        audio_controller = None
        voice_task = None
        voice_lock = asyncio.Lock()

        async def send(self, payload):
            sent_json.append(payload)

        async def send_audio(self, packet):
            encoded_packets.append(packet)

    conn = FakeConn()
    hub.connection = conn
    voice = DeviceVoice(hub, FakeService(), lambda _cfg: None)
    asyncio.run(voice._run("你好", conn))
    assert encoded_packets == [b"opus-frame", b"opus-tail"]
    assert any(msg.get("type") == "tts" and msg.get("state") == "stop" for msg in sent_json)


def test_transcribe_browser_wav_local_fallback_raises_when_unavailable():
    cfg = Settings(_env_file=None, asr_provider="local")
    speech = SimpleNamespace(transcribe=lambda _raw: asyncio.sleep(0, result=None))
    try:
        asyncio.run(transcribe_browser_wav(cfg, _wav_bytes(), speech_recognizer=speech))
    except Exception as exc:
        assert getattr(exc, "code", None) == "voice_asr_failed"
    else:
        raise AssertionError("Expected ProviderError when local ASR returns None")
