"""Regression test for multi-knowledge-base retrieval isolation using temporary SQLite."""

import json
import os
from urllib.parse import quote

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.llm import OpenAICompatibleProvider
from backend.app.main import create_app
from backend.app.settings_store import SettingsStore
from test_api import HEADERS


@pytest.fixture(autouse=True)
def _clean_ai_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("AI_"):
            monkeypatch.delenv(key)


def _sse_stream(chunks: list[dict]) -> httpx.Response:
    lines = [f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n" for chunk in chunks]
    lines.append("data: [DONE]\n\n")
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content="".join(lines).encode("utf-8"))


class _ToolLoopGateway:
    """External OpenAI SSE transport stub; triggers search_personal_knowledge once per turn."""

    def __init__(self):
        self.requests: list[dict] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        messages = body.get("messages", [])
        tool_names = [item["function"]["name"] for item in body.get("tools", []) if item.get("type") == "function"]
        has_tool_output = any(message.get("role") == "tool" for message in messages)
        if "search_personal_knowledge" in tool_names and not has_tool_output:
            arguments = json.dumps({"query": "设备校准协议", "top_k": 5}, ensure_ascii=False)
            return _sse_stream([
                {
                    "id": "chatcmpl-tool",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": body["model"],
                    "choices": [{
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "tool_calls": [{
                                "index": 0,
                                "id": "call_kb_1",
                                "type": "function",
                                "function": {"name": "search_personal_knowledge", "arguments": arguments},
                            }],
                        },
                        "finish_reason": None,
                    }],
                },
                {
                    "id": "chatcmpl-tool",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": body["model"],
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
                },
            ])
        return _sse_stream([
            {
                "id": "chatcmpl-reply",
                "object": "chat.completion.chunk",
                "created": 2,
                "model": body["model"],
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": "已核对知识库。"}, "finish_reason": None}],
            },
            {
                "id": "chatcmpl-reply",
                "object": "chat.completion.chunk",
                "created": 2,
                "model": body["model"],
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 30, "completion_tokens": 6, "total_tokens": 36},
            },
        ])

    def factory(self, settings: Settings) -> OpenAICompatibleProvider:
        return OpenAICompatibleProvider(settings, httpx.AsyncClient(transport=httpx.MockTransport(self.handle)))


def _upload_doc(client: TestClient, library_id: str, filename: str, content: str) -> dict:
    response = client.post(
        "/api/knowledge/personal/upload",
        content=content.encode("utf-8"),
        headers={
            **HEADERS,
            "content-type": "application/octet-stream",
            "x-doc-filename": quote(filename),
            "x-doc-title": quote(filename),
            "x-doc-library": quote(library_id),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _last_tool_payload(requests: list[dict]) -> dict:
    for message in reversed(requests[-1]["messages"]):
        if message.get("role") == "tool":
            return json.loads(message["content"])
    raise AssertionError("Expected tool output payload in final model request")


def test_multi_kb_retrieval_isolation(tmp_path):
    gateway = _ToolLoopGateway()
    config = Settings(
        _env_file=None,
        voice_mode="pipeline",
        api_key="test-secret",
        model="test-model",
        m5stack_enabled=False,
        personal_kb_enabled=True,
        embedding_enabled=False,
        usage_log_path=None,
        history_db_path=tmp_path / "conversations.sqlite3",
        personal_kb_db_path=tmp_path / "personal_kb.sqlite3",
    )
    app = create_app(config, settings_store=SettingsStore(tmp_path / ".env"), provider_factory=gateway.factory)

    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        lib_a = client.post("/api/knowledge/libraries", json={"name": "实验室星尘库"}, headers=HEADERS).json()["id"]
        lib_b = client.post("/api/knowledge/libraries", json={"name": "海岸海风库"}, headers=HEADERS).json()["id"]

        doc_a = _upload_doc(
            client,
            lib_a,
            "alpha_protocol.md",
            "# 北翼校准\n\n设备校准协议：ALPHA-NORTH-991，仅用于实验室光学平台。",
        )
        doc_b = _upload_doc(
            client,
            lib_b,
            "beta_protocol.md",
            "# 南站校准\n\n设备校准协议：BETA-SOUTH-774，仅用于海岸潮汐传感。",
        )

        # 1. Management search API respects assistant selection and explicit library_id without cross-library leakage.
        select_a = client.put("/api/assistant/selection", json={"selected_kb_ids": [lib_a]}, headers=HEADERS)
        assert select_a.status_code == 200

        search_a = client.post(
            "/api/knowledge/personal/search",
            json={"query": "设备校准协议", "top_k": 8},
            headers=HEADERS,
        )
        assert search_a.status_code == 200
        matches_a = search_a.json()["matches"]
        assert [item["document_id"] for item in matches_a] == [doc_a["id"]]
        assert "ALPHA-NORTH-991" in matches_a[0]["excerpt"]
        assert "BETA-SOUTH-774" not in search_a.text

        explicit_b = client.post(
            "/api/knowledge/personal/search",
            json={"query": "设备校准协议", "top_k": 8, "library_id": lib_b},
            headers=HEADERS,
        )
        assert explicit_b.status_code == 200
        matches_explicit_b = explicit_b.json()["matches"]
        assert [item["document_id"] for item in matches_explicit_b] == [doc_b["id"]]
        assert "BETA-SOUTH-774" in matches_explicit_b[0]["excerpt"]
        assert "ALPHA-NORTH-991" not in explicit_b.text

        # 2. Chat tool-calling path isolates retrieval strictly to selected_kb_ids.
        chat_a = client.post("/chat", json={"message": "查一下设备校准协议"})
        assert chat_a.status_code == 200
        tool_out_a = _last_tool_payload(gateway.requests)
        assert [item["document_id"] for item in tool_out_a["matches"]] == [doc_a["id"]]
        assert "ALPHA-NORTH-991" in tool_out_a["matches"][0]["excerpt"]
        assert "BETA-SOUTH-774" not in json.dumps(tool_out_a, ensure_ascii=False)
        assert {item["document_id"] for item in chat_a.json()["sources"]} == {doc_a["id"]}

        # Switch assistant selection to library B and run the same chat query again.
        assert client.put("/api/assistant/selection", json={"selected_kb_ids": [lib_b]}, headers=HEADERS).status_code == 200
        chat_b = client.post("/chat", json={"message": "查一下设备校准协议"})
        assert chat_b.status_code == 200
        tool_out_b = _last_tool_payload(gateway.requests)
        assert [item["document_id"] for item in tool_out_b["matches"]] == [doc_b["id"]]
        assert "BETA-SOUTH-774" in tool_out_b["matches"][0]["excerpt"]
        assert "ALPHA-NORTH-991" not in json.dumps(tool_out_b, ensure_ascii=False)
        assert {item["document_id"] for item in chat_b.json()["sources"]} == {doc_b["id"]}

        # Selecting both libraries allows hits from both; clearing selection removes KB retrieval completely.
        assert client.put("/api/assistant/selection", json={"selected_kb_ids": [lib_a, lib_b]}, headers=HEADERS).status_code == 200
        chat_both = client.post("/chat", json={"message": "查一下设备校准协议"})
        assert chat_both.status_code == 200
        tool_out_both = _last_tool_payload(gateway.requests)
        assert {item["document_id"] for item in tool_out_both["matches"]} == {doc_a["id"], doc_b["id"]}

        assert client.put("/api/assistant/selection", json={"selected_kb_ids": []}, headers=HEADERS).status_code == 200
        empty_search = client.post("/api/knowledge/personal/search", json={"query": "设备校准协议"}, headers=HEADERS)
        assert empty_search.status_code == 200 and empty_search.json()["matches"] == []
        request_count_before_empty = len(gateway.requests)
        chat_empty = client.post("/chat", json={"message": "查一下设备校准协议"})
        assert chat_empty.status_code == 200
        assert len(gateway.requests) == request_count_before_empty + 1
        offered_tools = [
            item["function"]["name"]
            for item in gateway.requests[-1].get("tools", [])
            if item.get("type") == "function"
        ]
        assert "search_personal_knowledge" not in offered_tools
