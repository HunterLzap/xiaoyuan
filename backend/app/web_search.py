from datetime import datetime, timezone
from time import monotonic
from urllib.parse import urlsplit

import httpx

from .config import Settings
from .llm import ProviderError


_SEARCH_URL = "https://api.deepseek.com/v1/tools/search"
_CACHE_TTL = 180.0
_CACHE_LIMIT = 64
_CACHE: dict[str, tuple[float, dict]] = {}
_SHARED_CLIENT: httpx.AsyncClient | None = None


class WebSearchError(ProviderError):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(status, code, message)


def resolve_web_search_api_key(settings: Settings) -> str:
    key = settings.web_search_api_key.get_secret_value().strip()
    if key:
        return key
    host = (urlsplit(settings.base_url or "").hostname or "").rstrip(".")
    if host == "deepseek.com" or host.endswith(".deepseek.com"):
        return settings.api_key.get_secret_value().strip()
    return ""


def resolve_web_search_provider(settings: Settings) -> tuple[str, str]:
    deepseek_key = resolve_web_search_api_key(settings)
    if deepseek_key:
        return "deepseek", deepseek_key
    rt_key = settings.rt_api_key.get_secret_value().strip()
    if getattr(settings, "rt_provider", "") == "bailian" and rt_key:
        return "bailian", rt_key
    host = (urlsplit(settings.base_url or "").hostname or "").lower()
    text_key = settings.api_key.get_secret_value().strip()
    if "aliyuncs.com" in host and text_key:
        return "bailian", text_key
    return "", ""


def _bailian_search_url(settings: Settings) -> str:
    ws = (getattr(settings, "rt_workspace", "") or "").strip()
    return (
        f"https://{ws}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions"
        if ws else "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    )


def _client() -> httpx.AsyncClient:
    global _SHARED_CLIENT
    if _SHARED_CLIENT is None or _SHARED_CLIENT.is_closed:
        _SHARED_CLIENT = httpx.AsyncClient(timeout=20.0, trust_env=False, follow_redirects=False)
    return _SHARED_CLIENT


def _safe_upstream_detail(response: httpx.Response, secret: str) -> str:
    detail = ""
    try:
        data = response.json()
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict):
            detail = str(err.get("message") or err.get("code") or "")
        elif isinstance(data, dict):
            detail = str(data.get("message") or "")
    except ValueError:
        detail = response.text or ""
    if secret:
        detail = detail.replace(secret, "***")
    return " ".join(detail.split())[:140]


async def close_web_search_client() -> None:
    global _SHARED_CLIENT
    client, _SHARED_CLIENT = _SHARED_CLIENT, None
    _CACHE.clear()
    if client is not None and not client.is_closed:
        await client.aclose()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def _search_deepseek(api_key: str, clean_q: str, count: int) -> dict:
    try:
        response = await _client().post(
            _SEARCH_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"query": clean_q, "count": count, "need_content": False},
        )
    except (TimeoutError, httpx.TimeoutException):
        raise WebSearchError("web_search_timeout", "DeepSeek 联网搜索超时。", 504) from None
    except httpx.HTTPError:
        raise WebSearchError("web_search_unavailable", "暂时无法连接 DeepSeek 联网搜索。", 502) from None

    if response.status_code != 200:
        raise WebSearchError("web_search_upstream_error", "DeepSeek 联网搜索请求失败。", 502)
    try:
        payload = response.json()
        if not isinstance(payload["results"], list):
            raise ValueError()
        items = [{
            "title": item["title"][:120],
            "url": item["url"][:300],
            "summary": (item.get("summary") or item.get("snippet") or "")[:300],
            "score": item.get("rerank_score"),
        } for item in payload["results"][:count]]
    except (ValueError, KeyError, TypeError, AttributeError):
        raise WebSearchError("web_search_upstream_error", "DeepSeek 联网搜索返回的数据格式无效。", 502) from None
    return {"query": clean_q, "provider": "deepseek", "fetched_at": _utc_now(), "results": items}


async def _search_bailian(settings: Settings, api_key: str, clean_q: str, count: int) -> dict:
    try:
        response = await _client().post(
            _bailian_search_url(settings),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "qwen-flash",
                "messages": [
                    {"role": "system", "content": "请联网检索最新事实，用简洁中文客观总结关键数据与结论（不超过200字），不要编造。"},
                    {"role": "user", "content": clean_q},
                ],
                "stream": False,
                "enable_thinking": False,
                "enable_search": True,
                "search_options": {"search_strategy": "turbo", "enable_source": True, "forced_search": True},
                "temperature": 0.1,
                "max_tokens": 300,
            },
        )
    except (TimeoutError, httpx.TimeoutException):
        raise WebSearchError("web_search_timeout", "百炼联网搜索超时。", 504) from None
    except httpx.HTTPError:
        raise WebSearchError("web_search_unavailable", "暂时无法连接百炼联网搜索。", 502) from None

    if response.status_code != 200:
        detail = _safe_upstream_detail(response, api_key)
        suffix = f"（HTTP {response.status_code}：{detail}）" if detail else f"（HTTP {response.status_code}）"
        raise WebSearchError("web_search_upstream_error", f"百炼联网搜索请求失败{suffix}。", 502)
    try:
        payload = response.json()
        choice = (payload.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        answer = (message.get("content") or "").strip()
        raw_results = (
            (payload.get("search_info") or {}).get("search_results")
            or message.get("search_results")
            or []
        )
        items = [
            {
                "title": (item.get("title") or clean_q)[:120],
                "url": (item.get("url") or "")[:300],
                "summary": (item.get("summary") or item.get("snippet") or "")[:300],
                "score": None,
            }
            for item in raw_results[:count]
            if isinstance(item, dict)
        ]
        if not items:
            if not answer:
                raise ValueError()
            items = [{"title": clean_q[:120], "url": "", "summary": answer[:300], "score": None}]
        elif answer and not items[0]["summary"]:
            items[0]["summary"] = answer[:300]
    except (ValueError, KeyError, TypeError, AttributeError, IndexError):
        raise WebSearchError("web_search_upstream_error", "百炼联网搜索返回的数据格式无效。", 502) from None
    return {
        "query": clean_q,
        "provider": "bailian",
        "fetched_at": _utc_now(),
        "answer": answer[:500],
        "results": items,
    }


async def search_web(settings: Settings, query: str, count: int = 5) -> dict:
    provider, api_key = resolve_web_search_provider(settings)
    if not api_key:
        raise WebSearchError(
            "web_search_not_configured",
            "尚未配置联网搜索密钥（已配置百炼密钥时会自动复用，或填写 DeepSeek API Key）。",
            422,
        )
    clean_q = query.strip()
    if not 1 <= len(clean_q) <= 128:
        raise WebSearchError("web_search_query_invalid", "搜索词须为 1 到 128 个字符。", 422)
    count = max(1, min(count, 5))
    cache_key = f"{provider}|{count}|{clean_q.lower()}"
    cached = _CACHE.get(cache_key)
    if cached and monotonic() < cached[0]:
        return {**cached[1], "query": clean_q}

    if provider == "bailian":
        result = await _search_bailian(settings, api_key, clean_q, count)
    else:
        result = await _search_deepseek(api_key, clean_q, count)

    _CACHE.pop(cache_key, None)
    if len(_CACHE) >= _CACHE_LIMIT:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[cache_key] = (monotonic() + _CACHE_TTL, result)
    return result
