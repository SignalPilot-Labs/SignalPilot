from __future__ import annotations

import os
from typing import Optional

from signalpilot._gateway.client import GatewayClient

_client: Optional[GatewayClient] = None


def get_gateway_client() -> Optional[GatewayClient]:
    """Returns the gateway client, initialized from env vars.

    Reads SP_GATEWAY_URL (default: http://localhost:3300) and SP_API_KEY.
    Returns None if SP_API_KEY is not set (gateway integration disabled).
    """
    global _client
    if _client is not None:
        return _client

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    jwt = os.environ.get("SP_SESSION_JWT", "")
    api_key = os.environ.get("SP_API_KEY", "")
    if not api_key and not jwt:
        return None

    base_url = os.environ.get("SP_GATEWAY_URL", "http://localhost:3300")
    _client = GatewayClient(base_url=base_url, api_key=api_key, session_jwt=jwt)
    return _client


def reset_gateway_client() -> None:
    """Reset the cached client (useful for testing or reconfiguration)."""
    global _client
    _client = None
