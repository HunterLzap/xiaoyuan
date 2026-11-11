"""Cloud text-embedding adapter (Bailian, OpenAI-compatible) and local vector math.

Real embedding calls are paid and are only made when the Lead enables them. This
module just wraps the call and provides deterministic cosine / RRF helpers.
"""
import math
import struct

import httpx
from openai import (APIConnectionError, APIError, APITimeoutError, AsyncOpenAI,
                    AuthenticationError, RateLimitError)

from .config import Settings


class EmbeddingError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


def validate_vector(vector, dimensions):
    if (not vector or len(vector) != dimensions
            or any(not isinstance(value, (int, float)) or isinstance(value, bool)
                   or not math.isfinite(value) for value in vector)
            or not any(value != 0 for value in vector)):
        raise EmbeddingError("embedding_vector_invalid", "向量数量、维度或数值无效，未发布资料。")


def to_blob(vector: list[float]) -> bytes:
    validate_vector(vector, len(vector))
    try:
        return struct.pack(f"<{len(vector)}f", *vector)
    except (OverflowError, struct.error):
        raise EmbeddingError("embedding_vector_invalid", "向量无法编码为 float32。") from None


def from_blob(blob: bytes) -> list[float]:
    if not blob or len(blob) % 4:
        raise EmbeddingError("embedding_vector_invalid", "存储向量格式无效。")
    vector = list(struct.unpack(f"<{len(blob) // 4}f", blob))
    validate_vector(vector, len(vector))
    return vector


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def rrf(rank_lists, k: int = 60):
    """Reciprocal rank fusion over ordered key lists; returns [(key, score)] desc."""
    scores: dict = {}
    for ranks in rank_lists:
        for position, key in enumerate(ranks, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + position)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


class BailianEmbedding:
    def __init__(self, base_url: str, api_key: str, model: str = "qwen3.7-text-embedding",
                 dimensions: int = 1024, timeout: float = 20, batch_size: int = 10):
        self.model = model
        self.dimensions = dimensions
        self.batch_size = max(1, min(batch_size, 10))
        self.client = AsyncOpenAI(
            api_key=api_key or "public", base_url=base_url, timeout=timeout, max_retries=0,
            http_client=httpx.AsyncClient(timeout=timeout, trust_env=False),
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            if any(not isinstance(text, str) or not text.strip() or len(text) > 8000 for text in batch):
                raise EmbeddingError("embedding_input", "向量化输入为空或过长，未截断原文。")
            try:
                response = await self.client.embeddings.create(
                    model=self.model, input=batch,
                    dimensions=self.dimensions, encoding_format="float")
            except APITimeoutError:
                raise EmbeddingError("embedding_timeout", "向量化请求超时，未自动重试。") from None
            except AuthenticationError:
                raise EmbeddingError("embedding_auth", "向量化鉴权失败，请检查百炼 Key。") from None
            except RateLimitError:
                raise EmbeddingError("embedding_rate_limit", "向量化被限流，请稍后重试。") from None
            except APIConnectionError:
                raise EmbeddingError("embedding_connection", "无法连接向量化服务。") from None
            except APIError:
                raise EmbeddingError("embedding_error", "向量化服务返回错误。") from None
            if len(response.data) != len(batch) or {item.index for item in response.data} != set(range(len(batch))):
                raise EmbeddingError("embedding_count", "供应商返回的向量数量或顺序索引不完整，未发布资料。")
            for item in sorted(response.data, key=lambda item: item.index):
                vector = list(item.embedding)
                validate_vector(vector, self.dimensions)
                vectors.append(vector)
        return vectors

    async def close(self):
        await self.client.close()


def build_embedder(settings: Settings):
    if not getattr(settings, "embedding_enabled", False):
        return None
    key = settings.rt_api_key.get_secret_value() if settings.rt_api_key else ""
    workspace = settings.rt_workspace
    if not key or not workspace:
        return None
    base_url = f"https://{workspace}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    return BailianEmbedding(base_url, key, settings.embedding_model,
                            settings.embedding_dimensions, timeout=settings.timeout_seconds)
