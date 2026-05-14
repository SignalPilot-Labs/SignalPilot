"""dbt-proxy sub-package for the SignalPilot gateway.

Provides a single-port Postgres-wire listener that authenticates sandboxed dbt
runs via short-lived HMAC run-tokens and forwards governed SQL to real Postgres
connectors.

Public API:
  DbtProxyServer   — async context manager wrapping asyncio.start_server.
  RunTokenStore    — in-memory token mint/verify/revoke.
  RunTokenClaims   — frozen dataclass with masked __repr__.
  router           — FastAPI router for /api/dbt-proxy/run-tokens.
"""

from __future__ import annotations

from .api import router
from .server import DbtProxyServer
from .tokens import RunTokenClaims, RunTokenStore

__all__ = ["DbtProxyServer", "RunTokenStore", "RunTokenClaims", "router"]
