from decimal import Decimal
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_", env_file=ROOT / ".env", env_file_encoding="utf-8",
        extra="ignore", hide_input_in_errors=True,
    )

    voice_mode: Literal["realtime", "pipeline"] = "realtime"
    rt_provider: Literal["bailian", "compatible"] = "bailian"
    rt_endpoint: str = Field(default="", max_length=500)
    rt_workspace: str = Field(default="", pattern=r"^(?:[a-z0-9][a-z0-9-]{0,62})?$")
    rt_model: str = Field(default="qwen3.8-omni-flash-realtime", min_length=1, max_length=200)
    rt_voice: str = Field(default="Tina", min_length=1, max_length=80)
    rt_api_key: SecretStr = SecretStr("")
    provider: str = "tokendance"
    base_url: str = "https://tokendance.space/gateway/v1"
    api_key: SecretStr = SecretStr("")
    model: str = ""
    models_protocol: Literal["auto", "openai", "disabled"] = "auto"
    timeout_seconds: float = Field(default=30, gt=0, le=300)
    max_tokens: int | None = Field(default=None, ge=1, le=8192)
    # Thinking switch forwarded to providers that expose one. Empty = current behaviour.
    # On spark-x2.5 only "none" really disables reasoning ("low" still runs the full
    # chain, "minimal" is rejected), which is what keeps voice turns from taking 20s+.
    reasoning_effort: str = Field(default="", max_length=20)
    history_turns: int = Field(default=6, ge=1, le=50)
    max_sessions: int = Field(default=100, ge=1, le=1000)
    system_prompt: str = Field(
        default="你是一个简洁、可靠的个人 AI 助理。使用中文回答，除非用户要求其他语言。",
        max_length=4000,
    )
    input_price_per_million: Decimal | None = Field(default=None, ge=0)
    output_price_per_million: Decimal | None = Field(default=None, ge=0)
    currency: str = "CNY"
    usage_log_path: Path | None = ROOT / "logs" / "usage.jsonl"
    history_db_path: Path | None = ROOT / "data" / "conversations.sqlite3"
    m5stack_enabled: bool = True
    m5stack_timeout_seconds: float = Field(default=40, ge=5, le=90)
    personal_kb_enabled: bool = True
    personal_kb_db_path: Path | None = ROOT / "data" / "personal_kb.sqlite3"
    weather_enabled: bool = True
    weather_default_city: str = Field(default="", max_length=80)
    # None 仅标记旧配置未初始化；启动时一次性写成具体数组。[] 明确禁止对应能力。
    selected_tool_ids: list[str] | None = None
    selected_kb_ids: list[str] | None = None
    embedding_enabled: bool = False
    embedding_model: str = Field(default="qwen3.7-text-embedding", max_length=200)
    embedding_dimensions: int = Field(default=1024, ge=256, le=2560)
    tts_base_url: str = "https://tokendance.space/gateway/v1"
    tts_api_key: SecretStr = SecretStr("")
    tts_use_text_connection: bool | None = None
    tts_model: str = Field(default="mimo-v2.5-tts", max_length=200)
    # Free text: preset names are fixed, but cloned voices use their saved id.
    tts_voice: str = Field(default="mimo_default", max_length=80)
    tts_instruction: str = Field(default="", max_length=2000)
    # Project-relative path to the reference voice used by the clone model.
    tts_clone_sample: str = Field(default="", max_length=500)
    # Playback shaping applied after synthesis, so the model never has to interpret
    # "faster" or "higher" as text instructions. Loudness is not shaped here: the device
    # speaker volume (0-100, stored with the device) is the single control for that.
    tts_rate: float = Field(default=1.0, ge=0.5, le=2.0)
    tts_pitch: float = Field(default=0.0, ge=-8.0, le=8.0)
    tts_timeout_seconds: float = Field(default=60, gt=0, le=120)
    public_origin: str = ""
    admin_proxy_token: SecretStr = SecretStr("")
    speech_python: Path | None = None
    speech_threads: int = Field(default=2, ge=1, le=4)
    asr_model_dir: Path = ROOT / "models" / "asr" / "sensevoice"

    @field_validator("rt_endpoint")
    @classmethod
    def rt_url(cls, value):
        if value:
            p = urlsplit(value)
            if p.scheme != "wss" or not p.hostname or p.username or p.password or p.query or p.fragment or any(c.isspace() for c in value):
                raise ValueError("需要不带密钥、查询参数的 WSS 地址")
        return value

    @field_validator("public_origin")
    @classmethod
    def validate_public_origin(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value:
            return ""
        parts = urlsplit(value)
        if (parts.scheme != "https" or not parts.hostname
                or parts.username is not None or parts.password is not None
                or parts.path or parts.query or parts.fragment
                or any(char.isspace() for char in value)):
            raise ValueError("Public origin must be an HTTPS origin without path, credentials or query")
        port = parts.port
        if port == 0 or "*" in parts.hostname:
            raise ValueError("Public origin must name one HTTPS host and a valid port")
        hostname = parts.hostname.encode("idna").decode("ascii").lower()
        host = f"[{hostname}]" if ":" in hostname else hostname
        return "https://" + host + (f":{port}" if port is not None and port != 443 else "")

    @field_validator("admin_proxy_token")
    @classmethod
    def validate_proxy_token(cls, value: SecretStr) -> SecretStr:
        token = value.get_secret_value().strip()
        if any(ord(char) < 33 or ord(char) > 126 for char in token):
            raise ValueError("Proxy credential must contain only printable ASCII without spaces")
        return SecretStr(token)

    @model_validator(mode="after")
    def require_public_auth(self):
        if self.public_origin and len(self.admin_proxy_token.get_secret_value()) < 32:
            raise ValueError("Public mode requires AI_ADMIN_PROXY_TOKEN with at least 32 characters")
        return self

    @field_validator("base_url", "tts_base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parts = urlsplit(value)
        if (parts.scheme not in {"http", "https"} or not parts.hostname
                or parts.username or parts.password or parts.query or parts.fragment):
            raise ValueError("Base URL must be an HTTP(S) API root without credentials or query")
        return value

    @field_validator("model", "provider", "currency", "reasoning_effort")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("selected_tool_ids", "selected_kb_ids", mode="before")
    @classmethod
    def parse_selection_ids(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            import json
            value = json.loads(value)
        if not isinstance(value, list) or any(
                not isinstance(item, str) or not item.strip() or item != item.strip() or len(item) > 64
                for item in value) or len(value) > 50 or len(value) != len(set(value)):
            raise ValueError("选择必须是不重复的有效 ID 数组")
        return value

    @field_validator("api_key", "tts_api_key", "rt_api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        key = value.get_secret_value().strip()
        if any(ord(char) < 33 or ord(char) > 126 for char in key):
            raise ValueError("API Key 格式无效；请使用服务商提供的密钥，不含空格或换行")
        return SecretStr(key)

    @property
    def missing_config(self) -> list[str]:
        if self.voice_mode == "realtime":
            missing = []
            if not self.rt_api_key.get_secret_value().strip():
                missing.append("AI_RT_API_KEY")
            if not (self.rt_workspace if self.rt_provider == "bailian" else self.rt_endpoint):
                missing.append("AI_RT_WORKSPACE" if self.rt_provider == "bailian" else "AI_RT_ENDPOINT")
            return missing
        missing = []
        if not self.api_key.get_secret_value().strip():
            missing.append("AI_API_KEY")
        if not self.model:
            missing.append("AI_MODEL")
        return missing

    @property
    def active_model(self) -> str:
        return self.rt_model if self.voice_mode == "realtime" else self.model

    @property
    def active_provider(self) -> str:
        if self.voice_mode == "realtime":
            return "百炼" if self.rt_provider == "bailian" else "实时接口"
        return self.provider

    @property
    def shared_tts_connection(self) -> bool:
        if self.tts_use_text_connection is not None:
            return self.tts_use_text_connection
        return (not bool(self.tts_api_key.get_secret_value()) or
                self.tts_base_url == self.base_url and self.tts_api_key == self.api_key)

    @property
    def effective_tts_base_url(self) -> str:
        return self.base_url if self.shared_tts_connection else self.tts_base_url

    @property
    def effective_tts_api_key(self) -> SecretStr:
        return self.api_key if self.shared_tts_connection else self.tts_api_key
