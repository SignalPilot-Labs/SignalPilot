"""Connection pool manager — reuses connector instances instead of recreating per query.

Fixes MED-06: Connection pool recreated per query causing resource leaks.
Now with SSH tunnel support for bastion-host connections.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse, urlunparse

from .base import BaseConnector
from .registry import get_connector
from .ssh_tunnel import SSHTunnel

logger = logging.getLogger(__name__)

# DB types that use host:port connections and can benefit from SSH tunnels
_TUNNEL_CAPABLE_DB_TYPES = {"postgres", "mysql", "redshift", "clickhouse", "mssql"}

# Default ports per DB type (for connection string rewriting)
_DEFAULT_PORTS: dict[str, int] = {
    "postgres": 5432,
    "mysql": 3306,
    "redshift": 5439,
    "clickhouse": 9000,
    "mssql": 1433,
}

# URI scheme prefixes per DB type
_URI_SCHEMES: dict[str, list[str]] = {
    "postgres": ["postgresql://", "postgres://"],
    "mysql": ["mysql://", "mysql+pymysql://"],
    "redshift": ["redshift://", "postgresql://"],
    "clickhouse": ["clickhouse://"],
    "mssql": ["mssql://", "mssql+pymssql://", "sqlserver://"],
}


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
        if db_type == "redshift" and normalized.startswith("redshift://"):
            normalized = "postgresql://" + normalized[len("redshift://"):]
        elif db_type == "clickhouse" and normalized.startswith("clickhouse://"):
            normalized = "http://" + normalized[len("clickhouse://"):]
        elif db_type == "mysql" and normalized.startswith("mysql+pymysql://"):
            normalized = "http://" + normalized[len("mysql+pymysql://"):]

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

        return result
    except Exception as e:
        logger.warning("Failed to rewrite connection string for SSH tunnel: %s", e)
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
        self._idle_timeout = idle_timeout_sec
        self._lock = asyncio.Lock()

    async def acquire(
        self,
        db_type: str,
        connection_string: str,
        credential_extras: dict | None = None,
    ) -> BaseConnector:
        """Get or create a connected connector for the given connection.

        Args:
            db_type: Database type string (e.g., "postgres", "bigquery").
            connection_string: Connection string for the database.
            credential_extras: Optional structured credential data (service account JSON,
                SSH tunnel config, etc.) for connectors that need more than a connection string.
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
                logger.info("SSH tunnel active for %s, connecting via %s:%d", key, local_host, local_port)

            await connector.connect(actual_conn_str)
            self._pools[key] = (connector, time.monotonic())
            return connector

    async def release(self, db_type: str, connection_string: str) -> None:
        """Mark a connector as available (updates last-used time)."""
        key = f"{db_type}:{connection_string}"
        async with self._lock:
            if key in self._pools:
                connector, _ = self._pools[key]
                self._pools[key] = (connector, time.monotonic())

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
                closed += 1
        return closed

    async def close_all(self) -> None:
        """Close all managed connectors and tunnels."""
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
            pools.append({
                "key": key[:80],  # Truncate for security
                "db_type": db_type,
                "idle_seconds": round(now - last_used, 1),
                "connector_type": type(connector).__name__,
            })
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
