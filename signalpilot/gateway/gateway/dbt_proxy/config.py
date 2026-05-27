"""DbtProxyConfig — settings for the single-port TCP listener.

Environment variables:
  SP_DBT_PROXY_HOST          Bind host (default: 127.0.0.1).
                             WARNING: The pg-wire handshake is cleartext. This listener
                             must only be exposed on loopback or a trusted container-
                             internal interface. Setting 0.0.0.0 without TLS (deferred
                             to R8) allows on-network passive capture of run-tokens.
  SP_DBT_PROXY_PORT          Bind port (default: 15432). Single port; no per-run allocation.
  SP_GATEWAY_RUN_TOKEN_SECRET  REQUIRED. HMAC-SHA256 secret for run-token signing.
                              When unset, the TCP listener is NOT started and the mint
                              route returns 503 proxy_disabled. Secret must be non-empty.
  SP_DBT_PROXY_ENABLED       When false, DbtProxyServer.start is a no-op and the
                              mint route returns 503 proxy_disabled (default: true).
"""

from __future__ import annotations

import logging

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


class DbtProxyConfig(BaseSettings):
    """Settings read from environment variables at startup."""

    # Default loopback: cleartext pg-wire handshake is only safe on loopback.
    # Set SP_DBT_PROXY_HOST=0.0.0.0 only when TLS is enabled (R8).
    sp_dbt_proxy_host: str = "127.0.0.1"
    sp_dbt_proxy_port: int = 15432
    sp_gateway_run_token_secret: str = ""
    sp_dbt_proxy_enabled: bool = True

    model_config = {"env_file": ".env", "extra": "ignore"}

    def warn_if_non_loopback(self) -> None:
        """Emit a startup WARNING when bound to a non-loopback address without TLS."""
        if self.sp_dbt_proxy_host not in _LOOPBACK_HOSTS:
            logger.warning(
                "SECURITY: dbt-proxy bound to %s (non-loopback) with cleartext password "
                "handshake. TLS is deferred to R8. Ensure this interface is not "
                "reachable from untrusted networks.",
                self.sp_dbt_proxy_host,
            )


__all__ = ["DbtProxyConfig"]
