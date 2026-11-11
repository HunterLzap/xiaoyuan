import json

import httpx
import pytest

from test_api import HEADERS, completion, draft, running, isolate_environment
from backend.app.config import Settings


def catalog(*models):
    return {"data": [{"id": model, "supported_protocols": ["openai:chat-completions"]}
                     for model in models]}


def test_public_catalog_draft_selection_test_save_and_history_reload(tmp_path):
    listing = catalog("selected-model", "selected-model", "another-model")
    listing["data"].append({"id": "image-only", "supported_protocols": ["openai:image-generations"]})
    with running(tmp_path, [completion(), listing, completion(), completion()]) as (client, gateway, _):
        sid = client.post("/chat", json={"message": "keep history"}).json()["session_id"]
        before = client.get(f"/sessions/{sid}").json()
        payload = draft(model="", api_key="draft-key")
        response = client.post("/api/settings/models", json=payload, headers=HEADERS)
        assert response.status_code == 200
        catalog_body = response.json()
        assert catalog_body["models"] == ["another-model", "selected-model"]
        assert catalog_body["speech_models"] == [] and catalog_body["chat_verified"] is False
        request = gateway.requests[-1]
        assert request.method == "GET" and str(request.url) == "https://tokendance.space/gateway/v1/models"
        assert "authorization" not in request.headers and not request.content
        assert client.get("/api/settings").json()["model"] == "test-model"
        assert client.get("/usage").json()["totals"]["calls"] == 1
        assert not (tmp_path / ".env").exists()
        payload["model"] = "selected-model"
        tested = client.post("/api/settings/test", json=payload, headers=HEADERS)
        assert tested.status_code == 200 and "draft-key" not in tested.text
        assert gateway.requests[-1].headers["authorization"] == "Bearer draft-key"
        assert not (tmp_path / ".env").exists()
        assert client.get(f"/sessions/{sid}").json() == before
        assert client.put("/api/settings", json=payload, headers=HEADERS).status_code == 200
        assert client.get(f"/sessions/{sid}").json() == before
        assert client.post("/chat", json={"message": "continue", "session_id": sid}).status_code == 200
        body = json.loads(gateway.requests[-1].content)
        assert body["model"] == "selected-model" and body["messages"][1]["content"] == "keep history"
        assert "draft-key" not in client.get("/api/settings").text
        assert "draft-key" not in (tmp_path / "usage.jsonl").read_text()
    saved = Settings(_env_file=tmp_path / ".env")
    assert saved.model == "selected-model" and saved.api_key.get_secret_value() == "draft-key"
    with running(tmp_path, model=saved.model, api_key=saved.api_key) as (client, _, _):
        assert client.get(f"/sessions/{sid}").json()["message_count"] == 4


def test_public_catalog_needs_no_key_or_model_and_empty_is_not_verified(tmp_path):
    with running(tmp_path, [catalog()], api_key="", model="") as (client, gateway, _):
        response = client.post("/api/settings/models", json=draft(model=""), headers=HEADERS)
        assert response.status_code == 200 and response.json()["models"] == []
        assert not client.get("/health").json()["upstream_verified"]
        assert "authorization" not in gateway.requests[0].headers


@pytest.mark.parametrize("outcome,code", [
    ((401, {"error": {"message": "test-secret"}}), "models_auth"),
    ((403, {"error": {"message": "test-secret"}}), "models_forbidden"),
    ((404, {}), "models_unsupported"),
    ((405, {}), "models_unsupported"),
    ((429, {}), "models_rate_limit"),
    ((500, {"error": {"message": "test-secret"}}), "models_error"),
    (httpx.ReadTimeout("test-secret"), "models_timeout"),
    (httpx.ConnectError("test-secret"), "models_connection"),
    ({"data": "test-secret"}, "models_invalid_response"),
    ({"data": [{"id": 123}]}, "models_invalid_response"),
])
def test_catalog_errors_are_distinct_redacted_and_do_not_retry_or_save(tmp_path, outcome, code):
    with running(tmp_path, [outcome]) as (client, gateway, _):
        response = client.post("/api/settings/models", json=draft(), headers=HEADERS)
        assert response.status_code >= 400 and response.json()["detail"]["code"] == code
        assert "test-secret" not in response.text
        assert len(gateway.requests) == 1
        assert not (tmp_path / ".env").exists()
        assert client.get("/api/settings").json()["model"] == "test-model"


def test_unknown_list_protocol_is_not_probed_but_explicit_openai_is_supported(tmp_path):
    with running(tmp_path, [{"data": [{"id": "manual-choice"}]}]) as (client, gateway, _):
        payload = draft(base_url="https://api.example/v1", api_key="new-service-key", model="")
        response = client.post("/api/settings/models", json=payload, headers=HEADERS)
        assert response.json()["detail"]["code"] == "models_unsupported" and not gateway.requests
        payload["models_protocol"] = "openai"
        assert client.post("/api/settings/models", json=payload, headers=HEADERS).json()["models"] == ["manual-choice"]
        assert str(gateway.requests[0].url) == "https://api.example/v1/models"
        assert gateway.requests[0].headers["authorization"] == "Bearer new-service-key"
        payload["models_protocol"] = "disabled"
        assert client.post("/api/settings/models", json=payload, headers=HEADERS).json()["detail"]["code"] == "models_unsupported"
        assert len(gateway.requests) == 1


@pytest.mark.parametrize("path,method", [("/api/settings/models", "POST"), ("/api/settings/test", "POST"), ("/api/settings", "PUT")])
def test_changing_url_never_reuses_saved_secret(tmp_path, path, method):
    with running(tmp_path) as (client, gateway, _):
        response = client.request(method, path, json=draft(base_url="https://new.example/v1"), headers=HEADERS)
        assert response.status_code == 422 and response.json()["detail"]["code"] == "key_required_for_new_url"
        assert not gateway.requests and not (tmp_path / ".env").exists()


def test_list_guard_and_invalid_key_do_not_leak_or_call_upstream(tmp_path):
    with running(tmp_path) as (client, gateway, _):
        for headers in [{}, HEADERS | {"Origin": "https://evil.example"}]:
            assert client.post("/api/settings/models", json=draft(), headers=headers).status_code == 403
        response = client.post("/api/settings/models", json=draft(api_key="private-key\ninvalid"), headers=HEADERS)
        assert response.status_code == 422 and "private-key" not in response.text
        assert not gateway.requests


def test_failed_save_keeps_current_configuration_and_persisted_history(tmp_path, monkeypatch):
    with running(tmp_path) as (client, gateway, app):
        sid = client.post("/chat", json={"message": "keep"}).json()["session_id"]
        def fail_replace(*args):
            raise OSError("disk denied")
        monkeypatch.setattr("backend.app.settings_store.os.replace", fail_replace)
        response = client.put("/api/settings", json=draft(api_key="replacement-key", model="changed"), headers=HEADERS)
        assert response.status_code == 500 and response.json()["detail"]["code"] == "config_write_failed"
        assert "replacement-key" not in response.text
        assert client.get("/api/settings").json()["model"] == "test-model"
        assert client.get(f"/sessions/{sid}").json()["message_count"] == 2
        assert client.post("/chat", json={"message": "still working", "session_id": sid}).status_code == 200
        assert gateway.requests[-1].headers["authorization"] == "Bearer test-secret"
        assert not list(tmp_path.glob(".env.*.tmp"))
