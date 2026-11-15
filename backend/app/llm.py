from dataclasses import dataclass, field
from typing import Protocol

import httpx
from openai import (
    APIConnectionError, APIError, APITimeoutError, AsyncOpenAI,
    AuthenticationError, RateLimitError,
    APIStatusError, Omit,
)

from .config import Settings
from .schemas import TokenUsage

FINISH_REASONS = {"stop", "length", "tool_calls", "content_filter", "function_call"}


class ProviderError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


@dataclass
class Completion:
    reply: str | None
    usage: TokenUsage | None
    finish_reason: str | None
    reasoning_tokens: int | None = None
    tool_calls: list[dict] = field(default_factory=list)

    def empty_response_error(self, max_tokens: int | None) -> ProviderError:
        output = self.usage.completion_tokens if self.usage is not None else None
        details = (
            f"结束原因：{self.finish_reason or '未提供'}；"
            f"输出 Token：{output if output is not None else '未知'}；"
            f"思考 Token：{self.reasoning_tokens if self.reasoning_tokens is not None else '未报告'}"
        )
        if self.finish_reason == "length":
            limit = f"当前请求上限为 {max_tokens} Token" if max_tokens is not None else "当前请求使用服务端默认上限"
            return ProviderError(
                502, "output_limit",
                f"上游报告达到输出上限，尚未返回最终正文；{limit}。{details}。未自动重试。",
            )
        if self.finish_reason == "content_filter":
            return ProviderError(502, "content_filtered", f"上游内容过滤结束，未返回最终正文。{details}。")
        return ProviderError(502, "empty_response", f"上游响应没有最终正文。{details}。未自动重试。")


def completion_metadata(usage, finish_reason) -> Completion:
    details = getattr(usage, "completion_tokens_details", None)
    reasoning_tokens = getattr(details, "reasoning_tokens", None)
    return Completion(
        reply=None, usage=TokenUsage.from_provider(usage),
        finish_reason=finish_reason if finish_reason in FINISH_REASONS else None,
        reasoning_tokens=reasoning_tokens if type(reasoning_tokens) is int and reasoning_tokens >= 0 else None,
    )


class ChatProvider(Protocol):
    async def complete(self, messages: list[dict[str, str]]) -> Completion: ...
    async def close(self) -> None: ...


class StreamingChatProvider(Protocol):
    """Provider that can also yield tokens as they arrive."""

    def complete_stream(self, messages: list[dict[str, str]]): ...


class OpenAICompatibleProvider:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.client = AsyncOpenAI(
            api_key=settings.api_key.get_secret_value() or "public-catalog", base_url=settings.base_url,
            timeout=settings.timeout_seconds, max_retries=0,
            http_client=http_client or httpx.AsyncClient(
                timeout=settings.timeout_seconds, trust_env=False),
        )

    async def list_models(self) -> dict[str, list[str]]:
        public_catalog = self.settings.base_url == "https://tokendance.space/gateway/v1"
        if (self.settings.models_protocol == "disabled" or
                (self.settings.models_protocol == "auto" and not public_catalog
                 and self.settings.base_url != "https://api.openai.com/v1")):
            raise ProviderError(422, "models_unsupported", "尚未确认此地址的模型列表协议。可手填模型 ID，或查阅供应商文档后选择 OpenAI 列表协议。")
        if not public_catalog and not self.settings.api_key.get_secret_value().strip():
            raise ProviderError(422, "not_configured", "获取模型列表前请填写 API Key。")
        try:
            data = await self.client.get("models", cast_to=object, options={
                "headers": {"Authorization": Omit()} if public_catalog else {},
            })
            if not isinstance(data, dict) or not isinstance(data.get("data"), list):
                raise ValueError()
            chat, speech = set(), set()
            for item in data["data"]:
                if not isinstance(item, dict):
                    raise ValueError()
                model = item.get("id")
                if not isinstance(model, str) or not model.strip() or len(model) > 200:
                    raise ValueError()
                if public_catalog:
                    protocols = item.get("supported_protocols")
                    if not isinstance(protocols, list):
                        raise ValueError()
                    if "openai:chat-completions" not in protocols:
                        continue
                lowered = model.lower()
                # Voice cloning needs reference audio, which this build does not send.
                if "voiceclone" in lowered:
                    continue
                if any(tag in lowered for tag in ("-tts", "tts-", "speech", "voice")):
                    speech.add(model)
                else:
                    chat.add(model)
            return {"chat": sorted(chat), "speech": sorted(speech)}
        except APITimeoutError:
            raise ProviderError(504, "models_timeout", "获取模型列表超时；输入已保留，可重试或手填模型 ID。") from None
        except AuthenticationError:
            raise ProviderError(502, "models_auth", "模型列表鉴权失败；请检查 API Key。") from None
        except RateLimitError:
            raise ProviderError(503, "models_rate_limit", "模型列表请求受限；请稍后重试或手填模型 ID。") from None
        except APIConnectionError:
            raise ProviderError(502, "models_connection", "无法连接模型列表接口；请检查地址和网络。") from None
        except APIStatusError as error:
            if error.status_code in {404, 405, 501}:
                raise ProviderError(502, "models_unsupported", "此地址未提供已选协议的模型列表接口；请手填模型 ID。") from None
            if error.status_code == 403:
                raise ProviderError(502, "models_forbidden", "无权获取模型列表；请检查密钥权限，或手填模型 ID。") from None
            raise ProviderError(502, "models_error", "获取模型列表失败；请核对接口地址和供应商状态。") from None
        except (APIError, AttributeError, TypeError, ValueError):
            raise ProviderError(502, "models_invalid_response", "模型列表响应不符合已选协议；请手填模型 ID。") from None

    def _request_options(self) -> dict:
        options = {} if self.settings.max_tokens is None else {"max_tokens": self.settings.max_tokens}
        # reasoning_effort is only valid on thinking models that expose it (spark here);
        # sending it to a plain deepseek/mimo model is rejected with 400, so gate by model.
        if self.settings.reasoning_effort and self.settings.model.lower().startswith("spark"):
            options["reasoning_effort"] = self.settings.reasoning_effort
        return options

    async def complete(self, messages: list[dict[str, str]]) -> Completion:
        if self.settings.model in {"mimo-v2.5-tts", "mimo-v2.5-tts-voicedesign", "mimo-v2.5-tts-voiceclone"}:
            raise ProviderError(422, "tts_model_in_text", "这是语音合成模型，请在设置的“语音合成”中配置和试听；文字聊天请选择文字模型。")
        try:
            options = self._request_options()
            response = await self.client.chat.completions.create(
                model=self.settings.model, messages=messages,
                stream=False, **options,
            )
            choice = response.choices[0] if response.choices else None
            content = choice.message.content if choice and choice.message else None
            result = completion_metadata(response.usage, choice.finish_reason if choice else None)
            result.reply = content if isinstance(content, str) else None
            return result
        except APITimeoutError:
            raise ProviderError(504, "upstream_timeout", "模型请求超时；可稍后重试。") from None
        except AuthenticationError:
            raise ProviderError(502, "upstream_auth", "模型服务鉴权失败；请检查本机 AI_API_KEY。") from None
        except RateLimitError:
            raise ProviderError(503, "upstream_rate_limit", "模型服务限流或额度不足；请检查控制台。") from None
        except APIConnectionError:
            raise ProviderError(502, "upstream_connection", "无法连接模型服务；请检查网络和 AI_BASE_URL。") from None
        except APIError:
            raise ProviderError(502, "upstream_error", "模型服务拒绝请求；请检查模型 ID 和接口参数。") from None
        except (AttributeError, TypeError, ValueError, IndexError):
            raise ProviderError(502, "invalid_response", "模型服务返回了不兼容的响应。") from None

    async def complete_stream(self, messages: list[dict], *, tools=None):
        """Yield reply text followed by completion metadata."""
        if self.settings.model in {"mimo-v2.5-tts", "mimo-v2.5-tts-voicedesign", "mimo-v2.5-tts-voiceclone"}:
            raise ProviderError(422, "tts_model_in_text", "这是语音合成模型，请在设置的“语音合成”中配置和试听；文字聊天请选择文字模型。")
        try:
            options = self._request_options()
            if tools:
                options["tools"] = tools
            stream = await self.client.chat.completions.create(
                model=self.settings.model, messages=messages,
                stream=True, **options,
            )
            usage = None
            finish_reason = None
            tool_calls = {}
            async with stream:
                async for chunk in stream:
                    if chunk.usage is not None:
                        usage = chunk.usage
                    choices = getattr(chunk, "choices", None)
                    if not choices:
                        continue
                    if choices[0].finish_reason is not None:
                        finish_reason = choices[0].finish_reason
                    delta = getattr(choices[0], "delta", None)
                    piece = getattr(delta, "content", None) if delta is not None else None
                    if isinstance(piece, str) and piece:
                        yield piece
                    for call in (getattr(delta, "tool_calls", None) or []) if delta is not None else []:
                        index = getattr(call, "index", 0) or 0
                        state = tool_calls.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                        if getattr(call, "id", None):
                            state["id"] = call.id
                        function = getattr(call, "function", None)
                        if function is not None:
                            if getattr(function, "name", None):
                                state["function"]["name"] += function.name
                            if getattr(function, "arguments", None):
                                state["function"]["arguments"] += function.arguments
            result = completion_metadata(usage, finish_reason)
            result.tool_calls = [tool_calls[index] for index in sorted(tool_calls)]
            yield result
        except APITimeoutError:
            raise ProviderError(504, "upstream_timeout", "模型请求超时；可稍后重试。") from None
        except AuthenticationError:
            raise ProviderError(502, "upstream_auth", "模型服务鉴权失败；请检查本机 AI_API_KEY。") from None
        except RateLimitError:
            raise ProviderError(503, "upstream_rate_limit", "模型服务限流或额度不足；请检查控制台。") from None
        except APIConnectionError:
            raise ProviderError(502, "upstream_connection", "无法连接模型服务；请检查网络和 AI_BASE_URL。") from None
        except APIError:
            raise ProviderError(502, "upstream_error", "模型服务拒绝请求；请检查模型 ID 和接口参数。") from None
        except (AttributeError, TypeError, ValueError, IndexError):
            raise ProviderError(502, "invalid_response", "模型服务返回了不兼容的响应。") from None

    async def close(self) -> None:
        await self.client.close()
