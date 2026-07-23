"""Embedding providers for knowledge-base semantic search.

Providers implement a tiny protocol:
    provider_id  — stable "provider:model:dim" string stored per embedding row;
                   a mismatch marks the row stale and triggers re-embedding.
    dim          — output dimension
    embed(texts) — batch-embed a list of strings into unit-normalized vectors

Three implementations:
    HashingEmbedder    — deterministic char-n-gram + word feature hashing.
                         No network, no deps, fully offline. Lexical rather
                         than truly semantic, but gives real vector-similarity
                         behavior (typo tolerance, partial overlap) and makes
                         the whole pipeline testable without an API key.
    OpenAICompatEmbedder — POST {base_url}/embeddings (OpenAI shape). Works
                         with OpenAI, Ollama, vLLM, TEI, LM Studio.
    VoyageEmbedder     — POST https://api.voyageai.com/v1/embeddings
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from typing import Protocol

from gateway.config.embeddings import get_embeddings_settings

logger = logging.getLogger(__name__)

_MAX_EMBED_CHARS = 8000  # cap per-text input; KB docs are chunk-free for now


class EmbeddingProvider(Protocol):
    provider_id: str
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two same-length vectors (0.0 on mismatch)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))  # inputs are unit-normalized


_WORD_RE = re.compile(r"[a-z0-9_]+")


class HashingEmbedder:
    """Deterministic feature-hashing embedder (signed hashing trick).

    Tokens: lowercase words plus character 3–5 grams of each word. Each token
    hashes to a (bucket, sign) pair; counts are accumulated sublinearly
    (sqrt) and the vector is L2-normalized. Deterministic across processes.
    """

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self.provider_id = f"hash:v1:{dim}"

    def _tokens(self, text: str):
        for word in _WORD_RE.findall(text.lower()):
            yield "w:" + word
            padded = f"^{word}$"
            for n in (3, 4, 5):
                if len(padded) >= n:
                    for i in range(len(padded) - n + 1):
                        yield f"g{n}:" + padded[i : i + n]

    def _embed_one(self, text: str) -> list[float]:
        counts: dict[int, float] = {}
        for token in self._tokens(text[:_MAX_EMBED_CHARS]):
            h = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big")
            bucket = h % self.dim
            sign = 1.0 if (h >> 60) & 1 else -1.0
            counts[bucket] = counts.get(bucket, 0.0) + sign
        vec = [0.0] * self.dim
        for bucket, val in counts.items():
            vec[bucket] = math.copysign(math.sqrt(abs(val)), val) if val else 0.0
        return _l2_normalize(vec)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]


class OpenAICompatEmbedder:
    """OpenAI-compatible /embeddings endpoint (OpenAI, Ollama, vLLM, TEI...)."""

    def __init__(self, *, model: str, api_key: str, base_url: str = "", dim: int = 0) -> None:
        self.model = model or "text-embedding-3-small"
        self.api_key = api_key
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.dim = dim or 1536
        self.provider_id = f"openai:{self.model}:{self.dim}"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx

        payload: dict = {"model": self.model, "input": [t[:_MAX_EMBED_CHARS] for t in texts]}
        if self.dim:
            payload["dimensions"] = self.dim
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{self.base_url}/embeddings", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()["data"]
        data.sort(key=lambda d: d["index"])
        return [_l2_normalize(d["embedding"]) for d in data]


class VoyageEmbedder:
    """Voyage AI embeddings (Anthropic's recommended embedding partner)."""

    def __init__(self, *, model: str, api_key: str, dim: int = 0) -> None:
        self.model = model or "voyage-3-lite"
        self.api_key = api_key
        self.dim = dim or 512
        self.provider_id = f"voyage:{self.model}:{self.dim}"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx

        payload = {"model": self.model, "input": [t[:_MAX_EMBED_CHARS] for t in texts]}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post("https://api.voyageai.com/v1/embeddings", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()["data"]
        data.sort(key=lambda d: d["index"])
        return [_l2_normalize(d["embedding"]) for d in data]


def get_embedding_provider() -> EmbeddingProvider | None:
    """Build the configured provider, or None when embeddings are disabled.

    Misconfiguration (e.g. openai selected but no API key and a non-local
    base_url) falls back to the hash provider rather than failing search.
    """
    cfg = get_embeddings_settings()
    if not cfg.enabled:
        return None

    def _hash_fallback() -> HashingEmbedder:
        return HashingEmbedder(dim=cfg.dim or 384)

    if cfg.provider == "hash":
        return _hash_fallback()
    if cfg.provider == "openai":
        if not cfg.api_key and not cfg.base_url:
            logger.warning("SP_EMBEDDINGS_PROVIDER=openai but no API key/base URL; falling back to hash")
            return _hash_fallback()
        return OpenAICompatEmbedder(model=cfg.model, api_key=cfg.api_key, base_url=cfg.base_url, dim=cfg.dim)
    if cfg.provider == "voyage":
        if not cfg.api_key:
            logger.warning("SP_EMBEDDINGS_PROVIDER=voyage but no API key; falling back to hash")
            return _hash_fallback()
        return VoyageEmbedder(model=cfg.model, api_key=cfg.api_key, dim=cfg.dim)
    logger.warning("Unknown SP_EMBEDDINGS_PROVIDER=%r; falling back to hash", cfg.provider)
    return _hash_fallback()
