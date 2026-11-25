"""Batch 2 & 3 tests: ToolGateway confirmations, TextToolSelection >5 trigger, unified traces, and SQLite business state."""
from __future__ import annotations

import asyncio
import io
import json
import sqlite3
from contextlib import closing
from threading import get_ident
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4
import wave

from dotenv import dotenv_values
from fastapi.testclient import TestClient
import httpx
import pytest

from backend.app import web_search
from backend.app.audit_store import AuditStore
from backend.app.config import Settings
from backend.app.error_log import ErrorLogStore
from backend.app.history_store import HistoryStore
from backend.app.llm import Completion, ProviderError
from backend.app.main import create_app
from backend.app.realtime import RealtimeTurn
from backend.app.schemas import TokenUsage
from backend.app.service import ChatService
from backend.app.settings_store import SettingsStore
from backend.app.text_tool_selection import TextToolSelection
from backend.app.tool_dialogue import TOOL_LOADING_NAME, ToolConversation
from backend.app.tools import ToolRegistry, ToolSpec, build_tool_registry


HEADERS = {"X-Local-Settings": "1", "Origin": "http://127.0.0.1"}


def _wav_bytes() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x01\x00" * 320)
    return buf.getvalue()


class _FakeTool:
    def __init__(self, name: str, permission: str = "read", handler=None):
        self.spec = ToolSpec(
            name=name,
            description=f"Test tool {name}",
            parameters={"type": "object", "properties": {"value": {"type": "string"}}, "additionalProperties": False},
            permission=permission,
        )
        self.handler = handler
        self.calls: list[dict] = []

    async def run(self, arguments: dict, trace=None):
        self.calls.append(arguments)
        if trace is not None:
            trace["request"] = {"arguments": arguments}
            trace["response"] = {"status": 200, "ok": True}
        if self.handler is not None:
            return await self.handler(arguments)
        return {"ok": True, "echo": arguments.get("value", "")}


class _ScriptedProvider:
    def __init__(self, scripts: list[list[str | Completion]]):
        self.scripts = list(scripts)
        self.seen_tools: list[list[str]] = []

    async def complete_stream(self, messages, tools=None):
        self.seen_tools.append([item["function"]["name"] for item in (tools or [])])
        step = self.scripts.pop(0)
        for item in step:
            yield item

    async def close(self):
        return None


def test_tool_gateway_side_effect_confirmation_and_manual_call():
    async def scenario():
        write_tool = _FakeTool("send_notice", permission="write")
        service = ChatService(Settings(_env_file=None, api_key="k", model="m", history_db_path=None, usage_log_path=None), None)
        service.tools = ToolRegistry([write_tool])
        sid = service.new_session()

        # Turn 1: initial invocation -> ask (blocked), tool NOT executed.
        t1 = uuid4()
        ctx1 = service.tool_context(sid, t1, "text", "帮我发送通知 hello")
        ctx1.begin_order_turn("帮我发送通知 hello")
        out1 = await ctx1.execute("send_notice", json.dumps({"value": "hello"}), "call-1")
        assert out1["error"] == "confirmation_required"
        assert write_tool.calls == []

        # Turn 2: user cancels -> denied, tool NOT executed.
        t2 = uuid4()
        ctx2 = service.tool_context(sid, t2, "text", "取消吧")
        ctx2.begin_order_turn("取消吧")
        out2 = await ctx2.execute("send_notice", json.dumps({"value": "hello"}), "call-2")
        assert out2["error"] == "confirmation_denied"
        assert write_tool.calls == []

        # Turn 3: ask again -> Turn 4: user confirms -> executed cleanly.
        t3 = uuid4()
        ctx3 = service.tool_context(sid, t3, "text", "还是发送通知 world")
        ctx3.begin_order_turn("还是发送通知 world")
        out3 = await ctx3.execute("send_notice", json.dumps({"value": "world"}), "call-3")
        assert out3["error"] == "confirmation_required"

        t4 = uuid4()
        ctx4 = service.tool_context(sid, t4, "text", "确认")
        ctx4.begin_order_turn("确认")
        out4 = await ctx4.execute("send_notice", json.dumps({"value": "world"}), "call-4")
        assert out4 == {"ok": True, "echo": "world"}
        assert write_tool.calls == [{"value": "world"}]

        # Manual gateway enforcement without confirmed=True.
        with pytest.raises(ProviderError) as err:
            await service.tool_gateway.execute_manual(service.tools, "send_notice", {"value": "x"}, confirmed=False)
        assert err.value.code == "tool_confirmation_required"

        manual_ok = await service.tool_gateway.execute_manual(service.tools, "send_notice", {"value": "x"}, confirmed=True)
        assert manual_ok["status"] == "ok"
        assert manual_ok["result"] == {"ok": True, "echo": "x"}

    asyncio.run(scenario())


def test_text_tool_selection_only_activates_above_five_tools():
    async def scenario():
        six_tools = [_FakeTool(f"ext_tool_{idx}") for idx in range(6)]
        service = ChatService(Settings(_env_file=None, api_key="k", model="m", history_db_path=None, usage_log_path=None), None)
        service.tools = ToolRegistry(six_tools)
        sid = service.new_session()
        ctx = service.tool_context(sid, uuid4(), "text", "查一下 ext_tool_2")
        ctx.begin_order_turn("查一下 ext_tool_2")

        provider = _ScriptedProvider([
            [Completion("", TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15), "tool_calls",
                        tool_calls=[{"id": "c1", "type": "function", "function": {"name": TOOL_LOADING_NAME, "arguments": json.dumps({"names": ["ext_tool_2"]})}}])],
            [Completion("", TokenUsage(prompt_tokens=12, completion_tokens=4, total_tokens=16), "tool_calls",
                        tool_calls=[{"id": "c2", "type": "function", "function": {"name": "ext_tool_2", "arguments": json.dumps({"value": "ok"})}}])],
            ["已查到 ext_tool_2 结果。", Completion("已查到 ext_tool_2 结果。", TokenUsage(prompt_tokens=14, completion_tokens=6, total_tokens=20), "stop", tool_calls=[])],
        ])
        conv = ToolConversation(provider, ctx)
        result = await conv.complete([{"role": "system", "content": "sys"}, {"role": "user", "content": "查一下 ext_tool_2"}])
        assert result.reply == "已查到 ext_tool_2 结果。"
        assert provider.seen_tools[0] == [TOOL_LOADING_NAME]
        assert "ext_tool_2" in provider.seen_tools[1]
        assert six_tools[2].calls == [{"value": "ok"}]

        # <= 5 tools exposes tools directly without _load_task_tools.
        three_tools = [_FakeTool(f"small_{idx}") for idx in range(3)]
        service.tools = ToolRegistry(three_tools)
        ctx_small = service.tool_context(sid, uuid4(), "text", "用 small_1")
        provider_small = _ScriptedProvider([["直接完成", Completion("直接完成", None, "stop", tool_calls=[])]])
        await ToolConversation(provider_small, ctx_small).complete([{"role": "system", "content": "sys"}, {"role": "user", "content": "用 small_1"}])
        assert provider_small.seen_tools[0] == ["small_0", "small_1", "small_2"]

    asyncio.run(scenario())


def test_unified_traces_and_sqlite_business_state(tmp_path, monkeypatch):
    # Pre-populate env overrides for business settings to prove SQLite state ignores 409 conflict.
    monkeypatch.setenv("AI_EMBEDDING_ENABLED", "true")
    monkeypatch.setenv("AI_SELECTED_TOOL_IDS", '["get_weather"]')
    monkeypatch.setenv("AI_TTS_RATE", "1.0")

    async def _async_val(v):
        return v

    class _FakeTTS:
        async def synthesize_stream(self, text: str):
            yield b"\x00\x01" * 100

        async def synthesize(self, text: str) -> bytes:
            return b"RIFF...."

        async def close(self) -> None:
            return None

    monkeypatch.setattr(
        "backend.app.main.transcribe_browser_wav",
        lambda config, wav, speech=None: _async_val({"text": "语音提问天气", "asr_provider": "openai", "model": "whisper-1"}),
    )

    class _FakeLLM:
        def __init__(self):
            self.closed = False

        async def complete_stream(self, messages, tools=None):
            yield "文字回答完毕。"
            yield Completion("文字回答完毕。", TokenUsage(prompt_tokens=20, completion_tokens=8, total_tokens=28), "stop", tool_calls=[])

        async def close(self):
            self.closed = True

    def _make_cfg():
        return Settings(
            _env_file=None,
            voice_mode="pipeline",
            api_key="test-key",
            model="test-chat-model",
            asr_provider="openai",
            asr_api_key="test-asr-key",
            tts_provider="openai",
            tts_api_key="test-tts-key",
            tts_model="tts-1",
            tts_voice="alloy",
            m5stack_enabled=False,
            personal_kb_enabled=True,
            usage_log_path=None,
            history_db_path=tmp_path / "conversations.sqlite3",
            personal_kb_db_path=tmp_path / "personal_kb.sqlite3",
            assistant_db_path=tmp_path / "assistant_state.sqlite3",
        )

    env_path = tmp_path / ".env"
    app = create_app(
        _make_cfg(),
        settings_store=SettingsStore(env_path),
        provider_factory=lambda cfg: _FakeLLM(),
        tts_factory=lambda cfg: _FakeTTS(),
    )

    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        # 1. Business settings survive env overrides without writing .env or throwing 409.
        cap_res = client.put(
            "/api/settings/capabilities",
            json={"m5stack_enabled": False, "personal_kb_enabled": True, "weather_enabled": False, "embedding_enabled": False},
            headers=HEADERS,
        )
        assert cap_res.status_code == 200
        assert cap_res.json()["text"]["embedding_enabled"] is False
        assert cap_res.json()["text"]["weather_enabled"] is False

        sel_res = client.put("/api/assistant/selection", json={"selected_tool_ids": []}, headers=HEADERS)
        assert sel_res.status_code == 200
        assert sel_res.json()["selected_tool_ids"] == []

        # 2. Manual tool execution via ToolGateway checks permission & records audit.
        manual_tool = _FakeTool("manual_write_check", permission="write")
        app.state.resource_tools = app.state.resource_tools.with_tool(manual_tool)
        blocked_call = client.post("/api/tools/manual_write_check/call", json={"arguments": {"value": "1"}, "confirmed": False}, headers=HEADERS)
        assert blocked_call.status_code == 409
        ok_call = client.post("/api/tools/manual_write_check/call", json={"arguments": {"value": "1"}, "confirmed": True}, headers=HEADERS)
        assert ok_call.status_code == 200
        assert ok_call.json() == {"ok": True, "echo": "1"}
        assert not env_path.exists()

        # 3. Text chat -> creates turn_traces entry.
        chat_res = client.post("/chat", json={"message": "你好，做个测试"})
        assert chat_res.status_code == 200
        session_id = chat_res.json()["session_id"]

        # 4. Browser voice ASR + pipeline voice turn -> creates web_voice pipeline turn_traces entry.
        rec_res = client.post(
            "/api/voice/asr",
            content=_wav_bytes(),
            headers=HEADERS,
        )
        assert rec_res.status_code == 200
        assert rec_res.json()["text"] == "语音提问天气"

        voice_res = client.post(
            "/api/voice/turn",
            json={"text": "语音提问天气", "session_id": session_id},
            headers=HEADERS,
        )
        assert voice_res.status_code == 200

        # 5. RealtimeTurn.persist -> delegates to commit_external_turn inside portal event loop.
        async def _persist_realtime():
            rt = RealtimeTurn(app.state.service, UUID(session_id), "web_voice", lambda *a: _async_val(None), True)
            rt.user = "实时语音问题"
            rt.reply = "实时语音回复"
            rt.usage = TokenUsage(prompt_tokens=30, completion_tokens=10, total_tokens=40)
            rt.first_audio_ms = 85
            rt.required_controls = set()
            rt.control_failure = None
            await rt.persist("complete", audio_status="streamed")
            if app.state.service.audit_tasks:
                await asyncio.gather(*list(app.state.service.audit_tasks), return_exceptions=True)
            return rt.turn_id

        rt_turn_id = client.portal.call(_persist_realtime)

        traces_res = client.get("/api/insights/traces")
        assert traces_res.status_code == 200
        items = traces_res.json()["items"]
        assert traces_res.json()["total"] == 3
        modes = {item["voice_mode"] for item in items}
        assert modes == {"pipeline", "realtime"}
        sources = {item["source"] for item in items}
        assert sources == {"text", "web_voice"}
        rt_row = next(item for item in items if item["trace_id"] == str(rt_turn_id))
        assert rt_row["first_audio_ms"] == 85
        assert rt_row["total_tokens"] == 40

        detail_res = client.get(f"/api/insights/traces/{rt_turn_id}")
        assert detail_res.status_code == 200
        assert detail_res.json()["reply_text"] == "实时语音回复"

        assert client.delete(f"/api/insights/traces/{rt_turn_id}", headers=HEADERS).status_code == 422
        assert client.delete(f"/api/insights/traces/{rt_turn_id}", params={"confirm": "true"}, headers=HEADERS).status_code == 204
        assert client.get(f"/api/insights/traces/{rt_turn_id}").status_code == 404

    # 6. Restart app and verify SQLite business state persisted across boot despite env defaults.
    app2 = create_app(
        _make_cfg(),
        settings_store=SettingsStore(env_path),
        provider_factory=lambda cfg: _FakeLLM(),
    )
    with TestClient(app2, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client2:
        settings2 = client2.get("/api/settings").json()
        assert settings2["embedding_enabled"] is False
        assert settings2["weather_enabled"] is False
        assert settings2["selected_tool_ids"] == []


def test_sqlite_stores_enable_wal_and_audit_initializes_schema_once(tmp_path, monkeypatch):
    history_path = tmp_path / "history.sqlite3"
    errors_path = tmp_path / "errors.sqlite3"
    audit_path = tmp_path / "audits" / "audit.sqlite3"
    HistoryStore(history_path)
    ErrorLogStore(errors_path)
    audit = AuditStore(audit_path)
    assert not audit_path.parent.exists()

    connect = sqlite3.connect
    scripts = []

    class TrackingConnection(sqlite3.Connection):
        def executescript(self, sql_script):
            scripts.append(sql_script)
            return super().executescript(sql_script)

    def connect_tracked(*args, **kwargs):
        return connect(*args, **kwargs, factory=TrackingConnection)

    monkeypatch.setattr(sqlite3, "connect", connect_tracked)
    audit.record("tool_call", tool_name="example")
    assert audit.list_tools()["total"] == 1
    assert len(scripts) == 1
    for path in (history_path, errors_path, audit_path):
        with closing(connect(path)) as connection:
            assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)


def test_async_history_persistence_builds_snapshot_before_threaded_save(tmp_path, monkeypatch, caplog):
    async def scenario():
        history = HistoryStore(tmp_path / "history.sqlite3")
        service = ChatService(Settings(_env_file=None, usage_log_path=None), None, history)
        session_id = service.new_session()
        session = service.get_session(session_id)
        loop_thread = get_ident()
        build_snapshot, save_snapshot = service.session_detail, history.save

        def checked_snapshot(sid):
            assert get_ident() == loop_thread
            assert session.lock.locked()
            return build_snapshot(sid)

        def checked_save(snapshot):
            assert get_ident() != loop_thread
            save_snapshot(snapshot)

        def failed_save(snapshot):
            assert get_ident() != loop_thread
            raise sqlite3.OperationalError("write failed")

        monkeypatch.setattr(service, "session_detail", checked_snapshot)
        monkeypatch.setattr(history, "save", checked_save)
        async with session.lock:
            await service._persist_async(session_id)
            assert session.history_persisted is True
            saved = history.get(session_id)
            assert saved is not None and saved.session_id == session_id and saved.history_persisted

            monkeypatch.setattr(history, "save", failed_save)
            await service._persist_async(session_id)
            assert session.history_persisted is False
            assert "会话仅保留在内存：无法写入本机历史记录。" in caplog.text

    asyncio.run(scenario())


def test_deepseek_search_protocol_trimming_cache_and_key_resolution(monkeypatch):
    async def scenario():
        clock = [100.0]
        monkeypatch.setattr(web_search, "monotonic", lambda: clock[0])
        payload = {"results": [
            {"title": "题" * 140, "url": "https://example.invalid/" + "x" * 310,
             "summary": "摘" * 320, "snippet": "优先使用摘要", "content": "全文", "rerank_score": 2.4},
            {"title": "简讯", "url": "https://example.invalid/second",
             "summary": "", "snippet": "备用摘要", "rerank_score": 1.8},
        ]}
        post = AsyncMock(return_value=httpx.Response(200, json=payload))
        monkeypatch.setattr(httpx.AsyncClient, "post", post)
        settings = Settings(_env_file=None, web_search_api_key="search-test-key",
                            api_key="text-test-key", base_url="https://api.deepseek.com/v1")
        try:
            result = await web_search.search_web(settings, "  Gold News  ", count=10)
            post.assert_awaited_once_with(
                "https://api.deepseek.com/v1/tools/search",
                headers={"Authorization": "Bearer search-test-key", "Content-Type": "application/json"},
                json={"query": "Gold News", "count": 5, "need_content": False},
            )
            assert result["query"] == "Gold News" and result["provider"] == "deepseek" and result["fetched_at"]
            assert result["results"] == [
                {"title": payload["results"][0]["title"][:120], "url": payload["results"][0]["url"][:300],
                 "summary": "摘" * 300, "score": 2.4},
                {"title": "简讯", "url": "https://example.invalid/second", "summary": "备用摘要", "score": 1.8},
            ]
            clock[0] += 179
            assert await web_search.search_web(settings, "Gold News") == result
            assert post.await_count == 1
            clock[0] += 1
            await web_search.search_web(settings, "Gold News")
            assert post.await_count == 2

            inherited = Settings(_env_file=None, web_search_api_key="",
                                 api_key="text-test-key", base_url="https://api.deepseek.com/v1")
            await web_search.search_web(inherited, "最新资讯", count=0)
            assert post.await_args.kwargs["headers"]["Authorization"] == "Bearer text-test-key"
            assert post.await_args.kwargs["json"]["count"] == 1
            unrelated = inherited.model_copy(update={"base_url": "https://third-party.invalid/deepseek.com"})
            with pytest.raises(web_search.WebSearchError) as missing:
                await web_search.search_web(unrelated, "Gold News")
            assert (missing.value.code, missing.value.status) == ("web_search_not_configured", 422)
            with pytest.raises(web_search.WebSearchError) as invalid_query:
                await web_search.search_web(settings, "金" * 129)
            assert (invalid_query.value.code, invalid_query.value.status) == ("web_search_query_invalid", 422)
            assert post.await_count == 3

            for failure, code, status in (
                (TimeoutError("search-test-key"), "web_search_timeout", 504),
                (httpx.ReadTimeout("search-test-key"), "web_search_timeout", 504),
                (httpx.ConnectError("search-test-key"), "web_search_unavailable", 502),
                (httpx.Response(401, text="search-test-key"), "web_search_upstream_error", 502),
            ):
                post.side_effect = [failure]
                with pytest.raises(web_search.WebSearchError) as error:
                    await web_search.search_web(settings, "未缓存的查询")
                assert (error.value.code, error.value.status) == (code, status)
                assert "search-test-key" not in str(error.value)
        finally:
            await web_search.close_web_search_client()

    asyncio.run(scenario())


def test_web_search_selection_requires_enablement_and_keeps_weather(monkeypatch):
    monkeypatch.delenv("AI_WEB_SEARCH_ENABLED", raising=False)
    settings = Settings(_env_file=None, selected_tool_ids=["web_search", "get_weather"], weather_enabled=True)
    disabled = build_tool_registry(settings, None, None)
    assert settings.web_search_enabled is False and not disabled.has("web_search")
    enabled = settings.model_copy(update={"web_search_enabled": True})
    unselected = enabled.model_copy(update={"selected_tool_ids": ["get_weather"]})
    assert not build_tool_registry(unselected, None, None).has("web_search")
    assert build_tool_registry(unselected, None, None, assistant_scope=False).has("web_search")

    service = ChatService(enabled, None)
    service.tools = build_tool_registry(enabled, None, None)
    assert service.tools.get("web_search").spec.permission == "read"
    sid = service.new_session()
    for question, expected in (("查一下今天金价", "web_search"), ("今天天气怎么样", "get_weather")):
        context = service.tool_context(sid, uuid4(), "text", question)
        selection = TextToolSelection(context)
        assert selection.active_names() == [expected]


def test_web_search_settings_are_persisted_and_key_is_redacted(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_WEB_SEARCH_ENABLED", raising=False)
    key = "manual-redaction-probe-value"
    cfg = Settings(
        _env_file=None, web_search_api_key=key, assistant_db_path=tmp_path / "assistant.sqlite3",
        history_db_path=None, personal_kb_db_path=tmp_path / "audit.sqlite3", usage_log_path=None,
        m5stack_enabled=False,
        selected_tool_ids=[],
    )
    post = AsyncMock(side_effect=AssertionError("invalid query must not reach DeepSeek"))
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    app = create_app(cfg, settings_store=SettingsStore(tmp_path / ".env"))
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        settings = client.get("/api/settings")
        assert settings.status_code == 200 and settings.json()["web_search_configured"] is True
        assert "web_search_api_key" not in settings.json() and key not in settings.text
        enabled = client.put("/api/tools/web_search/enabled", json={"enabled": True}, headers=HEADERS)
        assert enabled.status_code == 200
        catalog = {tool["name"]: tool for tool in enabled.json()["tools"]}
        assert catalog["web_search"]["enabled"] is True and catalog["web_search"]["kind"] == "search"
        assert not app.state.service.tools.has("web_search")
        selected = client.put("/api/assistant/selection", json={"selected_tool_ids": ["web_search"]}, headers=HEADERS)
        assert selected.status_code == 200 and app.state.service.tools.has("web_search")

        response = client.post("/api/tools/web_search/call",
                               json={"arguments": {"query": key + "字" * 128}}, headers=HEADERS)
        assert response.status_code == 422 and key not in response.text
        post.assert_not_awaited()
        entry = app.state.audit.list_tools(tool_name="web_search")["items"][0]
        detail = app.state.audit.detail(entry["id"], "tool_call")
        audit_json = json.dumps(detail, ensure_ascii=False)
        assert key not in audit_json and "[已隐藏]" in audit_json

    with closing(sqlite3.connect(cfg.assistant_db_path)) as connection:
        entries = dict(connection.execute("SELECT key, value_json FROM assistant_settings"))
        assert json.loads(entries["web_search_enabled"]) is True
        assert "web_search_api_key" not in entries and key not in json.dumps(entries)

    restarted = create_app(cfg, settings_store=SettingsStore(tmp_path / ".env"))
    with TestClient(restarted, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        assert restarted.state.service.tools.has("web_search")
        disabled = client.put("/api/tools/web_search/enabled", json={"enabled": False}, headers=HEADERS)
        assert disabled.status_code == 200 and not restarted.state.service.tools.has("web_search")


def test_close_web_search_client_closes_and_releases_reused_client():
    async def scenario():
        client = web_search._client()
        assert web_search._client() is client
        await web_search.close_web_search_client()
        assert client.is_closed and web_search._SHARED_CLIENT is None
        await web_search.close_web_search_client()

    asyncio.run(scenario())


_RT_CONNECTION_OPTIONS = {
    "rt_max_continuous_turns": 0,
    "rt_max_continuous_seconds": 900,
    "rt_silence_gate_enabled": False,
    "rt_silence_gate_rms": 180.0,
    "rt_defer_response_until_transcript": True,
}


@pytest.fixture
def connection_settings_client(tmp_path):
    cfg = Settings(
        _env_file=None, api_key="", rt_api_key="", web_search_api_key="",
        base_url="https://api.deepseek.com/v1", web_search_enabled=True, selected_tool_ids=["web_search"],
        assistant_db_path=tmp_path / "assistant.sqlite3",
        history_db_path=None, personal_kb_db_path=None, usage_log_path=None, m5stack_enabled=False,
    )
    store = SettingsStore(tmp_path / ".env")
    app = create_app(cfg, settings_store=store)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        yield client, store


def test_connections_persist_search_key_and_realtime_options_without_resetting_session(connection_settings_client):
    client, store = connection_settings_client
    service = client.app.state.service
    sid = client.portal.call(service.new_session)
    session = service.get_session(sid)
    key = "connection-search-key-for-tests"
    response = client.put("/api/settings/connections", headers=HEADERS,
                          json={"web_search_api_key": key, **_RT_CONNECTION_OPTIONS})
    assert response.status_code == 200 and key not in response.text
    assert all(getattr(service.settings, name) == value for name, value in _RT_CONNECTION_OPTIONS.items())
    saved_env = dotenv_values(store.path, encoding="utf-8")
    assert saved_env["AI_WEB_SEARCH_API_KEY"] == key
    assert all(saved_env["AI_" + name.upper()] == str(value) for name, value in _RT_CONNECTION_OPTIONS.items())
    assert service.tools.get("web_search").settings is service.settings

    response = client.put("/api/settings/connections", headers=HEADERS,
                          json={"base_url": "https://text.example.invalid/v1", "rt_max_continuous_turns": 12,
                                "rt_silence_gate_rms": None})
    assert response.status_code == 200 and key not in response.text
    assert service.settings.web_search_api_key.get_secret_value() == key
    assert service.settings.rt_max_continuous_turns == 12
    assert service.settings.rt_silence_gate_rms == 180.0
    saved_env = dotenv_values(store.path, encoding="utf-8")
    assert saved_env["AI_WEB_SEARCH_API_KEY"] == key and saved_env["AI_RT_MAX_CONTINUOUS_TURNS"] == "12"
    assert service.get_session(sid) is session

    response = client.put("/api/settings/connections", headers=HEADERS, json={"web_search_api_key": None})
    assert response.status_code == 200 and service.settings.web_search_api_key.get_secret_value() == key
    response = client.put("/api/settings/connections", headers=HEADERS, json={"web_search_api_key": ""})
    assert response.status_code == 200 and not service.settings.web_search_api_key.get_secret_value()
    assert dotenv_values(store.path, encoding="utf-8")["AI_WEB_SEARCH_API_KEY"] == ""


def test_public_settings_report_search_key_source_and_realtime_options(connection_settings_client):
    client, _ = connection_settings_client
    first = client.get("/api/settings").json()
    assert first["web_search_configured"] is False and first["web_search_separate_key_configured"] is False
    primary = "deepseek-primary-key-for-tests"
    response = client.put("/api/settings/connections", headers=HEADERS,
                          json={"api_key": primary, **_RT_CONNECTION_OPTIONS})
    assert response.status_code == 200
    fallback = client.get("/api/settings").json()
    assert fallback["web_search_configured"] is True and fallback["web_search_separate_key_configured"] is False

    separate = "independent-search-key-for-tests"
    response = client.put("/api/settings/connections", headers=HEADERS, json={"web_search_api_key": separate})
    assert response.status_code == 200
    public = client.get("/api/settings")
    payload = public.json()
    assert public.status_code == 200
    assert payload["web_search_configured"] is True and payload["web_search_separate_key_configured"] is True
    assert {name: payload[name] for name in _RT_CONNECTION_OPTIONS} == _RT_CONNECTION_OPTIONS
    assert "web_search_api_key" not in payload and separate not in public.text and primary not in public.text
    response = client.put("/api/settings/connections", headers=HEADERS,
                          json={"base_url": "https://different.example.invalid"})
    assert response.status_code == 422 and response.json()["detail"]["code"] == "key_required_for_new_url"


def test_bailian_web_search_fallback_and_public_settings(connection_settings_client, monkeypatch):
    client, _ = connection_settings_client

    async def scenario():
        clock = [200.0]
        monkeypatch.setattr(web_search, "monotonic", lambda: clock[0])
        payload = {
            "choices": [{"message": {"content": "今天北京多云，最高气温 12°C。"}}],
            "search_info": {
                "search_results": [
                    {"title": "北京今日天气预报", "url": "https://weather.example.invalid/bj", "summary": "多云 2~12°C"}
                ]
            },
        }
        post = AsyncMock(return_value=httpx.Response(200, json=payload))
        monkeypatch.setattr(httpx.AsyncClient, "post", post)
        settings = Settings(
            _env_file=None,
            voice_mode="realtime",
            rt_provider="bailian",
            rt_workspace="ws-123",
            rt_api_key="bailian-test-key",
            web_search_api_key="",
        )
        assert web_search.resolve_web_search_provider(settings) == ("bailian", "bailian-test-key")
        try:
            result = await web_search.search_web(settings, "  北京天气  ", count=3)
            post.assert_awaited_once()
            call = post.await_args
            assert call.args[0] == "https://ws-123.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions"
            assert call.kwargs["headers"]["Authorization"] == "Bearer bailian-test-key"
            assert call.kwargs["json"]["model"] == "qwen-flash"
            assert call.kwargs["json"]["stream"] is False
            assert call.kwargs["json"]["enable_thinking"] is False
            assert call.kwargs["json"]["enable_search"] is True
            assert call.kwargs["json"]["search_options"] == {
                "search_strategy": "turbo", "enable_source": True, "forced_search": True,
            }
            assert result["provider"] == "bailian"
            assert result["answer"] == "今天北京多云，最高气温 12°C。"
            assert result["results"] == [
                {"title": "北京今日天气预报", "url": "https://weather.example.invalid/bj", "summary": "多云 2~12°C", "score": None}
            ]
            clock[0] += 100
            assert await web_search.search_web(settings, "北京天气", count=3) == result
            assert post.await_count == 1

            post.return_value = httpx.Response(
                400, json={"error": {"message": "bad param with bailian-test-key"}}
            )
            with pytest.raises(web_search.WebSearchError) as err:
                await web_search.search_web(settings, "未缓存的百炼错误", count=1)
            assert (err.value.code, err.value.status) == ("web_search_upstream_error", 502)
            assert "HTTP 400" in err.value.message
            assert "bailian-test-key" not in err.value.message
        finally:
            await web_search.close_web_search_client()

    asyncio.run(scenario())

    saved = client.put(
        "/api/settings/connections",
        headers=HEADERS,
        json={"voice_mode": "realtime", "rt_provider": "bailian", "rt_api_key": "bailian-conn-secret", "rt_workspace": "ws-123"},
    )
    assert saved.status_code == 200
    pub = client.get("/api/settings").json()
    assert pub["web_search_configured"] is True
    assert pub["web_search_provider"] == "bailian"
    assert pub["web_search_separate_key_configured"] is False
    assert "bailian-conn-secret" not in str(pub)


def test_health_reports_hardware_ready_boolean(connection_settings_client):
    client, _ = connection_settings_client
    devices = client.app.state.devices
    assert client.get("/health").json()["device_connected"] is False
    try:
        devices.connection = SimpleNamespace(ready=False, token="device-token-for-tests")
        assert client.get("/health").json()["device_connected"] is False
        devices.connection.ready = True
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["device_connected"] is True
        assert "device-token-for-tests" not in response.text
    finally:
        devices.connection = None
