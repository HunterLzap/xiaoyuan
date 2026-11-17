import json
import os
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values, set_key, unset_key
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

from . import voices
from .config import ROOT, Settings
from .llm import ProviderError
from .tts import CLONE_MODEL


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    provider: str = Field(default="tokendance", min_length=1, max_length=80)
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(default="", max_length=200)
    models_protocol: Literal["auto", "openai", "disabled"] = "auto"
    api_key: SecretStr | None = None
    timeout_seconds: float = Field(default=30, gt=0, le=300)
    max_tokens: int | None = Field(default=None, ge=1, le=8192)
    input_price_per_million: Decimal | None = Field(default=None, ge=0)
    output_price_per_million: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="CNY", min_length=1, max_length=12)
    m5stack_enabled: bool = True


class CapabilitySettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    m5stack_enabled: bool = True
    personal_kb_enabled: bool = True
    weather_enabled: bool = True
    embedding_enabled: bool | None = None
    desktop_enabled: bool | None = None


class TTSSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    tts_provider: Literal["mimo", "openai", "bailian"] = "mimo"
    tts_base_url: str = Field(default="https://tokendance.space/gateway/v1", min_length=1, max_length=500)
    tts_api_key: SecretStr | None = None
    tts_use_text_connection: bool | None = None
    tts_model: str = Field(default="mimo-v2.5-tts", min_length=1, max_length=200)
    tts_voice: str = Field(default="mimo_default", max_length=80)
    tts_instruction: str = Field(default="", max_length=2000)
    tts_clone_sample: str = Field(default="", max_length=500)
    tts_rate: float = Field(default=1.0, ge=0.5, le=2.0)
    tts_pitch: float = Field(default=0.0, ge=-8.0, le=8.0)
    tts_timeout_seconds: float = Field(default=60, gt=0, le=120)


class ConnectionsUpdate(BaseModel):
    voice_mode: Literal["realtime", "pipeline"] = "realtime"
    rt_provider: Literal["bailian", "compatible"] = "bailian"
    rt_endpoint: str = Field(default="", max_length=500)
    rt_workspace: str = Field(default="", pattern=r"^(?:[a-z0-9][a-z0-9-]{0,62})?$")
    rt_model: str = Field(default="qwen3.8-omni-flash-realtime", min_length=1, max_length=200)
    rt_voice: str = Field(default="Tina", min_length=1, max_length=80)
    rt_asr_model: str = Field(default="whisper-1", max_length=200)
    rt_api_key: SecretStr | None = None

    asr_provider: Literal["openai", "bailian", "local"] = "openai"
    asr_base_url: str = Field(default="", max_length=500)
    asr_api_key: SecretStr | None = None
    asr_use_text_connection: bool | None = None
    asr_model: str = Field(default="whisper-1", max_length=200)
    asr_language: str = Field(default="zh", max_length=20)

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    base_url: str = Field(min_length=1, max_length=500)
    api_key: SecretStr | None = None
    models_protocol: Literal["auto", "openai", "disabled"] = "auto"
    tts_provider: Literal["mimo", "openai", "bailian"] = "mimo"
    tts_base_url: str | None = Field(default=None, min_length=1, max_length=500)
    tts_api_key: SecretStr | None = None
    tts_use_text_connection: bool | None = None
    provider: str = Field(default="tokendance", min_length=1, max_length=80)
    timeout_seconds: float = Field(default=30, gt=0, le=300)
    max_tokens: int | None = Field(default=None, ge=1, le=8192)
    input_price_per_million: Decimal | None = Field(default=None, ge=0)
    output_price_per_million: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="CNY", min_length=1, max_length=12)
    m5stack_enabled: bool = True
    personal_kb_enabled: bool = True
    tts_timeout_seconds: float = Field(default=60, gt=0, le=120)


class AssistantUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    system_prompt: str | None = Field(default=None, min_length=1, max_length=4000)
    agent_profile: str | None = Field(default=None, max_length=2000)
    model: str = Field(default="", max_length=200)
    tts_provider: Literal["mimo", "openai", "bailian"] | None = None
    tts_model: str = Field(default="mimo-v2.5-tts", min_length=1, max_length=200)
    tts_voice: str = Field(default="mimo_default", max_length=80)
    tts_instruction: str = Field(default="", max_length=2000)
    tts_clone_sample: str = Field(default="", max_length=500)
    tts_rate: float = Field(default=1.0, ge=0.5, le=2.0)
    tts_pitch: float = Field(default=0.0, ge=-8.0, le=8.0)
    tts_timeout_seconds: float = Field(default=60, gt=0, le=120)
    weather_enabled: bool | None = None
    weather_default_city: str | None = Field(default=None, max_length=80)

    @field_validator("system_prompt")
    @classmethod
    def validate_system_prompt(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("请填写角色说明。")
        return value

    @field_validator("agent_profile")
    @classmethod
    def validate_agent_profile(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class AssistantSelectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected_tool_ids: list[str] = Field(default_factory=list, max_length=50)
    selected_kb_ids: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("selected_tool_ids", "selected_kb_ids")
    @classmethod
    def validate_ids(cls, value):
        if any(not item or item != item.strip() or len(item) > 64 for item in value):
            raise ValueError("请选择有效的 ID")
        if len(value) != len(set(value)):
            raise ValueError("选择 ID 不能重复")
        return value


class APISettingsUpdate(ConnectionsUpdate, AssistantUpdate):
    pass


class TTSPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    config: TTSSettingsUpdate
    connection: ConnectionsUpdate | None = None
    text: str = Field(min_length=1, max_length=500)


def public_tts_settings(settings: Settings) -> dict:
    return {name: getattr(settings, name) for name in TTSSettingsUpdate.model_fields
            if name != "tts_api_key"} | {
        "use_text_connection": settings.shared_tts_connection,
        "connection_base_url": settings.effective_tts_base_url,
        "separate_api_key_configured": bool(settings.tts_api_key.get_secret_value()),
        "api_key_configured": bool(settings.effective_tts_api_key.get_secret_value()),
        "configured": bool(settings.effective_tts_api_key.get_secret_value()) and (
            settings.tts_provider != "mimo"
            or settings.tts_model != "mimo-v2.5-tts-voicedesign"
            or bool(settings.tts_instruction.strip())),
    }


def public_settings(settings: Settings) -> dict:
    return {
        name: getattr(settings, name)
        for name in SettingsUpdate.model_fields if name != "api_key"
    } | {
        "system_prompt": settings.system_prompt,
        "agent_profile": settings.agent_profile,
        "personal_kb_enabled": settings.personal_kb_enabled,
        "embedding_enabled": settings.embedding_enabled,
        "weather_enabled": settings.weather_enabled,
        "weather_default_city": settings.weather_default_city,
        "desktop_enabled": settings.desktop_enabled,
        "selected_tool_ids": settings.selected_tool_ids if settings.selected_tool_ids is not None else [],
        "selected_kb_ids": settings.selected_kb_ids if settings.selected_kb_ids is not None else [],
        "active_model": settings.active_model,
        "active_provider": settings.active_provider,
        **{k: getattr(settings, k) for k in (
            "voice_mode", "rt_provider", "rt_endpoint", "rt_workspace", "rt_model", "rt_voice", "rt_asr_model",
            "asr_provider", "asr_base_url", "asr_model", "asr_language", "tts_provider",
        )},
        "asr_use_text_connection": settings.shared_asr_connection,
        "asr_effective_base_url": settings.effective_asr_base_url,
        "asr_separate_key_configured": bool(settings.asr_api_key.get_secret_value()),
        "asr_key_configured": bool(settings.effective_asr_api_key.get_secret_value()),
        "rt_key_configured": bool(settings.rt_api_key.get_secret_value()),
        "api_key_configured": bool(settings.api_key.get_secret_value().strip()),
        "configured": not settings.missing_config,
        "environment_overrides": [
            "AI_" + name.upper() for name in SettingsUpdate.model_fields
            if "AI_" + name.upper() in os.environ
        ],
    }


class SettingsStore:
    def __init__(self, path: Path = ROOT / ".env"):
        self.path = path.resolve()

    def initialize_selection(self, current: Settings, tool_ids: list[str], kb_ids: list[str]) -> Settings:
        # 仅填充缺失字段，显式 [] 永远保留；保存失败则不能启用内存中的默认范围。
        missing = {}
        if current.selected_tool_ids is None:
            missing["selected_tool_ids"] = tool_ids
        if current.selected_kb_ids is None:
            missing["selected_kb_ids"] = kb_ids
        if not missing:
            return current
        update = AssistantSelectionUpdate(**missing)
        config = self.prepare(current, update)
        self.save(config, update)
        return config

    def prepare(self, current: Settings, update: SettingsUpdate | TTSSettingsUpdate | ConnectionsUpdate | AssistantUpdate | CapabilitySettingsUpdate | AssistantSelectionUpdate) -> Settings:
        if isinstance(update, AssistantSelectionUpdate):
            # 选择更新不得顺带规范化音色、样本等无关字段。
            return Settings(_env_file=None, **{**current.model_dump(), **update.model_dump(exclude_unset=True)})
        key_names = {name for name in ("api_key", "tts_api_key", "rt_api_key", "asr_api_key") if name in type(update).model_fields}
        values = current.model_dump()
        # 均为“真正部分更新”：只应用请求里显式提交的字段；
        # APISettingsUpdate 继承 ConnectionsUpdate/AssistantUpdate，按子集处理，未提交字段保持现配置。
        updates = update.model_dump(exclude=key_names, exclude_unset=isinstance(
            update, (ConnectionsUpdate, CapabilitySettingsUpdate, AssistantUpdate, AssistantSelectionUpdate)))
        if isinstance(update, AssistantUpdate) and update.system_prompt is None:
            updates.pop("system_prompt", None)
        if isinstance(update, AssistantUpdate):
            for extra in ("agent_profile", "weather_enabled", "weather_default_city", "tts_provider"):
                if getattr(update, extra, None) is None:
                    updates.pop(extra, None)
        if isinstance(update, CapabilitySettingsUpdate):
            for extra in ("embedding_enabled", "desktop_enabled"):
                if getattr(update, extra, None) is None:
                    updates.pop(extra, None)
        if isinstance(update, ConnectionsUpdate):
            for name in ("tts_base_url", "tts_use_text_connection", "asr_use_text_connection"):
                if updates.get(name) is None:
                    updates.pop(name, None)
        values.update(updates)
        # The clone sample is resolved from the voice id, never accepted from the client:
        # the browser only knows ids, and a path sent from the page would bypass the
        # project-boundary check in voices.resolve().
        if values.get("tts_provider", "mimo") == "mimo" and values.get("tts_model") == CLONE_MODEL:
            voice_id = str(values.get("tts_voice") or "")
            resolved = voices.sample_for(voice_id)
            if resolved:
                values["tts_clone_sample"] = resolved
            elif not voices.resolve(values.get("tts_clone_sample") or ""):
                values["tts_clone_sample"] = ""
        else:
            values["tts_clone_sample"] = ""
        for key_name in key_names:
            if getattr(update, key_name) is not None:
                values[key_name] = getattr(update, key_name)
        try:
            config = Settings(_env_file=None, **values)
        except ValidationError:
            raise ProviderError(422, "invalid_settings", "配置无效；请检查 Base URL 和数值范围。") from None
        if "rt_api_key" in key_names and update.rt_api_key is None and current.rt_api_key.get_secret_value() and (
            config.rt_provider != current.rt_provider or config.rt_endpoint != current.rt_endpoint):
            raise ProviderError(422, "key_required_for_new_url", "切换实时接口后，请重新输入 API Key。")
        for key_name in key_names:
            url_name = ("rt_workspace" if key_name == "rt_api_key"
                        else "tts_base_url" if key_name == "tts_api_key"
                        else "asr_base_url" if key_name == "asr_api_key"
                        else "base_url")
            if (getattr(config, url_name) != getattr(current, url_name) and getattr(update, key_name) is None
                    and getattr(current, key_name).get_secret_value().strip()):
                raise ProviderError(422, "key_required_for_new_url", "接口地址已更改，请重新输入该服务的密钥；不会向新地址发送已有密钥。")
        if isinstance(update, (SettingsUpdate, AssistantUpdate)) and config.model in {
                "mimo-v2.5-tts", "mimo-v2.5-tts-voicedesign", "mimo-v2.5-tts-voiceclone"}:
            raise ProviderError(422, "tts_model_in_text", "这是语音合成模型，请切换到“语音合成”配置；文字模型需使用可返回文字的模型。")
        return config

    def save(self, settings: Settings, update: SettingsUpdate | TTSSettingsUpdate | ConnectionsUpdate | AssistantUpdate | CapabilitySettingsUpdate | AssistantSelectionUpdate) -> None:
        managed = set(type(update).model_fields)
        if isinstance(update, AssistantUpdate) and update.system_prompt is None:
            managed.remove("system_prompt")
        if isinstance(update, AssistantUpdate):
            for extra in ("agent_profile", "weather_enabled", "weather_default_city", "tts_provider"):
                if getattr(update, extra, None) is None:
                    managed.discard(extra)
        if isinstance(update, CapabilitySettingsUpdate):
            for extra in ("embedding_enabled", "desktop_enabled"):
                if getattr(update, extra, None) is None:
                    managed.discard(extra)
        if isinstance(update, (ConnectionsUpdate, CapabilitySettingsUpdate, AssistantUpdate, AssistantSelectionUpdate)):
            managed &= update.model_fields_set
        if isinstance(update, ConnectionsUpdate):
            managed -= {name for name in ("tts_base_url", "tts_use_text_connection", "asr_use_text_connection") if getattr(update, name) is None}
        for key_name in ("api_key", "tts_api_key", "rt_api_key", "asr_api_key"):
            if key_name in managed and getattr(update, key_name) is None:
                managed.remove(key_name)
        if isinstance(update, AssistantSelectionUpdate):
            for name in tuple(managed):
                env_value = os.environ.get("AI_" + name.upper())
                if env_value is not None:
                    try:
                        unchanged = json.loads(env_value) == getattr(settings, name)
                    except ValueError:
                        unchanged = False
                    if unchanged:
                        managed.remove(name)
            if not managed:
                return
        overridden = sorted("AI_" + name.upper() for name in managed if "AI_" + name.upper() in os.environ)
        if overridden:
            raise ProviderError(409, "environment_override", "这些环境变量优先于配置文件，请先移除后再保存：" + ", ".join(overridden))
        temp_path = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".env.", suffix=".tmp", delete=False) as handle:
                temp_path = Path(handle.name)
                if self.path.exists():
                    handle.write(self.path.read_text(encoding="utf-8"))
            for name in managed:
                value = getattr(settings, name)
                key = "AI_" + name.upper()
                if value is None:
                    if key in dotenv_values(temp_path, encoding="utf-8"):
                        unset_key(temp_path, key)
                else:
                    if isinstance(value, SecretStr):
                        value = value.get_secret_value()
                    elif isinstance(value, (list, dict)):
                        value = json.dumps(value, ensure_ascii=False)
                    set_key(temp_path, key, str(value), quote_mode="always", encoding="utf-8")
            os.replace(temp_path, self.path)
        except OSError:
            raise ProviderError(500, "config_write_failed", "无法保存本机 .env；请检查文件权限。") from None
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def update_fields(self, settings: Settings, names) -> None:
        overridden = sorted("AI_" + name.upper() for name in names if "AI_" + name.upper() in os.environ)
        if overridden:
            raise ProviderError(409, "environment_override", "这些环境变量优先于配置文件，请先移除后再修改：" + ", ".join(overridden))
        temp_path = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".env.", suffix=".tmp", delete=False) as handle:
                temp_path = Path(handle.name)
                if self.path.exists():
                    handle.write(self.path.read_text(encoding="utf-8"))
            for name in names:
                set_key(temp_path, "AI_" + name.upper(), str(getattr(settings, name)),
                        quote_mode="always", encoding="utf-8")
            os.replace(temp_path, self.path)
        except OSError:
            raise ProviderError(500, "config_write_failed", "无法保存本机 .env；请检查文件权限。") from None
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
