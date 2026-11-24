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


def _client() -> httpx.AsyncClient:
    global _SHARED_CLIENT
    if _SHARED_CLIENT is None or _SHARED_CLIENT.is_closed:
        _SHARED_CLIENT = httpx.AsyncClient(timeout=10.0, trust_env=False, follow_redirects=False)
    return _SHARED_CLIENT


async def close_web_search_client() -> None:
    global _SHARED_CLIENT
    client, _SHARED_CLIENT = _SHARED_CLIENT, None
    _CACHE.clear()
    if client is not None and not client.is_closed:
        await client.aclose()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def search_web(settings: Settings, query: str, count: int = 5) -> dict:
    api_key = resolve_web_search_api_key(settings)
    if not api_key:
        raise WebSearchError("web_search_not_configured", "尚未配置 DeepSeek 联网搜索密钥（AI_WEB_SEARCH_API_KEY）。", 422)
    clean_q = query.strip()
    if not 1 <= len(clean_q) <= 128:
        raise WebSearchError("web_search_query_invalid", "DeepSeek 搜索词须为 1 到 128 个字符。", 422)
    count = max(1, min(count, 5))
    cache_key = f"{count}|{clean_q.lower()}"
    cached = _CACHE.get(cache_key)
    if cached and monotonic() < cached[0]:
        return {**cached[1], "query": clean_q}

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
    result = {"query": clean_q, "provider": "deepseek", "fetched_at": _utc_now(), "results": items}
    _CACHE.pop(cache_key, None)
    if len(_CACHE) >= _CACHE_LIMIT:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[cache_key] = (monotonic() + _CACHE_TTL, result)
    return result
