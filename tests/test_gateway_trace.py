"""Batch 2 & 3 tests: ToolGateway confirmations, TextToolSelection >5 trigger, unified traces, and SQLite business state."""
from __future__ import annotations

import asyncio
import io
import json
from uuid import UUID, uuid4
import wave

from fastapi.testclient import TestClient
import pytest

from backend.app.config import Settings
from backend.app.llm import Completion, ProviderError
from backend.app.main import create_app
from backend.app.realtime import RealtimeTurn
from backend.app.schemas import TokenUsage
from backend.app.service import ChatService
from backend.app.settings_store import SettingsStore
from backend.app.tool_dialogue import TOOL_LOADING_NAME, ToolConversation
from backend.app.tools import ToolRegistry, ToolSpec


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

        rt_turn_id = asyncio.run(_persist_realtime())

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
