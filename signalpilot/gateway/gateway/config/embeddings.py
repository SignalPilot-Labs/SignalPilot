"""Knowledge-base embedding settings for the gateway.

Class A vars managed here:
    SP_EMBEDDINGS_PROVIDER   — hash | openai | voyage | none (default: hash)
                               "hash" is a deterministic, dependency-free local
                               feature-hashing embedder: works offline, decent
                               lexical recall, no API cost. Use openai/voyage
                               for true semantic quality.
    SP_EMBEDDINGS_MODEL      — provider model name (e.g. text-embedding-3-small,
                               voyage-3-lite). Ignored by hash.
    SP_EMBEDDINGS_API_KEY    — API key for openai/voyage providers
    SP_EMBEDDINGS_BASE_URL   — base URL override for OpenAI-compatible servers
                               (Ollama, LM Studio, vLLM, TEI)
    SP_EMBEDDINGS_DIM        — embedding dimension; 0 = provider default
    SP_EMBEDDINGS_SYNC_INTERVAL — seconds between background embedding
                               reconcile passes (0 disables the loop)
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field

from ._base import _GatewaySettingsBase


class EmbeddingsSettings(_GatewaySettingsBase):
    """Typed embedding configuration read from process environment at instantiation."""

    provider: str = Field("hash", alias="SP_EMBEDDINGS_PROVIDER")
    model: str = Field("", alias="SP_EMBEDDINGS_MODEL")
    api_key: str = Field("", alias="SP_EMBEDDINGS_API_KEY")
    base_url: str = Field("", alias="SP_EMBEDDINGS_BASE_URL")
    dim: int = Field(0, alias="SP_EMBEDDINGS_DIM")
    sync_interval: int = Field(300, alias="SP_EMBEDDINGS_SYNC_INTERVAL")

    @property
    def enabled(self) -> bool:
        return self.provider not in ("", "none")


@lru_cache(maxsize=1)
def get_embeddings_settings() -> EmbeddingsSettings:
    """Return cached EmbeddingsSettings instance."""
    return EmbeddingsSettings()
