"""Read-only M5Stack documentation adapter; no remote agent or feedback calls."""
import ast
import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
import html
import json
import re
from typing import Protocol
from urllib.parse import unquote, urljoin, urlsplit

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client

from .llm import ProviderError
from .schemas import KnowledgeDocument, KnowledgeResult, KnowledgeSearchRequest, KnowledgeSource

M5STACK_URL = "https://mcp.m5stack.com/sse"
SEARCH_TOOL = "knowledge_search"
MAX_REMOTE_CHARS = 250_000
MAX_DOCUMENTS = 5
MAX_CONTEXT_CHARS = 6000
VERIFIED_PRODUCT_URLS = {
    "AtomS3R-AI Chatbot": "https://docs.m5stack.com/zh_CN/core/AtomS3R-AI_Chatbot",
    "AtomS3R-CAM AI Chatbot": "https://docs.m5stack.com/zh_CN/core/AtomS3R-CAM_AI_Chatbot",
    "Atomic Voice Base": "https://docs.m5stack.com/zh_CN/atom/Atomic_Voice_Base",
    "Atomic Echo Base": "https://docs.m5stack.com/zh_CN/atom/Atomic_Voice_Base",
}
K147_COMPONENTS = {"atoms3r", "atoms3raichatbot", "atomicvoicebase", "atomicechobase",
                   "es8311", "bmi270", "bmm150", "esp32s3pico1n8r8",
                   "m5atomicechobase", "m5atoms3", "m5unified", "m5gfx"}


def connection_error(error: Exception) -> ProviderError:
    errors = []
    def collect(item):
        if isinstance(item, BaseExceptionGroup):
            for child in item.exceptions:
                collect(child)
        else:
            errors.append(item)
    collect(error)
    for item in errors:
        if isinstance(item, ProviderError):
            return item
    if any(isinstance(item, (TimeoutError, httpx.TimeoutException)) for item in errors):
        return ProviderError(504, "m5stack_timeout", "M5Stack 官方资料服务响应超时，请稍后重试。")
    for item in errors:
        if isinstance(item, httpx.HTTPStatusError):
            return ProviderError(502, "m5stack_http_error", f"M5Stack 官方资料服务返回 HTTP {item.response.status_code}，请稍后重试。")
    if any(isinstance(item, httpx.TransportError) for item in errors):
        return ProviderError(502, "m5stack_network_error", "无法建立资料连接，请检查本机网络或代理能否访问 mcp.m5stack.com。")
    return ProviderError(502, "m5stack_unavailable", "资料接口握手或响应异常，请稍后重新测试连接。")


class KnowledgeProvider(Protocol):
    async def search(self, request: KnowledgeSearchRequest) -> KnowledgeResult: ...
    async def status(self) -> dict: ...


def clean_markup(text: str) -> str:
    # Remove document presentation tags, while keeping C++ headers such as <Arduino.h>.
    return re.sub(r"</?(?:img|span|div|p|br|PictureViewer|SchViewer|a|table|tr|td|th|thead|tbody|strong|em)\b[^>]*>", "", text, flags=re.IGNORECASE)


def official_url(value: str) -> str | None:
    url = urljoin("https://docs.m5stack.com/", html.unescape(value.strip()))
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password or parts.port not in {None, 443}:
        return None
    if parts.hostname == "github.com":
        path = unquote(parts.path)
        return url if path.startswith("/m5stack/") and ".." not in path.split("/") else None
    if parts.hostname in {"docs.m5stack.com", "uiflow-micropython.readthedocs.io",
                          "m5stack.oss-cn-shenzhen.aliyuncs.com", "m5stack-doc.oss-cn-shenzhen.aliyuncs.com",
                          "static-cdn.m5stack.com"}:
        return url
    return None


def unwrap_text(text: str) -> str:
    text = text[:MAX_REMOTE_CHARS].strip()
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except (ValueError, RecursionError):
            # The official service currently returns a Python dict repr inside `text`.
            # Read only literal string nodes, never evaluate remote expressions.
            try:
                tree = ast.parse(text, mode="eval").body
                payload = {key.value: value.value for key, value in zip(tree.keys, tree.values)
                           if isinstance(key, ast.Constant) and isinstance(value, ast.Constant)} if isinstance(tree, ast.Dict) else {}
            except (SyntaxError, ValueError, RecursionError):
                payload = {}
        if isinstance(payload, dict):
            for name in ("info", "text", "content"):
                if isinstance(payload.get(name), str):
                    return payload[name][:MAX_REMOTE_CHARS]
    return text


def parse_search_result(query: str, text: str) -> KnowledgeResult:
    text = unwrap_text(text)
    candidates = []
    terms = set(re.findall(r"[a-zA-Z0-9][a-zA-Z0-9_-]{2,}", query.casefold()))
    terms.update(part[index:index+2] for part in re.findall(r"[\u4e00-\u9fff]{2,}", query) for index in range(len(part)-1))
    exact_k147 = bool(re.search(r"(?<![A-Za-z0-9_-])K147(?![A-Za-z0-9_-])", query, re.IGNORECASE)) and "K147-CAM" not in query.upper() and "ATOMS3R-CAM" not in query.upper()
    for chunk in re.split(r"\n---\s*\n", text):
        title_match = re.search(r"^分段标题[:：]\s*(.+)$", chunk, re.MULTILINE)
        content_match = re.search(r"^分段内容[:：](.*)", chunk, re.MULTILINE | re.DOTALL)
        if not content_match:
            continue
        product_match = re.search(r"^产品名[:：]\s*(.+)$", chunk, re.MULTILINE)
        product = product_match[1].strip() if product_match else ""
        title = title_match[1].strip() if title_match else product or "官方资料"
        clean_product = re.split(r"\s*\(SKU[:：]", product.removeprefix("schematic "), flags=re.IGNORECASE)[0].strip()
        if exact_k147 and product:
            normalized_product = re.sub(r"[^a-z0-9]", "", clean_product.casefold())
            if normalized_product not in K147_COMPONENTS:
                continue
        body = content_match[1]
        # Ignore wrappers/instructions around retrieved documents, and image markup.
        body = re.split(r"\n请忽略以上参考资料", body, maxsplit=1)[0]
        body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)
        body = clean_markup(body)
        body = html.unescape(body).strip()
        if not body:
            continue
        if re.fullmatch(r"SKU\s*[:：]\s*[A-Za-z0-9-]+", body, re.IGNORECASE):
            continue
        source_url = None
        source_url = VERIFIED_PRODUCT_URLS.get(clean_product)
        links = []
        for match in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", body):
            try:
                url = official_url(match[2])
            except ValueError:
                url = None
            if url:
                links.append(KnowledgeSource(title=match[1].strip()[:160], url=url))
        score = sum(4 if term in product.casefold() or term in title.casefold() else 1
                    for term in terms if term in (product + title + body).casefold())
        if exact_k147:
            score += 8 if re.search(r"SKU:K147\)", product) or clean_product == "AtomS3R-AI Chatbot" else 0
        candidates.append((score, KnowledgeDocument(title=title, product=product, excerpt=body, source_url=source_url), links))
    if not candidates and text.strip() and "分段内容" not in text:
        # Preserve a plain documented response instead of pretending it is empty.
        body = html.unescape(clean_markup(text)).strip()
        if body:
            candidates.append((0, KnowledgeDocument(title="M5Stack 官方检索结果", excerpt=body), []))
    candidates.sort(key=lambda item: item[0], reverse=True)
    documents, sources, seen, remaining = [], [], set(), MAX_CONTEXT_CHARS
    truncated = len(candidates) > MAX_DOCUMENTS
    for _, document, links in candidates[:MAX_DOCUMENTS]:
        original = document.excerpt
        document.excerpt = original[:min(1600, remaining)]
        truncated |= len(document.excerpt) < len(original)
        remaining -= len(document.excerpt)
        documents.append(document)
        if document.source_url:
            links.insert(0, KnowledgeSource(title=document.product or document.title, url=document.source_url))
        for source in links:
            if source.url not in seen and len(sources) < 12:
                sources.append(source); seen.add(source.url)
        if remaining <= 0:
            truncated |= len(documents) < min(len(candidates), MAX_DOCUMENTS)
            break
    return KnowledgeResult(query=query, status="success" if documents else "empty", documents=documents,
                           sources=sources, total_matches=len(candidates), truncated=truncated)


class M5StackKnowledge:
    def __init__(self, timeout_seconds: float = 40):
        self.timeout_seconds = timeout_seconds
        self.slots = asyncio.Semaphore(2)

    @asynccontextmanager
    async def session(self):
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async with self.slots:
                    async with sse_client(M5STACK_URL, timeout=min(self.timeout_seconds, 15),
                                          sse_read_timeout=self.timeout_seconds) as streams:
                        async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=self.timeout_seconds)) as session:
                            await session.initialize()
                            listed = await session.list_tools()
                            tool = next((tool for tool in listed.tools if tool.name == SEARCH_TOOL), None)
                            if (tool is None or tool.annotations is None or tool.annotations.readOnlyHint is not True
                                    or set(tool.inputSchema.get("required", [])) != {"query"}
                                    or tool.inputSchema.get("properties", {}).get("query", {}).get("type") != "string"):
                                raise ProviderError(502, "m5stack_incompatible", "官方检索接口发生变化，暂时无法安全调用。")
                            yield session, tool
        except ProviderError:
            raise
        except TimeoutError:
            raise ProviderError(504, "m5stack_timeout", "M5Stack 官方资料检索超时，请稍后重试。") from None
        except Exception as error:
            raise connection_error(error) from None

    async def status(self) -> dict:
        async with self.session():
            return {"connected": True, "server_url": M5STACK_URL, "tool_name": SEARCH_TOOL, "read_only": True}

    async def search(self, request: KnowledgeSearchRequest) -> KnowledgeResult:
        async with self.session() as (session, tool):
            arguments = {"query": request.query}
            properties = tool.inputSchema["properties"]
            if request.is_chip:
                if "is_chip" not in properties:
                    raise ProviderError(502, "m5stack_incompatible", "官方接口暂不支持芯片资料过滤。")
                arguments["is_chip"] = True
            if request.filter_type:
                if "filter_type" not in properties:
                    raise ProviderError(502, "m5stack_incompatible", "官方接口暂不支持分类过滤。")
                arguments["filter_type"] = request.filter_type
            result = await session.call_tool(SEARCH_TOOL, arguments)
            if result.isError:
                raise ProviderError(502, "m5stack_search_failed", "官方知识库查询失败，请换个关键词重试。")
            payload = result.structuredContent
            if payload is None:
                blocks = [block.text for block in result.content if block.type == "text"]
                raw = "\n".join(blocks)[:MAX_REMOTE_CHARS]
                try:
                    payload = json.loads(raw)
                except ValueError:
                    payload = {"text": raw, "outcome": "success"}
            if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
                raise ProviderError(502, "m5stack_invalid_response", "官方知识库返回了不兼容的结果。")
            if payload.get("outcome") not in {"success", "empty", "no_results", "not_found"}:
                raise ProviderError(502, "m5stack_search_failed", "官方知识库未能完成查询，请稍后重试。")
            if payload.get("outcome") != "success":
                return parse_search_result(request.query, "")
            return parse_search_result(request.query, payload["text"])
