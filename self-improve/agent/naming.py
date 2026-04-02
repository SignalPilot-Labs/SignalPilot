"""Run auto-naming — generates short descriptive names via Anthropic Haiku."""

import os

import httpx

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
NAMING_MODEL = "claude-haiku-4-5-20251001"


async def generate_run_name(context: str) -> str | None:
    """Call Haiku to generate a short run name from the prompt or first-round context.

    Returns a 3-6 word name like "Fix auth token refresh" or "Refactor SQL engine tests".
    Returns None on failure (caller should fall back to branch name).
    """
    if not ANTHROPIC_API_KEY:
        return None

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": NAMING_MODEL,
                "max_tokens": 30,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Generate a short name (3-6 words, max 40 chars) that describes "
                            "what this coding agent run is doing. Return ONLY the name, no "
                            "quotes, no punctuation at the end. Use title case.\n\n"
                            f"Context:\n{context[:1500]}"
                        ),
                    }
                ],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["content"][0]["text"].strip().strip('"').strip("'")
        # Enforce length limit
        if len(text) > 50:
            text = text[:50].rsplit(" ", 1)[0]
        return text or None
