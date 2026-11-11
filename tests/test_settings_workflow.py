import json

from backend.app.config import Settings
from test_api import HEADERS, isolate_environment
from test_tts import running_tts


def connections(**changes):
    return {"base_url": "https://tokendance.space/gateway/v1", "api_key": "new-text-key",
            "tts_base_url": "https://tokendance.space/gateway/v1", "tts_api_key": "new-voice-key"} | changes


def selection(**changes):
    return {"model": "chosen-text-model", "tts_model": "mimo-v2.5-tts", "tts_voice": "茉莉", "tts_instruction": "自然"} | changes


def test_api_setup_then_daily_selection_preserves_credentials_and_history(tmp_path):
    with running_tts(tmp_path) as (client, speech, text, _):
        sid = client.post("/chat", json={"message": "keep"}).json()["session_id"]
        history = client.get(f"/sessions/{sid}").json()
        response = client.put("/api/settings/connections", json=connections(), headers=HEADERS)
        assert response.status_code == 200 and response.json()["text"]["model"] == "text-model"
        assert response.json()["tts"]["tts_voice"] == "mimo_default"
        assert "new-text-key" not in response.text and "new-voice-key" not in response.text
        assert len(text.requests) == 1 and not speech.requests
        response = client.put("/api/settings/assistant", json=selection(), headers=HEADERS)
        assert response.status_code == 200 and response.json()["text"]["model"] == "chosen-text-model"
        assert response.json()["tts"]["tts_voice"] == "茉莉"
        assert client.get(f"/sessions/{sid}").json() == history
        assert client.post("/chat", json={"message": "continue", "session_id": sid}).status_code == 200
        assert text.requests[-1].headers["authorization"] == "Bearer new-text-key"
        assert json.loads(text.requests[-1].content)["model"] == "chosen-text-model"
    config = Settings(_env_file=tmp_path / ".env")
    assert config.api_key.get_secret_value() == "new-text-key"
    assert config.tts_api_key.get_secret_value() == "new-voice-key"
    assert config.model == "chosen-text-model" and config.tts_voice == "茉莉"


def test_grouped_endpoints_reject_cross_group_fields_and_invalid_voice_atomically(tmp_path):
    with running_tts(tmp_path) as (client, _, _, _):
        assert client.put("/api/settings/connections", json=connections(), headers=HEADERS).status_code == 200
        before = (tmp_path / ".env").read_bytes()
        assert client.put("/api/settings/assistant", json=selection(api_key="wrong-group"), headers=HEADERS).status_code == 422
        assert client.put("/api/settings/connections", json=connections(model="wrong-group"), headers=HEADERS).status_code == 422
        assert client.put("/api/settings/assistant", json=selection(tts_model="mimo-v2.5-tts-voicedesign", tts_instruction=""), headers=HEADERS).status_code == 422
        assert (tmp_path / ".env").read_bytes() == before
        assert client.get("/api/settings").json()["model"] == "text-model"


def test_connection_save_keeps_existing_selection_and_requires_keys_for_new_addresses(tmp_path):
    with running_tts(tmp_path) as (client, _, _, _):
        assert client.put("/api/settings/connections", json=connections(), headers=HEADERS).status_code == 200
        assert client.put("/api/settings/assistant", json=selection(), headers=HEADERS).status_code == 200
        response = client.put("/api/settings/connections", json=connections(api_key=None, tts_api_key=None), headers=HEADERS)
        assert response.status_code == 200 and response.json()["text"]["model"] == "chosen-text-model"
        assert response.json()["tts"]["tts_voice"] == "茉莉"
        response = client.put("/api/settings/connections", json=connections(api_key=None, base_url="https://other.example/v1"), headers=HEADERS)
        assert response.json()["detail"]["code"] == "key_required_for_new_url"
        assert client.put("/api/settings/assistant", json=selection()).status_code == 403


def test_group_save_failure_preserves_previous_state(tmp_path, monkeypatch):
    with running_tts(tmp_path) as (client, _, _, _):
        assert client.put("/api/settings/connections", json=connections(), headers=HEADERS).status_code == 200
        before = (tmp_path / ".env").read_bytes()
        def fail(*args):
            raise OSError("denied")
        monkeypatch.setattr("backend.app.settings_store.os.replace", fail)
        response = client.put("/api/settings/assistant", json=selection(), headers=HEADERS)
        assert response.status_code == 500
        assert client.get("/api/settings").json()["model"] == "text-model"
        assert client.get("/api/settings/tts").json()["tts_voice"] == "mimo_default"
        assert (tmp_path / ".env").read_bytes() == before


def test_shared_connection_configure_once_synthesize_and_rotate_key(tmp_path):
    from test_tts import speech_response, tts_draft
    with running_tts(tmp_path, [speech_response(), speech_response()]) as (client, speech, _, _):
        response = client.put("/api/settings/connections", json={
            "base_url": "https://tokendance.space/gateway/v1", "api_key": "shared-key",
            "tts_use_text_connection": True,
        }, headers=HEADERS)
        assert response.status_code == 200
        assert response.json()["tts"]["use_text_connection"] is True
        assert response.json()["tts"]["api_key_configured"] is True
        assert "shared-key" not in response.text
        payload = {"config": tts_draft(), "text": "你好"}
        assert client.post("/api/settings/tts/preview", json=payload, headers=HEADERS).status_code == 200
        assert speech.requests[-1].headers["authorization"] == "Bearer shared-key"
        assert client.put("/api/settings/connections", json={
            "base_url": "https://tokendance.space/gateway/v1", "api_key": "rotated-key",
            "tts_use_text_connection": True,
        }, headers=HEADERS).status_code == 200
        assert client.post("/api/settings/tts/preview", json=payload, headers=HEADERS).status_code == 200
        assert speech.requests[-1].headers["authorization"] == "Bearer rotated-key"
    saved = Settings(_env_file=tmp_path / ".env")
    assert saved.shared_tts_connection and saved.effective_tts_api_key.get_secret_value() == "rotated-key"
    assert "AI_TTS_API_KEY=" not in (tmp_path / ".env").read_text()


def test_separate_service_does_not_inherit_shared_key_and_switch_back_keeps_private_config(tmp_path):
    from test_tts import speech_response, tts_draft
    with running_tts(tmp_path, [speech_response(), speech_response()]) as (client, speech, _, _):
        common = {"base_url": "https://tokendance.space/gateway/v1", "api_key": "shared-key"}
        assert client.put("/api/settings/connections", json=common | {
            "tts_use_text_connection": False, "tts_base_url": "https://voice.example/v1",
        }, headers=HEADERS).status_code == 200
        payload = {"config": tts_draft(tts_base_url="https://voice.example/v1"), "text": "你好"}
        assert client.post("/api/settings/tts/preview", json=payload, headers=HEADERS).json()["detail"]["code"] == "tts_not_configured"
        assert client.put("/api/settings/connections", json=common | {
            "tts_use_text_connection": False, "tts_base_url": "https://voice.example/v1", "tts_api_key": "separate-key",
        }, headers=HEADERS).status_code == 200
        assert client.post("/api/settings/tts/preview", json=payload, headers=HEADERS).status_code == 200
        assert str(speech.requests[-1].url) == "https://voice.example/v1/chat/completions"
        assert speech.requests[-1].headers["authorization"] == "Bearer separate-key"
        assert client.put("/api/settings/connections", json=common | {"tts_use_text_connection": True}, headers=HEADERS).status_code == 200
        assert client.post("/api/settings/tts/preview", json=payload, headers=HEADERS).status_code == 200
        assert str(speech.requests[-1].url) == "https://tokendance.space/gateway/v1/chat/completions"
        assert speech.requests[-1].headers["authorization"] == "Bearer shared-key"
        assert Settings(_env_file=tmp_path / ".env").tts_api_key.get_secret_value() == "separate-key"


def test_shared_default_and_legacy_separate_credentials():
    assert Settings(_env_file=None).shared_tts_connection
    assert not Settings(_env_file=None, api_key="text", tts_api_key="voice").shared_tts_connection
    assert Settings(_env_file=None, api_key="same", tts_api_key="same").shared_tts_connection


def test_persona_applies_next_turn_preserves_history_usage_and_old_clients(tmp_path):
    persona = "你是小蛋，一个耐心、直率的朋友。回答简短，先给建议。"
    with running_tts(tmp_path) as (client, _, text, app):
        sid = client.post("/chat", json={"message": "hello"}).json()["session_id"]
        history = client.get(f"/sessions/{sid}").json()
        usage = client.get("/usage").json()
        provider = app.state.service.provider
        payload = selection(model="text-model", system_prompt=persona)
        response = client.put("/api/settings/assistant", json=payload, headers=HEADERS)
        assert response.status_code == 200 and response.json()["text"]["system_prompt"] == persona
        assert app.state.service.provider is provider
        assert client.get("/usage").json() == usage
        assert client.get(f"/sessions/{sid}").json() == history
        assert client.post("/chat", json={"message": "continue", "session_id": sid}).status_code == 200
        messages = json.loads(text.requests[-1].content)["messages"]
        assert messages[0] == {"role": "system", "content": persona}
        assert any(message["content"] == "hello" for message in messages)
        assert client.put("/api/settings/assistant", json=selection(model="text-model"), headers=HEADERS).status_code == 200
        assert client.get("/api/settings").json()["system_prompt"] == persona
    assert Settings(_env_file=tmp_path / ".env").system_prompt == persona


def test_persona_invalid_or_failed_save_preserves_active_and_persisted_settings(tmp_path, monkeypatch):
    with running_tts(tmp_path) as (client, _, _, _):
        original = client.get("/api/settings").json()["system_prompt"]
        assert client.put("/api/settings/assistant", json=selection(system_prompt=original), headers=HEADERS).status_code == 200
        before = (tmp_path / ".env").read_bytes()
        for invalid in ("", "   ", "a" * 4001):
            assert client.put("/api/settings/assistant", json=selection(system_prompt=invalid), headers=HEADERS).status_code == 422
        def fail(*args):
            raise OSError("denied")
        monkeypatch.setattr("backend.app.settings_store.os.replace", fail)
        assert client.put("/api/settings/assistant", json=selection(system_prompt="新角色"), headers=HEADERS).status_code == 500
        assert client.get("/api/settings").json()["system_prompt"] == original
        assert (tmp_path / ".env").read_bytes() == before


def test_unified_api_save_is_atomic_and_preserves_history(tmp_path):
    with running_tts(tmp_path) as (client, _, _, _):
        sid = client.post("/chat", json={"message": "keep"}).json()["session_id"]
        history = client.get(f"/sessions/{sid}").json()
        payload = connections() | selection() | {"tts_use_text_connection": True}
        response = client.put("/api/settings/api", json=payload, headers=HEADERS)
        assert response.status_code == 200
        assert response.json()["text"]["model"] == "chosen-text-model"
        assert response.json()["tts"]["tts_voice"] == "茉莉"
        assert "new-text-key" not in response.text
        assert client.get(f"/sessions/{sid}").json() == history
        before = (tmp_path / ".env").read_bytes()
        invalid = payload | {"base_url": "https://other.example/v1", "tts_model": "mimo-v2.5-tts-voicedesign", "tts_instruction": ""}
        assert client.put("/api/settings/api", json=invalid, headers=HEADERS).status_code == 422
        assert (tmp_path / ".env").read_bytes() == before
    saved = Settings(_env_file=tmp_path / ".env")
    assert saved.model == "chosen-text-model" and saved.tts_voice == "茉莉"


def test_preview_uses_unsaved_shared_connection_without_persisting(tmp_path):
    from test_tts import speech_response, tts_draft
    with running_tts(tmp_path, [speech_response()]) as (client, speech, _, _):
        before = client.get("/api/settings").json()
        payload = {"connection": {"base_url": "https://draft.example/v1", "api_key": "draft-only-key", "tts_use_text_connection": True},
                   "config": tts_draft(), "text": "隔离试听"}
        response = client.post("/api/settings/tts/preview", json=payload, headers=HEADERS)
        assert response.status_code == 200
        assert str(speech.requests[-1].url) == "https://draft.example/v1/chat/completions"
        assert speech.requests[-1].headers["authorization"] == "Bearer draft-only-key"
        assert client.get("/api/settings").json() == before
        assert not (tmp_path / ".env").exists()
