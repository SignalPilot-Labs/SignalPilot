"""Canonical Chats URL for MCP callers."""

import os
from urllib.parse import urlsplit


def chat_url(thread_id: str) -> str:
    base = (os.getenv("SP_WEB_URL") or os.getenv("SIGNALPILOT_WEB_URL") or "https://app.signalpilot.ai").rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.query
        or parsed.fragment
    ):
        base = "https://app.signalpilot.ai"
    return f"{base}/chats/{thread_id}"
