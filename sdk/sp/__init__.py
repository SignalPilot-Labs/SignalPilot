"""SignalPilot SDK — governed data access for notebooks and scripts.

Usage::

    import sp

    sp.init()                          # local (no auth)
    sp.init(api_key="sp_...")          # cloud

    db = sp.connect("default")
    rows = db.query("SELECT * FROM users LIMIT 10")
"""

from __future__ import annotations

import os

from sp._client import GatewayClient, _is_local_url
from sp._connection import Connection

_gw: GatewayClient | None = None


def init(
    gateway_url: str | None = None,
    api_key: str | None = None,
    session_token: str | None = None,
) -> None:
    """Initialize the SDK.

    Local:    sp.init()
    Cloud:    sp.init(api_key="sp_...")
    Sandbox:  sp.init(gateway_url=..., session_token=...)   # internal
    """
    global _gw
    url = gateway_url or os.environ.get("SP_GATEWAY_URL") or "http://localhost:3300"
    token = session_token or api_key or os.environ.get("SP_API_KEY")
    if not _is_local_url(url) and not token:
        raise ValueError(
            "API key required for remote gateway. "
            "Pass api_key= or set SP_API_KEY env var."
        )
    _gw = GatewayClient(url, token)


def connections() -> list[str]:
    """List available connection names."""
    _require_init()
    assert _gw is not None
    data = _gw.get("/api/connections")
    if isinstance(data, list):
        return [c["name"] if isinstance(c, dict) else c for c in data]
    return []


def connect(connection_name: str) -> Connection:
    """Get a Connection object for a named database connection."""
    _require_init()
    assert _gw is not None
    return Connection(connection_name, _gw)


def _require_init() -> None:
    if _gw is None:
        raise RuntimeError(
            "sp not initialized. Call sp.init() first.\n"
            "  Local:  sp.init()\n"
            "  Cloud:  sp.init(api_key='sp_...')"
        )
