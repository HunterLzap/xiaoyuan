import asyncio
from contextlib import contextmanager
from decimal import Decimal
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.llm import Completion, OpenAICompatibleProvider
from backend.app.main import create_app
from backend.app.schemas import ChatRequest
from backend.app.service import ChatService
from backend.app.settings_store import SettingsStore

HEADERS = {"X-Local-Settings": "1", "Origin": "http://127.0.0.1"}


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch):
    import os
    for key in list(os.environ):
        if key.startswith("AI_"):
            monkeypatch.delenv(key)


def completion(reply="你好", usage=True):
    data = {"id": "mock-1", "object": "chat.completion", "created": 1,
            "model": "test-model", "choices": [{"index": 0, "message": {
                "role": "assistant", "content": reply}, "finish_reason": "stop"}]}
    if usage:
        data["usage"] = {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}
    return data


class Gateway:
    def __init__(self, outcomes=None):
        self.outcomes = list(outcomes or [])
        self.requests = []

    def handle(self, request):
        self.requests.append(request)
        outcome = self.outcomes.pop(0) if self.outcomes else completion()
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, tuple):
            return httpx.Response(outcome[0], json=outcome[1])
        return httpx.Response(200, json=outcome)

    def factory(self, settings):
        return OpenAICompatibleProvider(settings, httpx.AsyncClient(transport=httpx.MockTransport(self.handle)))


@contextmanager
def running(tmp_path, outcomes=None, **overrides):
    config = Settings(_env_file=None, **({"api_key": "test-secret", "model": "test-model",
                      "usage_log_path": tmp_path / "usage.jsonl",
                      "history_db_path": tmp_path / "conversations.sqlite3"} | overrides))
    gateway = Gateway(outcomes)
    app = create_app(config, settings_store=SettingsStore(tmp_path / ".env"), provider_factory=gateway.factory)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        yield client, gateway, app


def draft(**overrides):
    return {"provider": "tokendance", "base_url": "https://tokendance.space/gateway/v1",
            "model": "test-model", "max_tokens": 512, "timeout_seconds": 30} | overrides


def test_sdk_http_contract_context_and_session_isolation(tmp_path):
    with running(tmp_path) as (client, gateway, app):
        first = client.post("/chat", json={"message": "我叫小丹"}).json()
        second = client.post("/chat", json={"message": "我叫什么？", "session_id": first["session_id"]})
        assert second.status_code == 200
        assert second.json()["session_usage"]["total_tokens"] == 28
        request = gateway.requests[1]
        assert str(request.url) == "https://tokendance.space/gateway/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-secret"
        body = json.loads(request.content)
        assert body["model"] == "test-model" and body["max_tokens"] == 512 and not body["stream"]
        assert [m["role"] for m in body["messages"]] == ["system", "user", "assistant", "user"]
        assert body["messages"][1]["content"] == "我叫小丹"
        client.post("/chat", json={"message": "独立对话"})
        assert len(json.loads(gateway.requests[2].content)["messages"]) == 2
        assert client.get("/usage").json()["totals"]["total_tokens"] == 42
        assert client.get("/health").json()["upstream_verified"]


def test_cost_and_usage_journal_do_not_contain_secrets_or_text(tmp_path):
    with running(tmp_path, input_price_per_million="2", output_price_per_million="4") as (client, _, _):
        data = client.post("/chat", json={"message": "private-message"}).json()
        assert Decimal(data["estimated_cost"]) == Decimal("0.000036")
        assert client.get("/usage").json()["totals"]["calls_with_cost_estimate"] == 1
    journal = (tmp_path / "usage.jsonl").read_text(encoding="utf-8")
    assert "test-secret" not in journal and "private-message" not in journal and "你好" not in journal
    assert json.loads(journal)["usage"]["total_tokens"] == 14


def test_unreported_usage_and_unconfigured_prices_are_unknown(tmp_path):
    with running(tmp_path, [completion(usage=False), completion()]) as (client, _, _):
        data = client.post("/chat", json={"message": "hello"}).json()
        assert data["usage"] is None and data["estimated_cost"] is None
        data = client.post("/chat", json={"message": "hello"}).json()
        assert data["estimated_cost"] is None
        totals = client.get("/usage").json()["totals"]
        assert totals["calls_without_complete_usage"] == 1
        assert totals["calls_without_cost_estimate"] == 2
        assert totals["total_tokens"] == 14


@pytest.mark.parametrize("upstream,status,code", [
    (401, 502, "upstream_auth"), (429, 503, "upstream_rate_limit"),
    (500, 502, "upstream_error"), (400, 502, "upstream_error"),
])
def test_upstream_failures_are_sanitized_and_not_retried(tmp_path, upstream, status, code):
    with running(tmp_path, [(upstream, {"error": {"message": "test-secret"}})]) as (client, gateway, _):
        response = client.post("/chat", json={"message": "hello"})
        assert response.status_code == status and response.json()["detail"]["code"] == code
        assert "test-secret" not in response.text
        assert len(gateway.requests) == 1
        stats = client.get("/usage").json()
        assert stats["active_sessions"] == 0 and stats["totals"]["failed_calls"] == 1


def test_timeout_and_failed_turn_do_not_pollute_context(tmp_path):
    with running(tmp_path, [completion(), httpx.ReadTimeout("test-secret"), completion()]) as (client, gateway, _):
        first = client.post("/chat", json={"message": "keep"}).json()
        response = client.post("/chat", json={"session_id": first["session_id"], "message": "failed-turn"})
        assert response.status_code == 504
        assert "test-secret" not in response.text
        response = client.post("/chat", json={"session_id": first["session_id"], "message": "next"})
        assert response.status_code == 200
        assert "failed-turn" not in gateway.requests[2].content.decode()
        assert response.json()["session_usage"]["calls"] == 3


def test_empty_reply_still_records_reported_billable_tokens(tmp_path):
    with running(tmp_path, [completion(reply="")]) as (client, _, _):
        assert client.post("/chat", json={"message": "hello"}).status_code == 502
        totals = client.get("/usage").json()["totals"]
        assert totals["failed_calls"] == 1 and totals["total_tokens"] == 14


def test_limits_deletion_and_unknown_session(tmp_path):
    with running(tmp_path, history_turns=1, max_sessions=1) as (client, gateway, _):
        for message in ("", "   ", "a" * 4001):
            assert client.post("/chat", json={"message": message}).status_code == 422
        assert client.post("/chat", json={"message": "hello", "session_id": str(uuid4())}).status_code == 404
        sid = client.post("/chat", json={"message": "one"}).json()["session_id"]
        for message in ("two", "three"):
            assert client.post("/chat", json={"message": message, "session_id": sid}).status_code == 200
        assert len(json.loads(gateway.requests[-1].content)["messages"]) == 4
        assert "one" not in gateway.requests[-1].content.decode()
        assert client.post("/chat", json={"message": "new"}).status_code == 429
        assert client.delete(f"/sessions/{sid}").status_code == 204
        assert client.post("/chat", json={"message": "new"}).status_code == 200


def test_missing_credentials_can_start_and_open_configuration(tmp_path):
    with running(tmp_path, api_key="", model="") as (client, gateway, _):
        health = client.get("/health").json()
        assert health["status"] == "ok" and not health["configured"] and not health["upstream_verified"]
        assert client.get("/settings").status_code == 200
        assert client.get("/docs").status_code == 200
        assert client.post("/chat", json={"message": "hello"}).status_code == 503
        assert not gateway.requests


def test_settings_save_preserves_key_reload_and_applies_without_restart(tmp_path):
    with running(tmp_path, api_key="", model="") as (client, gateway, _):
        response = client.put("/api/settings", json=draft(api_key="saved-secret"), headers=HEADERS)
        assert response.status_code == 200 and response.json()["api_key_configured"]
        assert "saved-secret" not in response.text
        assert "saved-secret" not in client.get("/api/settings").text
        assert client.put("/api/settings", json=draft(model="another-model"), headers=HEADERS).status_code == 200
        assert client.post("/chat", json={"message": "hello"}).status_code == 200
        assert gateway.requests[-1].headers["authorization"] == "Bearer saved-secret"
        assert json.loads(gateway.requests[-1].content)["model"] == "another-model"
    reloaded = Settings(_env_file=tmp_path / ".env")
    assert reloaded.api_key.get_secret_value() == "saved-secret" and reloaded.model == "another-model"


def test_draft_connection_test_does_not_save_or_change_chat_stats(tmp_path):
    with running(tmp_path) as (client, gateway, _):
        response = client.post("/api/settings/test", json=draft(api_key="draft-secret", model="draft-model"), headers=HEADERS)
        assert response.status_code == 200 and response.json()["usage"]["total_tokens"] == 14
        assert "draft-secret" not in response.text
        assert not (tmp_path / ".env").exists()
        assert client.get("/api/settings").json()["model"] == "test-model"
        assert client.get("/usage").json()["totals"]["calls"] == 0
        assert gateway.requests[0].headers["authorization"] == "Bearer draft-secret"


def test_settings_guard_validation_and_environment_precedence(tmp_path, monkeypatch):
    with running(tmp_path) as (client, _, _):
        assert client.put("/api/settings", json=draft()).status_code == 403
        assert client.put("/api/settings", json=draft(), headers=HEADERS | {"Origin": "https://evil.example"}).status_code == 403
        assert client.get("/api/settings", headers={"Host": "evil.example"}).status_code == 400
        response = client.put("/api/settings", json=draft(api_key="private-key", max_tokens=0), headers=HEADERS)
        assert response.status_code == 422 and "private-key" not in response.text
        response = client.put("/api/settings", json=draft(base_url="https://secret@api.example/v1"), headers=HEADERS)
        assert response.status_code == 422 and "secret" not in response.text
        monkeypatch.setenv("AI_MODEL", "environment-model")
        assert client.put("/api/settings", json=draft(), headers=HEADERS).status_code == 409
        assert not (tmp_path / ".env").exists()


def test_remote_settings_access_is_denied(tmp_path):
    app = create_app(Settings(_env_file=None, usage_log_path=None, history_db_path=None))
    with TestClient(app, base_url="http://127.0.0.1", client=("192.168.1.5", 50000)) as client:
        assert client.get("/api/settings").status_code == 403
        assert client.get("/settings").status_code == 403


def test_same_session_concurrent_messages_see_committed_previous_turn():
    class Provider:
        def __init__(self):
            self.messages = []
        async def complete(self, messages):
            self.messages.append(messages)
            await asyncio.sleep(0.01)
            return Completion("reply", None, "stop")
        async def close(self):
            pass
    async def scenario():
        provider = Provider()
        service = ChatService(Settings(_env_file=None, usage_log_path=None), provider)
        first = await service.chat(ChatRequest(message="first"))
        await asyncio.gather(*[
            service.chat(ChatRequest(message=message, session_id=first.session_id))
            for message in ("second", "third")
        ])
        assert len(provider.messages[-1]) == 6
        assert provider.messages[-1][-3]["content"] == "second"
        assert service.usage.successful_calls == 3
    asyncio.run(scenario())


def test_full_transcript_survives_restart_and_context_remains_bounded(tmp_path):
    with running(tmp_path, history_turns=1) as (client, _, _):
        sid = client.post("/chat", json={"message": "第一轮"}).json()["session_id"]
        for message in ("第二轮", "第三轮"):
            assert client.post("/chat", json={"message": message, "session_id": sid}).status_code == 200
        detail = client.get(f"/sessions/{sid}").json()
        assert detail["message_count"] == 6 and detail["messages"][0]["content"] == "第一轮"
        assert detail["history_persisted"]
        assert detail["messages"][1]["usage"]["total_tokens"] == 14
        assert client.get("/sessions").json()[0]["session_id"] == sid
    with running(tmp_path, history_turns=1) as (client, gateway, _):
        assert client.get(f"/sessions/{sid}").json()["message_count"] == 6
        assert client.get("/usage").json()["totals"]["calls"] == 0
        assert client.post("/chat", json={"message": "继续", "session_id": sid}).status_code == 200
        messages = json.loads(gateway.requests[0].content)["messages"]
        assert len(messages) == 4 and messages[1]["content"] == "第三轮"
        assert client.get(f"/sessions/{sid}").json()["message_count"] == 8


def test_rename_configuration_change_and_delete_preserve_correct_history(tmp_path):
    with running(tmp_path) as (client, gateway, _):
        sid = client.post("/chat", json={"message": "原始问题"}).json()["session_id"]
        response = client.patch(f"/sessions/{sid}", json={"title": "我的计划"})
        assert response.status_code == 200 and response.json()["title"] == "我的计划"
        assert client.patch(f"/sessions/{sid}", json={"title": "   "}).status_code == 422
        assert client.put("/api/settings", json=draft(model="updated-model"), headers=HEADERS).status_code == 200
        detail = client.get(f"/sessions/{sid}").json()
        assert detail["title"] == "我的计划" and detail["message_count"] == 2
        assert client.post("/chat", json={"message": "继续", "session_id": sid}).status_code == 200
        assert json.loads(gateway.requests[-1].content)["messages"][1]["content"] == "原始问题"
    with running(tmp_path) as (client, _, _):
        assert client.get(f"/sessions/{sid}").json()["title"] == "我的计划"
        assert client.delete(f"/sessions/{sid}").status_code == 204
    with running(tmp_path) as (client, _, _):
        assert client.get("/sessions").json() == []
        assert client.get(f"/sessions/{sid}").status_code == 404


def test_history_write_failure_keeps_paid_reply_and_recovers_snapshot(tmp_path, monkeypatch):
    import sqlite3
    with running(tmp_path) as (client, _, app):
        store = app.state.service.history_store
        save = store.save
        def fail(record):
            raise sqlite3.OperationalError("disk full")
        monkeypatch.setattr(store, "save", fail)
        response = client.post("/chat", json={"message": "已计费的消息"})
        assert response.status_code == 200 and response.json()["history_persisted"] is False
        sid = response.json()["session_id"]
        assert client.get(f"/sessions/{sid}").json()["message_count"] == 2
        assert client.get("/usage").json()["totals"]["total_tokens"] == 14
        monkeypatch.setattr(store, "save", save)
        assert client.post("/chat", json={"message": "再次保存", "session_id": sid}).json()["history_persisted"]
    with running(tmp_path) as (client, _, _):
        assert client.get(f"/sessions/{sid}").json()["message_count"] == 4


def test_delete_failure_does_not_claim_success_or_forget_history(tmp_path, monkeypatch):
    import sqlite3
    with running(tmp_path) as (client, _, app):
        sid = client.post("/chat", json={"message": "保留"}).json()["session_id"]
        def fail(session_id):
            raise sqlite3.OperationalError("locked")
        monkeypatch.setattr(app.state.service.history_store, "delete", fail)
        assert client.delete(f"/sessions/{sid}").status_code == 500
        assert client.get(f"/sessions/{sid}").status_code == 200
    with running(tmp_path) as (client, _, _):
        assert client.get(f"/sessions/{sid}").status_code == 200
