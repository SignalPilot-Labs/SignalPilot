"""Adapter for OpenAI Codex API as a fallback provider.

Only activated when codex_fallback_enabled = true in key_rotation_config.
Provides degraded-mode text completion when all Claude keys are rate-limited.
"""

import httpx
from dataclasses import dataclass


@dataclass
class CodexResponse:
    """Response from the Codex API."""
    content: str
    usage: dict
    model: str


class CodexClient:
    """Thin wrapper around OpenAI's API for Codex completions.

    This is NOT a drop-in replacement for Claude Code. Codex can only do
    text completion — no tool use (Read, Write, Bash, etc.). Use for:
    - Continuing analysis/planning while waiting for Claude keys to reset
    - Generating code snippets
    - Keeping the run "alive" rather than fully pausing
    """

    def __init__(self, api_key: str, model: str = "codex-mini-latest"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://api.openai.com/v1"

    def __repr__(self) -> str:
        masked = self.api_key[:4] + "***" if len(self.api_key) > 4 else "***"
        return f"CodexClient(model={self.model!r}, api_key={masked!r})"

    async def complete(self, prompt: str, max_tokens: int = 4096) -> CodexResponse:
        """Send a completion request to Codex."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/responses",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "input": prompt,
                    "max_output_tokens": max_tokens,
                },
                timeout=120.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return CodexResponse(
                content=data["output"][0]["content"][0]["text"],
                usage=data.get("usage", {}),
                model=data.get("model", self.model),
            )
