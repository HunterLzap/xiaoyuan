import asyncio
import base64
from contextlib import contextmanager
from io import BytesIO
import json
import wave

from fastapi.testclient import TestClient
import httpx
import pytest

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.settings_store import SettingsStore
from backend.app.tts import MiMoTTSProvider
from test_api import Gateway, HEADERS, draft, isolate_environment


def wav_sample():
    buffer = BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24000)
        output.writeframes(b"\x01\x00" * 2400)
    return buffer.getvalue()


def speech_response():
    return {"choices": [{"message": {"audio": {"data": base64.b64encode(wav_sample()).decode()}}}]}


def tts_draft(**changes):
    return {"tts_base_url": "https://tokendance.space/gateway/v1", "tts_model": "mimo-v2.5-tts",
            "tts_voice": "冰糖", "tts_instruction": "自然温柔", "tts_timeout_seconds": 30} | changes


@contextmanager
def running_tts(tmp_path, outcomes=None):
    settings = Settings(_env_file=None, api_key="text-secret", model="text-model", tts_use_text_connection=False,
                        history_db_path=tmp_path / "history.sqlite3", usage_log_path=tmp_path / "usage.jsonl")
    text_gateway = Gateway()
    speech_gateway = Gateway(outcomes or [speech_response()])
    def tts_factory(config):
        return MiMoTTSProvider(config, httpx.AsyncClient(transport=httpx.MockTransport(speech_gateway.handle)))
    app = create_app(settings, settings_store=SettingsStore(tmp_path / ".env"),
                     provider_factory=text_gateway.factory, tts_factory=tts_factory)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        yield client, speech_gateway, text_gateway, app


def test_separate_saves_keep_keys_history_usage_and_restore_both_configs(tmp_path):
    with running_tts(tmp_path) as (client, speech, text, app):
        sid = client.post("/chat", json={"message": "preserve history"}).json()["session_id"]
        before = client.get(f"/sessions/{sid}").json()
        usage = client.get("/usage").json()
        provider = app.state.service.provider
        response = client.put("/api/settings/tts", json=tts_draft(tts_api_key="speech-secret"), headers=HEADERS)
        assert response.status_code == 200 and "speech-secret" not in response.text
        assert app.state.service.provider is provider
        assert client.get("/usage").json() == usage
        assert client.get(f"/sessions/{sid}").json() == before
        assert client.put("/api/settings", json=draft(model="new-text", api_key="new-text-key"), headers=HEADERS).status_code == 200
        assert client.put("/api/settings/tts", json=tts_draft(tts_voice="茉莉"), headers=HEADERS).status_code == 200
        assert client.get("/api/settings/tts").json()["tts_voice"] == "茉莉"
        assert client.get(f"/sessions/{sid}").json() == before
        preview = client.post("/api/settings/tts/preview", json={"config": tts_draft(), "text": "你好"}, headers=HEADERS)
        assert preview.status_code == 200 and preview.content == wav_sample()
        assert speech.requests[-1].headers["authorization"] == "Bearer speech-secret"
        assert client.post("/chat", json={"message": "continue", "session_id": sid}).status_code == 200
        assert text.requests[-1].headers["authorization"] == "Bearer new-text-key"
        assert "speech-secret" not in client.get("/api/settings/tts").text
        assert "speech-secret" not in client.get("/api/settings").text
    saved = Settings(_env_file=tmp_path / ".env")
    assert saved.tts_api_key.get_secret_value() == "speech-secret"
    assert saved.api_key.get_secret_value() == "new-text-key"
    assert saved.model == "new-text" and saved.tts_voice == "茉莉"


@pytest.mark.parametrize("model", ["mimo-v2.5-tts", "mimo-v2.5-tts-voicedesign"])
def test_draft_wav_contract_never_saves_or_uses_text_key(tmp_path, model):
    with running_tts(tmp_path) as (client, speech, text, _):
        before = client.get("/usage").json()
        payload = tts_draft(tts_model=model, tts_api_key="draft-speech-key")
        response = client.post("/api/settings/tts/preview", json={"config": payload, "text": "只朗读这句话"}, headers=HEADERS)
        assert response.status_code == 200 and response.headers["content-type"] == "audio/wav"
        assert response.headers["cache-control"] == "no-store"
        with wave.open(BytesIO(response.content)) as audio:
            assert audio.getnframes() == 2400
        request = speech.requests[0]
        assert str(request.url) == "https://tokendance.space/gateway/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer draft-speech-key"
        body = json.loads(request.content)
        assert body["messages"] == [{"role": "user", "content": "自然温柔"}, {"role": "assistant", "content": "只朗读这句话"}]
        assert body["audio"] == ({"format": "wav", "voice": "冰糖"} if model == "mimo-v2.5-tts" else {"format": "wav"})
        assert body["stream"] is False and "max_tokens" not in body
        assert not text.requests and not (tmp_path / ".env").exists()
        assert client.get("/sessions").json() == [] and client.get("/usage").json() == before
        assert not (tmp_path / "usage.jsonl").exists()


@pytest.mark.parametrize("outcome,code", [
    ((401, {"error": {"message": "speech-secret"}}), "tts_auth"),
    ((429, {}), "tts_rate_limit"),
    ((500, {"error": {"message": "speech-secret"}}), "tts_upstream_error"),
    (httpx.ReadTimeout("speech-secret"), "tts_timeout"),
    (httpx.ConnectError("speech-secret"), "tts_connection"),
    ({"choices": []}, "tts_invalid_audio"),
    ({"choices": [{"message": {"audio": {"data": "!!!!"}}}]}, "tts_invalid_audio"),
])
def test_synthesis_errors_are_redacted_no_retry_no_save(tmp_path, outcome, code):
    with running_tts(tmp_path, [outcome]) as (client, speech, _, _):
        response = client.post("/api/settings/tts/preview", json={"config": tts_draft(tts_api_key="speech-secret"), "text": "你好"}, headers=HEADERS)
        assert response.json()["detail"]["code"] == code and "speech-secret" not in response.text
        assert len(speech.requests) == 1 and not (tmp_path / ".env").exists()


def test_missing_key_description_address_and_origin_are_checked_before_synthesis(tmp_path):
    with running_tts(tmp_path) as (client, speech, _, _):
        payload = {"config": tts_draft(), "text": "你好"}
        assert client.post("/api/settings/tts/preview", json=payload, headers=HEADERS).json()["detail"]["code"] == "tts_not_configured"
        payload["config"].update(tts_api_key="speech-secret", tts_model="mimo-v2.5-tts-voicedesign", tts_instruction=" ")
        assert client.post("/api/settings/tts/preview", json=payload, headers=HEADERS).json()["detail"]["code"] == "tts_voice_description_required"
        assert client.post("/api/settings/tts/preview", json=payload).status_code == 403
        assert client.put("/api/settings/tts", json=tts_draft(tts_api_key="speech-secret"), headers=HEADERS).status_code == 200
        payload["config"] = tts_draft(tts_base_url="https://new.example/v1")
        assert client.post("/api/settings/tts/preview", json=payload, headers=HEADERS).json()["detail"]["code"] == "key_required_for_new_url"
        assert not speech.requests


def test_tts_models_cannot_be_tested_as_text(tmp_path):
    with running_tts(tmp_path) as (client, speech, text, _):
        response = client.post("/api/settings/test", json=draft(model="mimo-v2.5-tts"), headers=HEADERS)
        assert response.status_code == 422 and response.json()["detail"]["code"] == "tts_model_in_text"
        assert not speech.requests and not text.requests


def test_tts_save_failure_or_environment_override_preserves_both_configs(tmp_path, monkeypatch):
    with running_tts(tmp_path) as (client, speech, _, _):
        assert client.put("/api/settings/tts", json=tts_draft(tts_api_key="original-key"), headers=HEADERS).status_code == 200
        before = (tmp_path / ".env").read_bytes()
        with monkeypatch.context() as patch:
            patch.setenv("AI_TTS_VOICE", "Mia")
            assert client.put("/api/settings/tts", json=tts_draft(tts_voice="Mia"), headers=HEADERS).status_code == 409
        with monkeypatch.context() as patch:
            def fail(*args):
                raise OSError("denied")
            patch.setattr("backend.app.settings_store.os.replace", fail)
            assert client.put("/api/settings/tts", json=tts_draft(tts_api_key="changed-key"), headers=HEADERS).status_code == 500
        assert (tmp_path / ".env").read_bytes() == before
        assert client.get("/api/settings").json()["model"] == "text-model"
        assert client.post("/api/settings/tts/preview", json={"config": tts_draft(), "text": "你好"}, headers=HEADERS).status_code == 200
        assert speech.requests[-1].headers["authorization"] == "Bearer original-key"


def test_inflight_preview_does_not_block_save_or_mix_snapshots(tmp_path):
    async def check():
        started, release = asyncio.Event(), asyncio.Event()
        captured = []
        async def gateway(request):
            captured.append(request)
            started.set()
            await release.wait()
            return httpx.Response(200, json=speech_response())
        def factory(config):
            return MiMoTTSProvider(config, httpx.AsyncClient(transport=httpx.MockTransport(gateway)))
        app = create_app(Settings(_env_file=None, usage_log_path=None, history_db_path=None),
                         settings_store=SettingsStore(tmp_path / ".env"), tts_factory=factory)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 50000)), base_url="http://127.0.0.1") as client:
                payload = {"config": tts_draft(tts_api_key="snapshot-key"), "text": "你好"}
                preview = asyncio.create_task(client.post("/api/settings/tts/preview", json=payload, headers=HEADERS))
                await asyncio.wait_for(started.wait(), 2)
                try:
                    assert (await client.post("/api/settings/tts/preview", json=payload, headers=HEADERS)).status_code == 409
                    saved = await asyncio.wait_for(client.put("/api/settings/tts", json=tts_draft(tts_api_key="new-key", tts_voice="茉莉"), headers=HEADERS), 2)
                    assert saved.status_code == 200
                finally:
                    release.set()
                assert (await preview).status_code == 200
                assert captured[0].headers["authorization"] == "Bearer snapshot-key"
                assert json.loads(captured[0].content)["audio"]["voice"] == "冰糖"
    asyncio.run(check())
