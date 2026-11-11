import asyncio
import base64
import json
import re
from ipaddress import ip_address
from time import perf_counter
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from .llm import ProviderError

SENSITIVE_KEY = re.compile(r"authorization|cookie|password|passwd|token|secret|api[-_]?key|credential", re.I)
MAX_RESPONSE_BYTES = 65536


def validate_url(value):
    value = value.strip()
    p = urlsplit(value)
    loopback = p.hostname == "localhost"
    try:
        loopback = loopback or ip_address(p.hostname or "").is_loopback
    except ValueError:
        pass
    if (p.scheme != "https" and not (p.scheme == "http" and loopback)
            or not p.hostname or p.username or p.password or p.query or p.fragment
            or any(c.isspace() for c in value)):
        raise ValueError("请使用不含凭据和查询参数的 HTTPS 地址；本机回环地址可使用 HTTP")
    if p.port == 0:
        raise ValueError("端口无效")
    return value


class RequestPair(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    key: str = Field(default="", max_length=200)
    value: str | None = Field(default=None, max_length=8192)
    enabled: bool = True
    secret: bool = False

    @model_validator(mode="after")
    def identify_secret(self):
        if SENSITIVE_KEY.search(self.key):
            self.secret = True
        return self


class RequestAuth(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    type: Literal["none", "bearer", "header", "basic"] = "none"
    token: SecretStr | None = None
    header: str = Field(default="Authorization", pattern=r"^[A-Za-z][A-Za-z0-9-]{0,63}$")
    scheme: Literal["Bearer", "raw"] = "Bearer"
    username: str = Field(default="", max_length=200)
    password: SecretStr | None = None

    @field_validator("token", "password")
    @classmethod
    def check_secret(cls, value):
        if value is not None and (len(value.get_secret_value()) > 8192
                or any(c in value.get_secret_value() for c in "\r\n\x00")):
            raise ValueError("鉴权值过长或包含控制字符")
        return value


class RequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    mode: Literal["none", "json", "text", "form"] = "none"
    text: str | None = Field(default=None, max_length=65536)
    fields: list[RequestPair] = Field(default_factory=list, max_length=100)
    secret: bool = False

    @model_validator(mode="after")
    def check_body(self):
        if self.mode == "json" and self.text:
            try:
                value = json.loads(self.text)
            except (ValueError, RecursionError):
                raise ValueError("Body 的 JSON 格式无效") from None
            if contains_secret_fields(value):
                self.secret = True
        return self


def contains_secret_fields(value):
    if isinstance(value, dict):
        return any(SENSITIVE_KEY.search(k) or contains_secret_fields(v) for k, v in value.items())
    if isinstance(value, list):
        return any(contains_secret_fields(v) for v in value)
    return False


class RequestDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] = "GET"
    url: str = Field(min_length=1, max_length=1000)
    params: list[RequestPair] = Field(default_factory=list, max_length=100)
    headers: list[RequestPair] = Field(default_factory=list, max_length=100)
    auth: RequestAuth = Field(default_factory=RequestAuth)
    body: RequestBody = Field(default_factory=RequestBody)
    timeout_seconds: float = Field(default=20, ge=1, le=60)

    @field_validator("url")
    @classmethod
    def check_url(cls, value):
        return validate_url(value)

    @model_validator(mode="after")
    def check_request(self):
        for row in self.headers:
            if row.enabled and row.key:
                if (not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,199}", row.key)
                        or row.key.lower() in {"host", "content-length", "connection", "transfer-encoding"}
                        or row.value and any(c in row.value for c in "\r\n\x00")):
                    raise ValueError("请求头名称或内容无效")
        if self.auth.header.lower() in {"host", "content-length", "connection", "transfer-encoding", "content-type"}:
            raise ValueError("该请求头不能用于鉴权")
        size = sum(len(r.value or "") for r in self.params + self.headers + self.body.fields)
        if size + len(self.body.text or "") > 131072:
            raise ValueError("请求内容超过 128KB")
        return self


class DebugRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    request_id: UUID
    request: RequestDraft
    reuse_tool: str | None = Field(default=None, max_length=48)
    permission: Literal["read", "write", "paid"] = "read"
    confirmed: bool = False


def merge_request(draft, previous=None):
    values = draft.model_dump()
    same_target = previous is not None and draft.url == previous.url
    previous_secrets = secret_values(previous) if previous is not None else []
    if not same_target and previous_secrets:
        missing = draft.auth.type in {"bearer", "header"} and draft.auth.token is None
        missing |= draft.auth.type == "basic" and draft.auth.password is None
        missing |= any(r.secret and r.value is None for r in draft.params + draft.headers + draft.body.fields)
        missing |= draft.body.secret and draft.body.text is None
        if missing:
            raise ProviderError(422, "tool_key_required", "请求地址已更改，请重新填写鉴权及敏感字段。")
    for field in ("params", "headers"):
        old = {r.key.lower() if field == "headers" else r.key: r for r in getattr(previous, field)} if same_target else {}
        for row in values[field]:
            key = row["key"].lower() if field == "headers" else row["key"]
            if row["value"] is None and row["secret"] and key in old:
                row["value"] = old[key].value
    if same_target:
        old_auth = previous.auth
        compatible = (draft.auth.type, draft.auth.header.lower(), draft.auth.scheme, draft.auth.username) == (
            old_auth.type, old_auth.header.lower(), old_auth.scheme, old_auth.username)
        if compatible:
            for key in ("token", "password"):
                if getattr(draft.auth, key) is None:
                    values["auth"][key] = getattr(old_auth, key)
        elif ((draft.auth.type in {"bearer", "header"} and draft.auth.token is None)
                or (draft.auth.type == "basic" and draft.auth.password is None)):
            raise ProviderError(422, "tool_key_required", "鉴权方式已更改，请重新填写鉴权值。")
        old_fields = {r.key: r for r in previous.body.fields}
        for row in values["body"]["fields"]:
            if row["secret"] and row["value"] is None and row["key"] in old_fields:
                row["value"] = old_fields[row["key"]].value
        if draft.body.secret and draft.body.text is None and draft.body.mode == previous.body.mode:
            values["body"]["text"] = previous.body.text
    result = RequestDraft.model_validate(values)
    if result.auth.type in {"bearer", "header"} and result.auth.token is None:
        raise ProviderError(422, "tool_auth_required", "请填写鉴权值，或选择复用同一已存请求的鉴权。")
    if result.auth.type == "basic" and result.auth.password is None:
        raise ProviderError(422, "tool_auth_required", "请填写 Basic 鉴权密码。")
    if any(row.secret and row.value is None for row in result.params + result.headers + result.body.fields):
        raise ProviderError(422, "tool_secret_required", "请补齐敏感字段值，或复用同一已存请求。")
    if result.body.secret and result.body.text is None:
        raise ProviderError(422, "tool_secret_required", "请补齐已隐藏的 Body。")
    return result


def request_dump(draft, *, private=False):
    values = draft.model_dump(mode="json")
    for key in ("token", "password"):
        secret = getattr(draft.auth, key)
        configured = bool(secret and secret.get_secret_value())
        values["auth"][key] = secret.get_secret_value() if private and secret else None
        if not private:
            values["auth"][key + "_configured"] = configured
    for field, rows in (("params", draft.params), ("headers", draft.headers)):
        for index, row in enumerate(rows):
            if not private and row.secret:
                values[field][index]["value"] = ""
                values[field][index]["value_configured"] = row.value is not None
    for index, row in enumerate(draft.body.fields):
        if not private and row.secret:
            values["body"]["fields"][index]["value"] = ""
            values["body"]["fields"][index]["value_configured"] = row.value is not None
    if not private and draft.body.secret:
        values["body"]["text"] = ""
        values["body"]["text_configured"] = draft.body.text is not None
    return values


def secret_values(draft):
    if draft is None:
        return []
    result = [r.value for r in draft.params + draft.headers + draft.body.fields if r.secret and r.value]
    for key in ("token", "password"):
        value = getattr(draft.auth, key)
        if value and value.get_secret_value():
            result.append(value.get_secret_value())
    if draft.auth.type == "basic" and draft.auth.password:
        result.append(base64.b64encode((draft.auth.username + ":" + draft.auth.password.get_secret_value()).encode()).decode())
    if draft.body.secret and draft.body.text:
        result.append(draft.body.text)
        if draft.body.mode == "json":
            def visit(item):
                if isinstance(item, dict):
                    for key, value in item.items():
                        if SENSITIVE_KEY.search(key) and isinstance(value, str) and value:
                            result.append(value)
                        visit(value)
                elif isinstance(item, list):
                    for value in item:
                        visit(value)
            visit(json.loads(draft.body.text))
    return sorted(set(result), key=len, reverse=True)


def redact(text, secrets):
    for value in secrets:
        text = text.replace(value, "[已隐藏]")
    return text


def confirm_request(draft, permission, confirmed):
    if draft.method in {"PUT", "PATCH", "DELETE"} and permission == "read":
        raise ProviderError(422, "tool_permission", "修改或删除接口必须声明 write 或 paid 权限。")
    if permission != "read" and not confirmed:
        raise ProviderError(409, "tool_confirmation_required", "请确认请求地址、参数及修改或付费动作后发送。")


def request_options(draft, arguments=None, argument_target="auto"):
    params = [(row.key, row.value or "") for row in draft.params if row.enabled and row.key]
    headers = {row.key: row.value or "" for row in draft.headers if row.enabled and row.key}
    auth = draft.auth
    if auth.type == "basic":
        value = base64.b64encode((auth.username + ":" + auth.password.get_secret_value()).encode()).decode()
        headers["Authorization"] = "Basic " + value
    elif auth.type in {"bearer", "header"}:
        key = "Authorization" if auth.type == "bearer" else auth.header
        value = auth.token.get_secret_value()
        headers[key] = ("Bearer " if auth.type == "bearer" or auth.scheme == "Bearer" else "") + value
    target = argument_target
    if target == "auto":
        target = "query" if draft.method in {"GET", "HEAD", "OPTIONS"} else "body"
    options = {"params": params, "headers": headers}
    body = draft.body
    dynamic = arguments or {}
    if target == "query":
        if any(isinstance(v, dict) or isinstance(v, list) and any(isinstance(i, (dict, list)) for i in v)
               for v in dynamic.values()):
            raise ProviderError(422, "tool_arguments", "Query 只支持简单参数或简单参数数组。")
        if {key for key, _ in params}.intersection(dynamic):
            raise ProviderError(422, "tool_argument_collision", "模型参数与固定 Params 同名，请移除固定项或更改参数名。")
        options["params"] = params + list(dynamic.items())
    if body.mode == "json":
        try:
            data = json.loads(body.text or "{}")
        except ValueError:
            raise ProviderError(422, "tool_json", "Body 的 JSON 格式无效。") from None
        if target == "body" and dynamic:
            if not isinstance(data, dict) or body.secret:
                raise ProviderError(422, "tool_arguments", "带模型参数的 JSON Body 必须是无隐藏敏感字段的对象。")
            if set(data).intersection(dynamic):
                raise ProviderError(422, "tool_argument_collision", "模型参数与固定 JSON Body 同名，请移除固定项或更改参数名。")
            data = {**data, **dynamic}
        options["json"] = data
    elif body.mode == "form":
        data = {row.key: row.value or "" for row in body.fields if row.enabled and row.key}
        if target == "body" and dynamic:
            raise ProviderError(422, "tool_arguments", "模型参数注入 Body 仅支持 JSON 对象，不支持 Form。")
        options["content"] = str(httpx.QueryParams(data)).encode()
        if not any(k.lower() == "content-type" for k in headers):
            headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body.mode == "text":
        if target == "body" and dynamic:
            raise ProviderError(422, "tool_arguments", "纯文本 Body 不支持注入模型参数，请改用 JSON 或 Form。")
        options["content"] = (body.text or "").encode()
    elif target == "body" and dynamic:
        options["json"] = dynamic
    return options


async def send_request(draft, arguments=None, argument_target="auto", trace=None):
    options = request_options(draft, arguments, argument_target)
    if trace is not None:
        from .audit_store import redact_value
        trace["request"] = redact_value({"method": draft.method, "url": draft.url,
            "params": [{"key": key, "value": value} for key, value in options["params"]],
            "headers": [{"name": key, "value": value} for key, value in options["headers"].items()],
            "json": options.get("json"), "body": options.get("content", b"").decode("utf-8", errors="replace")},
            secret_values(draft))
    started = perf_counter()
    secrets = secret_values(draft)
    try:
        async with asyncio.timeout(draft.timeout_seconds):
            async with httpx.AsyncClient(timeout=draft.timeout_seconds, trust_env=False, follow_redirects=False) as client:
                async with client.stream(draft.method, draft.url, **options) as response:
                    raw = bytearray()
                    truncated = False
                    async for chunk in response.aiter_bytes():
                        remaining = MAX_RESPONSE_BYTES - len(raw)
                        raw.extend(chunk[:remaining])
                        if len(chunk) > remaining:
                            truncated = True
                            break
                    encoding = response.encoding or "utf-8"
                    text = bytes(raw).decode(encoding, errors="replace")
                    headers = [{"name": k, "value": "[已隐藏]" if SENSITIVE_KEY.search(k) else redact(v, secrets)}
                               for k, v in response.headers.multi_items()]
                    result = {"status": response.status_code, "elapsed_ms": round((perf_counter() - started) * 1000),
                              "content_type": response.headers.get("content-type", ""), "headers": headers,
                              "body": redact(text, secrets), "truncated": truncated}
                    if trace is not None:
                        from .audit_store import redact_value
                        trace["response"] = redact_value(result, secrets)
                    return result
    except (TimeoutError, httpx.TimeoutException):
        raise ProviderError(504, "tool_timeout", "请求超时，执行结果未知；未自动重试。") from None
    except (httpx.HTTPError, UnicodeError, LookupError):
        raise ProviderError(502, "tool_connection", "连接或响应解码失败，执行结果未知；未自动重试。") from None
