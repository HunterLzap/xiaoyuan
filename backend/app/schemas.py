from decimal import Decimal
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)
    session_id: UUID | None = None
    use_m5stack: bool = False

    @field_validator("message")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message cannot be blank")
        return value.strip()


class VoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)
    session_id: UUID | None = None
    turn_id: UUID = Field(default_factory=uuid4)

    @field_validator("text")
    @classmethod
    def nonblank(cls, value: str) -> str:
        return ChatRequest.nonblank(value)


class VoiceSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: UUID | None = None


class VoiceStopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: UUID
    turn_id: UUID


class ChatCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: UUID
    turn_id: UUID | None = None


class VoicePlaybackRequest(VoiceStopRequest):
    state: Literal["played", "interrupted", "failed"]


class QwenVoicePreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    voice: str = Field(min_length=1, max_length=200)
    text: str = Field(default="你好，我是你的个人助理。", min_length=1, max_length=80)
    rate: float | None = Field(default=None, ge=0.5, le=2.0)
    pitch: float | None = Field(default=None, ge=-8.0, le=8.0)


class TokenUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    input_tokens_details: dict | None = None
    output_tokens_details: dict | None = None
    response_count: int | None = None
    reported_response_count: int | None = None
    responses: list[dict] | None = None

    @classmethod
    def from_provider(cls, usage):
        if usage is None:
            return None
        data = usage if isinstance(usage, dict) else usage.model_dump()

        def count_int(value) -> int | None:
            return value if type(value) is int and value >= 0 else None

        def count_dict(value) -> dict | None:
            if not isinstance(value, dict):
                return None
            cleaned = {}
            for key, item in value.items():
                if isinstance(item, dict):
                    nested = count_dict(item)
                    if nested is not None:
                        cleaned[key] = nested
                else:
                    number = count_int(item)
                    if number is not None:
                        cleaned[key] = number
            return cleaned

        return cls(
            prompt_tokens=count_int(data.get("input_tokens", data.get("prompt_tokens"))),
            completion_tokens=count_int(data.get("output_tokens", data.get("completion_tokens"))),
            total_tokens=count_int(data.get("total_tokens")),
            input_tokens_details=count_dict(data.get("input_tokens_details", data.get("prompt_tokens_details"))),
            output_tokens_details=count_dict(data.get("output_tokens_details", data.get("completion_tokens_details"))),
            response_count=1,
            reported_response_count=1 if data else 0,
        )


class UsageTotals(BaseModel):
    calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    calls_with_complete_usage: int = 0
    calls_without_complete_usage: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost: Decimal = Decimal("0")
    calls_with_cost_estimate: int = 0
    calls_without_cost_estimate: int = 0


class KnowledgeSource(BaseModel):
    title: str
    url: str


class KnowledgeDocument(BaseModel):
    title: str
    product: str = ""
    excerpt: str
    source_url: str | None = None


class KnowledgeResult(BaseModel):
    query: str
    status: Literal["success", "empty"]
    documents: list[KnowledgeDocument]
    sources: list[KnowledgeSource]
    total_matches: int
    truncated: bool
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    server_url: str = "https://mcp.m5stack.com/sse"
    tool_name: Literal["knowledge_search"] = "knowledge_search"


class KnowledgeSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=4000)
    filter_type: Literal["product", "product_no_eol", "program", "arduino", "uiflow", "esp-idf", "esphome"] | None = None
    is_chip: bool = False

    @field_validator("query")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query cannot be blank")
        return value.strip()


class PersonalKnowledgeSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=8)
    group: str = Field(default="", max_length=80)
    hybrid: bool = False
    # 管理端「试查」可指定单个库，独立于助手选择；省略时按助手所选库范围。
    library_id: str | None = Field(default=None, max_length=64)

    @field_validator("query")
    @classmethod
    def nonblank(cls, value: str) -> str:
        return ChatRequest.nonblank(value)


class PersonalKnowledgeRename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    group: str = Field(default="", max_length=80)

    @field_validator("title")
    @classmethod
    def nonblank(cls, value: str) -> str:
        return ChatRequest.nonblank(value)


class LibraryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        return ChatRequest.nonblank(value)


class LibraryRename(LibraryCreate):
    pass


class InsightCorrectAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correct_answer: str | None = Field(max_length=16000)


class InsightClearFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str = Field(default="", max_length=200)
    answer_type: str | None = Field(default=None, max_length=40)
    status: str | None = Field(default=None, max_length=40)
    tool_name: str | None = Field(default=None, max_length=80)
    since: str | None = Field(default=None, max_length=40)
    until: str | None = Field(default=None, max_length=40)
    confirm: bool = False
    expected_total: int | None = Field(default=None, ge=0)


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "deny", "approve_desktop_lease"]
    session_id: UUID | None = None


class ChatResponse(BaseModel):
    session_id: UUID
    reply: str
    provider: str
    model: str
    finish_reason: str | None
    usage: TokenUsage | None
    estimated_cost: Decimal | None
    currency: str
    session_usage: UsageTotals
    history_persisted: bool | None = None
    knowledge: KnowledgeResult | None = None
    sources: list[dict] = Field(default_factory=list)
    tool_calls: list[dict] = Field(default_factory=list)
    pending_approval: dict | None = None
    elapsed_ms: int | None = None


class TranscriptMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model: str | None = None
    provider: str | None = None
    usage: TokenUsage | None = None
    estimated_cost: Decimal | None = None
    currency: str | None = None
    finish_reason: str | None = None
    knowledge: KnowledgeResult | None = None
    sources: list[dict] = Field(default_factory=list)
    tool_calls: list[dict] = Field(default_factory=list)
    pending_approval: dict | None = None
    elapsed_ms: int | None = None
    source: Literal["text", "web_voice", "device_voice"] = "text"
    turn_id: UUID | None = None
    status: Literal["complete", "generating", "interrupted", "failed"] = "complete"
    audio_status: Literal["pending", "streamed", "played", "interrupted", "failed"] | None = None


class SessionSummary(BaseModel):
    session_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    history_persisted: bool | None = None


class SessionDetail(SessionSummary):
    messages: list[TranscriptMessage]


class SessionRename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=80)

    @field_validator("title")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title cannot be blank")
        return value.strip()
