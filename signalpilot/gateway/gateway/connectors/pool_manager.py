"""Connection pool manager — reuses connector instances instead of recreating per query.

Fixes MED-06: Connection pool recreated per query causing resource leaks.
Now with SSH tunnel support for bastion-host connections and retry logic.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from typing import Any, AsyncIterator
from urllib.parse import urlparse, urlunparse

from .base import BaseConnector
from .registry import get_connector
from .ssh_tunnel import SSHTunnel

logger = logging.getLogger(__name__)

# DB types that use host:port connections and can benefit from SSH tunnels
_TUNNEL_CAPABLE_DB_TYPES = {"postgres", "mysql", "redshift", "clickhouse", "mssql", "trino"}

# Default ports per DB type (for connection string rewriting)
_DEFAULT_PORTS: dict[str, int] = {
    "postgres": 5432,
    "mysql": 3306,
    "redshift": 5439,
    "clickhouse": 9000,
    "mssql": 1433,
    "trino": 8080,
}

# URI scheme prefixes per DB type
_URI_SCHEMES: dict[str, list[str]] = {
    "postgres": ["postgresql://", "postgres://"],
    "mysql": ["mysql://", "mysql+pymysql://"],
    "redshift": ["redshift://", "postgresql://"],
    "clickhouse": ["clickhouse://"],
    "mssql": ["mssql://", "mssql+pymssql://", "sqlserver://"],
    "trino": ["trino://", "trino+https://"],
}


def _safe_pool_key_for_log(key: str) -> str:
    """Return a log-safe representation of a pool key.

    Pool keys have the format ``db_type:connection_string``. If the connection
    string looks like a URL (contains ``://``), parse it and return only the
    host and port — never the credentials. Non-URL formats (bare project IDs,
    file paths) are returned as-is since they do not contain embedded passwords.
    """
    colon_idx = key.find(":")
    if colon_idx == -1:
        return key
    db_type = key[:colon_idx]
    remainder = key[colon_idx + 1:]
    if "://" not in remainder:
        # Non-URL format (BigQuery project ID, DuckDB/SQLite path) — safe to log.
        return key
    try:
        parsed = urlparse(remainder)
        host = parsed.hostname or ""
        port = parsed.port
        if port:
            return f"{db_type}:{host}:{port}"
        return f"{db_type}:{host}"
    except Exception:
        return f"{db_type}:<redacted>"


def _rewrite_connection_string(
    connection_string: str,
    db_type: str,
    local_host: str,
    local_port: int,
) -> str:
    """Rewrite a connection string to point at the SSH tunnel's local port."""
    try:
        # Normalize scheme for urlparse
        normalized = connection_string
        trino_https = False
        if db_type == "redshift" and normalized.startswith("redshift://"):
            normalized = "postgresql://" + normalized[len("redshift://"):]
        elif db_type == "clickhouse" and normalized.startswith("clickhouse://"):
            normalized = "http://" + normalized[len("clickhouse://"):]
        elif db_type == "mysql" and normalized.startswith("mysql+pymysql://"):
            normalized = "http://" + normalized[len("mysql+pymysql://"):]
        elif db_type == "trino" and normalized.startswith("trino+https://"):
            trino_https = True
            normalized = "http://" + normalized[len("trino+https://"):]

        parsed = urlparse(normalized)
        # Replace host and port
        new_netloc = parsed.netloc
        if parsed.hostname:
            old_host_port = parsed.hostname
            if parsed.port:
                old_host_port += f":{parsed.port}"
            new_host_port = f"{local_host}:{local_port}"
            # Preserve username:password@ prefix
            if "@" in new_netloc:
                user_pass = new_netloc.split("@")[0]
                new_netloc = f"{user_pass}@{new_host_port}"
            else:
                new_netloc = new_host_port

        new_parsed = parsed._replace(netloc=new_netloc)
        result = urlunparse(new_parsed)

        # Restore original scheme
        if db_type == "redshift" and connection_string.startswith("redshift://"):
            result = "redshift://" + result[len("postgresql://"):]
        elif db_type == "clickhouse":
            result = "clickhouse://" + result[len("http://"):]
        elif db_type == "mysql" and connection_string.startswith("mysql+pymysql://"):
            result = "mysql+pymysql://" + result[len("http://"):]
        elif db_type == "trino" and trino_https:
            result = "trino+https://" + result[len("http://"):]

        return result
    except Exception as e:
        logger.warning("Failed to rewrite connection string for SSH tunnel: %s", type(e).__name__)
        return connection_string


def _extract_host_port(connection_string: str, db_type: str) -> tuple[str, int]:
    """Extract (host, port) from a connection string."""
    default_port = _DEFAULT_PORTS.get(db_type, 5432)
    try:
        normalized = connection_string
        if db_type == "clickhouse" and normalized.startswith("clickhouse://"):
            normalized = "http://" + normalized[len("clickhouse://"):]
        elif db_type == "mysql" and normalized.startswith("mysql+pymysql://"):
            normalized = "http://" + normalized[len("mysql+pymysql://"):]
        elif db_type == "redshift" and normalized.startswith("redshift://"):
            normalized = "postgresql://" + normalized[len("redshift://"):]
        elif db_type == "trino" and normalized.startswith("trino+https://"):
            normalized = "http://" + normalized[len("trino+https://"):]

        parsed = urlparse(normalized)
        host = parsed.hostname or "localhost"
        port = parsed.port or default_port
        return host, port
    except Exception:
        return "localhost", default_port


class PoolManager:
    """Manages a cache of connected connectors, keyed by (db_type, connection_string).

    Connectors are reused across requests and cleaned up after idle timeout.
    SSH tunnels are automatically managed alongside their connectors.
    """

    def __init__(self, idle_timeout_sec: int = 300):
        self._pools: dict[str, tuple[BaseConnector, float]] = {}
        self._tunnels: dict[str, SSHTunnel] = {}  # key -> active tunnel
        self._keepalive_intervals: dict[str, int] = {}  # key -> interval seconds
        self._last_keepalive: dict[str, float] = {}  # key -> last keepalive time
        self._idle_timeout = idle_timeout_sec
        self._lock = asyncio.Lock()
        self._keepalive_task: asyncio.Task | None = None

    # Error substrings that indicate non-transient failures (don't retry these)
    _NON_TRANSIENT_ERRORS = (
        "authentication failed", "auth", "password",
        "database not found", "does not exist",
        "invalid catalog", "permission denied", "access denied",
        "not installed", "no module", "import error",
        "invalid connection string", "invalid dsn",
        "certificate", "ssl", "tls",
    )

    @staticmethod
    def _is_transient(error: Exception) -> bool:
        """Determine if an error is transient and worth retrying."""
        err_lower = str(error).lower()
        for keyword in PoolManager._NON_TRANSIENT_ERRORS:
            if keyword in err_lower:
                return False
        # OSError, TimeoutError, ConnectionError are always transient
        if isinstance(error, (OSError, asyncio.TimeoutError, ConnectionError, ConnectionRefusedError)):
            return True
        # RuntimeError wrapping transient causes
        if isinstance(error, RuntimeError):
            return "timeout" in err_lower or "unreachable" in err_lower or "connection refused" in err_lower or "connection lost" in err_lower
        return False

    async def acquire(
        self,
        db_type: str,
        connection_string: str,
        credential_extras: dict | None = None,
        max_retries: int = 3,
    ) -> BaseConnector:
        """Get or create a connected connector for the given connection.

        Retries transient failures (network timeouts, connection refused) with
        exponential backoff + jitter. Auth/config errors fail immediately.

        Args:
            db_type: Database type string (e.g., "postgres", "bigquery").
            connection_string: Connection string for the database.
            credential_extras: Optional structured credential data (service account JSON,
                SSH tunnel config, etc.) for connectors that need more than a connection string.
            max_retries: Maximum retry attempts for transient failures (default 3).
        """
        key = f"{db_type}:{connection_string}"
        async with self._lock:
            if key in self._pools:
                connector, _ = self._pools[key]
                self._pools[key] = (connector, time.monotonic())
                # Verify it's still healthy (and tunnel is still active)
                try:
                    tunnel_ok = True
                    if key in self._tunnels:
                        tunnel_ok = self._tunnels[key].check_tunnel()
                    if tunnel_ok and await connector.health_check():
                        return connector
                except Exception:
                    pass
                # Stale — close and recreate
                try:
                    await connector.close()
                except Exception:
                    pass
                if key in self._tunnels:
                    self._tunnels[key].stop()
                    del self._tunnels[key]
                del self._pools[key]

            # Cloud mode: reject all local database connections (file-based and in-memory)
            # Only MotherDuck (md:) DuckDB is allowed in cloud mode
            from ..deployment import is_cloud_mode
            if is_cloud_mode():
                if db_type == "sqlite":
                    raise RuntimeError("SQLite connections are not available in cloud mode")
                if db_type == "duckdb" and connection_string and not connection_string.startswith("md:"):
                    raise RuntimeError("Only MotherDuck (md:) DuckDB connections are available in cloud mode")

            # Use sandboxed connectors for local file-based databases (DuckDB, SQLite)
            # that live on the host filesystem and can't be opened directly from Docker.
            if db_type == "duckdb" and connection_string and not connection_string.startswith("md:") and connection_string != ":memory:":
                from .sandboxed_duckdb import SandboxedDuckDBConnector
                connector = SandboxedDuckDBConnector()
            elif db_type == "sqlite" and connection_string and connection_string != ":memory:":
                from .sandboxed_sqlite import SandboxedSQLiteConnector
                connector = SandboxedSQLiteConnector()
            else:
                connector = get_connector(db_type)

            # Pass credential extras to connector via standardized interface.
            # Each connector's set_credential_extras() extracts what it needs
            # (SSL certs, service account JSON, structured auth params, etc.)
            if credential_extras:
                connector.set_credential_extras(credential_extras)

            # BigQuery short-circuit: set_credential_extras already configures
            # the client with credentials, so we can skip connect()
            if db_type == "bigquery" and credential_extras and credential_extras.get("credentials_json"):
                self._pools[key] = (connector, time.monotonic())
                return connector

            # SSH tunnel setup (for host:port-based databases)
            actual_conn_str = connection_string
            if (
                credential_extras
                and credential_extras.get("ssh_tunnel")
                and credential_extras["ssh_tunnel"].get("enabled")
                and db_type in _TUNNEL_CAPABLE_DB_TYPES
            ):
                ssh_config = credential_extras["ssh_tunnel"]
                remote_host, remote_port = _extract_host_port(connection_string, db_type)

                tunnel = SSHTunnel(ssh_config)
                local_host, local_port = tunnel.start(remote_host, remote_port)

                # Rewrite connection string to use tunnel's local port
                actual_conn_str = _rewrite_connection_string(
                    connection_string, db_type, local_host, local_port
                )
                self._tunnels[key] = tunnel
                logger.info("SSH tunnel active for %s, connecting via %s:%d", _safe_pool_key_for_log(key), local_host, local_port)

            # Track keepalive interval if provided
            keepalive = (
                credential_extras.get("keepalive_interval", 0)
                if credential_extras else 0
            )

            # Connect with retry logic (exponential backoff + jitter)
            last_error: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    await connector.connect(actual_conn_str)
                    now = time.monotonic()
                    self._pools[key] = (connector, now)
                    if keepalive and keepalive > 0:
                        self._keepalive_intervals[key] = keepalive
                        self._last_keepalive[key] = now
                        self._ensure_keepalive_running()
                    if attempt > 0:
                        logger.info("Connection succeeded on attempt %d for %s", attempt + 1, db_type)
                    return connector
                except Exception as e:
                    last_error = e
                    if attempt >= max_retries or not self._is_transient(e):
                        # Non-transient or exhausted retries — fail now
                        if key in self._tunnels:
                            self._tunnels[key].stop()
                            del self._tunnels[key]
                        raise
                    # Exponential backoff: 0.5s, 1s, 2s + jitter
                    backoff = (0.5 * (2 ** attempt)) + random.uniform(0, 0.5)
                    logger.warning(
                        "Transient connection error for %s (attempt %d/%d), retrying in %.1fs: %s",
                        db_type, attempt + 1, max_retries, backoff, e,
                    )
                    await asyncio.sleep(backoff)
                    # Re-create connector for fresh state
                    connector = get_connector(db_type)
                    if credential_extras:
                        connector.set_credential_extras(credential_extras)

            # Should never reach here, but safety net
            raise last_error or RuntimeError("Connection failed after retries")

    def _ensure_keepalive_running(self) -> None:
        """Start the keepalive background task if not already running."""
        if self._keepalive_task is None or self._keepalive_task.done():
            self._keepalive_task = asyncio.ensure_future(self._keepalive_loop())

    async def _keepalive_loop(self) -> None:
        """Periodically ping connections that have a keepalive interval configured."""
        while True:
            await asyncio.sleep(30)  # Check every 30 seconds
            if not self._keepalive_intervals:
                break  # No more keepalive connections, stop the loop
            now = time.monotonic()
            async with self._lock:
                for key in list(self._keepalive_intervals):
                    if key not in self._pools:
                        # Connection was removed
                        self._keepalive_intervals.pop(key, None)
                        self._last_keepalive.pop(key, None)
                        continue
                    interval = self._keepalive_intervals[key]
                    last = self._last_keepalive.get(key, 0)
                    if now - last < interval:
                        continue
                    connector, last_used = self._pools[key]
                    try:
                        healthy = await connector.health_check()
                        if healthy:
                            self._last_keepalive[key] = now
                            logger.debug("Keepalive ping OK for %s", _safe_pool_key_for_log(key))
                        else:
                            logger.warning("Keepalive ping failed for %s — removing from pool", _safe_pool_key_for_log(key))
                            try:
                                await connector.close()
                            except Exception:
                                pass
                            del self._pools[key]
                            self._keepalive_intervals.pop(key, None)
                            self._last_keepalive.pop(key, None)
                            if key in self._tunnels:
                                self._tunnels[key].stop()
                                del self._tunnels[key]
                    except Exception as e:
                        logger.warning("Keepalive error for %s: %s", _safe_pool_key_for_log(key), e)
                        self._last_keepalive[key] = now  # Don't spam retries

    async def release(self, db_type: str, connection_string: str) -> None:
        """Mark a connector as available (updates last-used time)."""
        key = f"{db_type}:{connection_string}"
        async with self._lock:
            if key in self._pools:
                connector, _ = self._pools[key]
                self._pools[key] = (connector, time.monotonic())

    @contextlib.asynccontextmanager
    async def connection(
        self,
        db_type: str,
        connection_string: str,
        credential_extras: dict | None = None,
        connection_name: str | None = None,
    ) -> AsyncIterator[BaseConnector]:
        """Context manager that acquires a connector and guarantees release.

        All SQL executed through the yielded connector is automatically
        logged to the audit trail via AuditedConnector.

        Usage:
            async with pool_manager.connection("postgres", conn_str, connection_name="mydb") as connector:
                rows = await connector.execute(sql)
        """
        from .audited import AuditedConnector
        connector = await self.acquire(db_type, connection_string, credential_extras=credential_extras)
        audited = AuditedConnector(connector, connection_name=connection_name)
        try:
            yield audited  # type: ignore[misc]
        finally:
            audited.restore()
            await self.release(db_type, connection_string)

    async def cleanup_idle(self) -> int:
        """Close connectors that have been idle longer than timeout. Returns count closed."""
        now = time.monotonic()
        closed = 0
        async with self._lock:
            stale_keys = [
                k for k, (_, last_used) in self._pools.items()
                if now - last_used > self._idle_timeout
            ]
            for key in stale_keys:
                connector, _ = self._pools.pop(key)
                try:
                    await connector.close()
                except Exception:
                    pass
                # Close associated tunnel
                if key in self._tunnels:
                    self._tunnels[key].stop()
                    del self._tunnels[key]
                # Clean up keepalive tracking
                self._keepalive_intervals.pop(key, None)
                self._last_keepalive.pop(key, None)
                closed += 1
        return closed

    async def close_all(self) -> None:
        """Close all managed connectors, tunnels, and the keepalive task."""
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
            self._keepalive_task = None
        async with self._lock:
            for connector, _ in self._pools.values():
                try:
                    await connector.close()
                except Exception:
                    pass
            self._pools.clear()
            # Close all tunnels
            for tunnel in self._tunnels.values():
                tunnel.stop()
            self._tunnels.clear()
            self._keepalive_intervals.clear()
            self._last_keepalive.clear()

    async def close_pool(self, key_substring: str) -> int:
        """Close pools whose key contains the given substring.

        Used when connection credentials change and existing pools are stale.
        Pass the connection string or a unique identifier to match.
        Returns number of pools closed.
        """
        closed = 0
        async with self._lock:
            stale_keys = [k for k in self._pools if key_substring in k]
            for key in stale_keys:
                connector, _ = self._pools.pop(key)
                try:
                    await connector.close()
                except Exception:
                    pass
                if key in self._tunnels:
                    self._tunnels[key].stop()
                    del self._tunnels[key]
                self._keepalive_intervals.pop(key, None)
                self._last_keepalive.pop(key, None)
                closed += 1
        return closed

    @property
    def pool_count(self) -> int:
        return len(self._pools)

    @property
    def tunnel_count(self) -> int:
        return len(self._tunnels)

    def stats(self) -> dict[str, Any]:
        """Return pool manager statistics for monitoring."""
        now = time.time()
        pools = []
        for key, (connector, last_used) in self._pools.items():
            # Extract db_type from key
            parts = key.split(":", 1)
            db_type = parts[0] if parts else "unknown"
            pool_info: dict[str, Any] = {
                "key": key[:80],  # Truncate for security
                "db_type": db_type,
                "idle_seconds": round(now - last_used, 1),
                "connector_type": type(connector).__name__,
            }
            if key in self._keepalive_intervals:
                pool_info["keepalive_interval"] = self._keepalive_intervals[key]
            pools.append(pool_info)
        tunnels = []
        for key, tunnel in self._tunnels.items():
            tunnels.append({
                "key": key[:80],
                "active": tunnel.is_active if hasattr(tunnel, "is_active") else True,
            })
        return {
            "pool_count": len(self._pools),
            "tunnel_count": len(self._tunnels),
            "max_idle_seconds": self._idle_timeout,
            "pools": pools,
            "tunnels": tunnels,
        }


# Global pool manager singleton
pool_manager = PoolManager()
