"""DbtProxyServer — single TCP listener that serves all dbt-proxy runs.

Design (R3):
  - Binds once at lifespan start on sp_dbt_proxy_host:sp_dbt_proxy_port.
  - All concurrent connections share the same listener; per-connection auth
    resolves the run-token to a RunTokenClaims, selecting the right connector
    and tenant.
  - No PortAllocator — one port for all runs.

Usage (in lifespan):
    async with DbtProxyServer.start(config, token_store=..., store_factory=...) as server:
        app.state.dbt_proxy_server = server
        yield
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from ..db.engine import get_session_factory
from ..store import Store
from .auth import handle_startup
from .config import DbtProxyConfig
from .errors import AuthFailed, RunTokenExpired
from .session import DbtProxySession
from .tokens import RunTokenStore

logger = logging.getLogger(__name__)


class DbtProxyServer:
    """Wraps an asyncio TCP server for the dbt-proxy listener."""

    def __init__(self, server: asyncio.Server, config: DbtProxyConfig) -> None:
        self._server = server
        self._config = config

    @property
    def host(self) -> str:
        return self._config.sp_dbt_proxy_host

    @property
    def port(self) -> int:
        return self._config.sp_dbt_proxy_port

    @staticmethod
    @asynccontextmanager
    async def start(
        config: DbtProxyConfig,
        *,
        token_store: RunTokenStore | None,
        store_factory=None,
    ) -> AsyncIterator[DbtProxyServer]:
        """Async context manager that starts the TCP listener.

        Args:
            config:        DbtProxyConfig instance.
            token_store:   RunTokenStore for token verification.
            store_factory: Optional callable returning an async session factory.
                           Defaults to gateway.db.engine.get_session_factory().
                           Used to build a per-connection Store.
        """
        if not config.sp_dbt_proxy_enabled:
            logger.info("dbt_proxy disabled (sp_dbt_proxy_enabled=false) — skipping listener")
            yield _DisabledProxyServer(config)  # type: ignore[misc]
            return

        if not config.sp_gateway_run_token_secret:
            logger.error(
                "dbt_proxy STARTUP ABORTED: SP_GATEWAY_RUN_TOKEN_SECRET is not set. "
                "The TCP listener will NOT bind. Set the secret to enable the proxy."
            )
            yield _DisabledProxyServer(config)  # type: ignore[misc]
            return

        # token_store is guaranteed non-None here: the missing-secret branch
        # returned early above. The assert narrows the type for pyright.
        assert token_store is not None, "token_store must be set when secret is configured"

        if store_factory is None:
            store_factory = get_session_factory

        async def _handle_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            peer = writer.get_extra_info("peername")
            logger.debug("dbt_proxy new connection from %s", peer)
            try:
                claims = await handle_startup(reader, writer, token_store)
            except (AuthFailed, RunTokenExpired) as exc:
                logger.warning("dbt_proxy auth failed from %s: %s", peer, exc)
                return

            session_factory = store_factory()
            try:
                async with session_factory() as db_session:
                    store = Store(db_session, org_id=claims.org_id, user_id=claims.user_id)
                    session = DbtProxySession(reader, writer, claims, store)
                    await session.run()
            except Exception as exc:
                logger.error("dbt_proxy session error run_id=%s: %s", claims.run_id, exc)

        server = await asyncio.start_server(
            _handle_connection,
            config.sp_dbt_proxy_host,
            config.sp_dbt_proxy_port,
        )
        proxy = DbtProxyServer(server, config)
        logger.info(
            "dbt_proxy listening on %s:%s",
            config.sp_dbt_proxy_host,
            config.sp_dbt_proxy_port,
        )
        try:
            async with server:
                yield proxy
        finally:
            logger.info("dbt_proxy listener stopped")


class _DisabledProxyServer:
    """Placeholder returned when sp_dbt_proxy_enabled=false."""

    def __init__(self, config: DbtProxyConfig) -> None:
        self._config = config

    @property
    def port(self) -> int:
        return self._config.sp_dbt_proxy_port


__all__ = ["DbtProxyServer"]
