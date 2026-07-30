"""Connection pool manager — reuses connector instances instead of recreating per query.

Fixes MED-06: Connection pool recreated per query causing resource leaks.
Now with SSH tunnel support for bastion-host connections and retry logic.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import random
import socket
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse, urlunparse

from ..common.credential_identity import CREDENTIAL_IDENTITY_KEY
from .base import BaseConnector
from .registry import get_connector
from .ssh_tunnel import SSHTunnel

logger = logging.getLogger(__name__)

# Pool keys are "{db_type}:{connection_string}" followed by scope segments. The
# separator is a control character so it can never collide with a DSN.
_KEY_SCOPE_SEP = "\x1f"

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


def _split_pool_key(key: str) -> tuple[str, list[str]]:
    """Split a pool key into its ``db_type:connection_string`` head and scope tail."""
    head, _, tail = key.partition(_KEY_SCOPE_SEP)
    return head, [seg for seg in tail.split(_KEY_SCOPE_SEP) if seg]


def _pool_key_scope(key: str) -> str:
    """Return the ``org=…`` segment of a pool key, or "" when unscoped."""
    for segment in _split_pool_key(key)[1]:
        if segment.startswith("org="):
            return segment[len("org=") :]
    return ""


def _make_pool_key(
    db_type: str,
    connection_string: str,
    org_id: str | None,
    credential_identity: str | None,
) -> str:
    """Build a pool key scoped by org and credential identity.

    Both scope segments are non-secret: org_id is a tenant identifier and
    credential_identity is a digest supplied by the store (see
    CREDENTIAL_IDENTITY_KEY). Without them, two tenants whose connection strings
    look identical but whose credential extras differ — service-account JSON, TLS
    key, SSH tunnel, token — would share one connector.
    """
    return _KEY_SCOPE_SEP.join(
        (
            f"{db_type}:{connection_string}",
            f"org={org_id or ''}",
            f"cred={credential_identity or ''}",
        )
    )


def _current_org_id() -> str | None:
    from ..governance.context import current_org_id_var

    return current_org_id_var.get()


# Extras fields that are identifiers rather than secrets, safe to fold into a
# pool key verbatim. Secret-bearing fields contribute their presence only.
_NON_SECRET_EXTRAS_FIELDS = (
    "account",
    "authenticator",
    "branch",
    "catalog",
    "dataset",
    "http_path",
    "location",
    "project",
    "region",
    "role",
    "schema_name",
    "snowflake_host",
    "snowflake_protocol",
    "username",
    "warehouse",
    "workspace",
    "xata_credential_ref",
    "xata_database",
    "xata_organization",
    "xata_project",
)
_NON_SECRET_SSH_FIELDS = ("host", "port", "username", "auth_method", "proxy_host", "proxy_port")
_NON_SECRET_SSL_FIELDS = ("enabled", "mode")
# Non-secret identifiers inside a GCP service-account blob.
_NON_SECRET_SA_FIELDS = ("client_email", "private_key_id", "project_id")


def _extras_shape_identity(credential_extras: dict) -> str:
    """Fallback identity for extras that did not come with a store marker.

    Built from field names and identifier values only — never from secret values,
    and never logged. Residual: extras whose sole distinguishing content is an
    opaque token (access_token, motherduck_token) are indistinguishable here, so
    for those the isolation rests on the org segment of the pool key.
    """
    parts: list[str] = []
    for key in sorted(credential_extras):
        parts.append(f"k:{key}")
        value = credential_extras[key]
        if key in _NON_SECRET_EXTRAS_FIELDS and isinstance(value, (str, int, bool)):
            parts.append(f"{key}={value}")
        elif key == "ssh_tunnel" and isinstance(value, dict):
            parts += [f"ssh.{f}={value.get(f)}" for f in _NON_SECRET_SSH_FIELDS]
            parts += [f"ssh.{f}?{bool(value.get(f))}" for f in ("password", "private_key")]
        elif key == "ssl_config" and isinstance(value, dict):
            parts += [f"ssl.{f}={value.get(f)}" for f in _NON_SECRET_SSL_FIELDS]
            parts += [f"ssl.{f}?{bool(value.get(f))}" for f in ("ca_cert", "client_cert", "client_key")]
        elif key == "credentials_json" and isinstance(value, str):
            try:
                blob = json.loads(value)
            except Exception:
                blob = {}
            parts += [f"sa.{f}={blob.get(f)}" for f in _NON_SECRET_SA_FIELDS]
    return "shape." + hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def _pop_credential_identity(credential_extras: dict | None) -> tuple[dict | None, str | None]:
    """Detach the store-supplied credential identity from the extras.

    Connectors must never see it, so it is removed from a copy before use. Callers
    that hand-build extras instead of taking them from the store get the shape
    identity below.
    """
    if not credential_extras:
        return credential_extras, None
    if CREDENTIAL_IDENTITY_KEY not in credential_extras:
        return credential_extras, _extras_shape_identity(credential_extras)
    remaining = {k: v for k, v in credential_extras.items() if k != CREDENTIAL_IDENTITY_KEY}
    return (remaining or None), credential_extras[CREDENTIAL_IDENTITY_KEY]


def _safe_pool_key_for_log(key: str) -> str:
    """Return a log-safe representation of a pool key.

    Pool keys have the format ``db_type:connection_string`` plus non-secret scope
    segments. If the connection string looks like a URL (contains ``://``), parse
    it and return only the host and port — never the credentials. Non-URL formats
    (bare project IDs, file paths) are kept as-is since they do not contain
    embedded passwords.
    """
    key, scope = _split_pool_key(key)
    suffix = (" " + " ".join(scope)) if scope else ""
    return _safe_pool_key_head_for_log(key) + suffix


def _safe_pool_key_head_for_log(key: str) -> str:
    colon_idx = key.find(":")
    if colon_idx == -1:
        return key
    db_type = key[:colon_idx]
    remainder = key[colon_idx + 1 :]
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
            normalized = "postgresql://" + normalized[len("redshift://") :]
        elif db_type == "clickhouse" and normalized.startswith("clickhouse://"):
            normalized = "http://" + normalized[len("clickhouse://") :]
        elif db_type == "mysql" and normalized.startswith("mysql+pymysql://"):
            normalized = "http://" + normalized[len("mysql+pymysql://") :]
        elif db_type == "trino" and normalized.startswith("trino+https://"):
            trino_https = True
            normalized = "http://" + normalized[len("trino+https://") :]

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
            result = "redshift://" + result[len("postgresql://") :]
        elif db_type == "clickhouse":
            result = "clickhouse://" + result[len("http://") :]
        elif db_type == "mysql" and connection_string.startswith("mysql+pymysql://"):
            result = "mysql+pymysql://" + result[len("http://") :]
        elif db_type == "trino" and trino_https:
            result = "trino+https://" + result[len("http://") :]

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
            normalized = "http://" + normalized[len("clickhouse://") :]
        elif db_type == "mysql" and normalized.startswith("mysql+pymysql://"):
            normalized = "http://" + normalized[len("mysql+pymysql://") :]
        elif db_type == "redshift" and normalized.startswith("redshift://"):
            normalized = "postgresql://" + normalized[len("redshift://") :]
        elif db_type == "trino" and normalized.startswith("trino+https://"):
            normalized = "http://" + normalized[len("trino+https://") :]

        parsed = urlparse(normalized)
        host = parsed.hostname or "localhost"
        port = parsed.port or default_port
        return host, port
    except Exception:
        return "localhost", default_port


def _validate_destination(db_type: str, connection_string: str) -> tuple[str, list[str]] | None:
    """Re-validate a TCP destination immediately before connecting.

    Gating mirrors network.validation.validate_connection_params: only TCP
    db_types, and only in cloud mode — loopback is unconditionally blocked by the
    resolver, so local deployments pointed at 127.0.0.1 warehouses would otherwise
    stop working. resolve_and_validate honours SP_ALLOW_PRIVATE_CONNECTIONS and
    raises ValueError on a blocked or unresolvable address.

    Returns (host, validated_ips) so the caller can pin the resolver, or None when
    validation does not apply.

    Not called for SSH-tunnelled connections: the warehouse endpoint is resolved on
    the bastion, not here, so a local lookup would fail closed on every legitimate
    tunnel.
    """
    from ..network.validation import TCP_DB_TYPES, resolve_and_validate
    from ..runtime.mode import is_cloud_mode

    if not connection_string or db_type not in TCP_DB_TYPES or not is_cloud_mode():
        return None

    host, port = _extract_host_port(connection_string, db_type)
    return host, resolve_and_validate(host, port, db_type)


async def _connect_validated(
    connector: BaseConnector,
    db_type: str,
    connection_string: str,
    actual_conn_str: str,
) -> None:
    """Connect with the destination validated and the resolver pinned across it.

    The validated IPs are deliberately not substituted into the connection string
    — connecting by IP breaks TLS hostname verification (sslmode=verify-full) and
    SNI-based routing. Pinning the resolver instead keeps the hostname in the DSN
    while denying the driver's own lookup any address we did not just validate.
    Drivers that resolve inside a C library (psycopg2/libpq, pymssql/FreeTDS) do
    not consult the pin; for those the post-connect peer check below is the only
    thing that narrows the window.
    """
    from ..network.validation import assert_address_allowed, pinned_resolution

    validated = _validate_destination(db_type, connection_string)
    if validated is None:
        await connector.connect(actual_conn_str)
        return

    host, ips = validated
    with pinned_resolution(host, ips):
        await connector.connect(actual_conn_str)

    peer = _connected_peer_ip(connector)
    if peer is None:
        return
    try:
        assert_address_allowed(peer)
    except ValueError:
        with contextlib.suppress(Exception):
            await connector.close()
        raise ValueError(f"Connection refused: {host} connected to a blocked internal address") from None


def _connected_peer_ip(connector: BaseConnector) -> str | None:
    """Best-effort: the address the driver's socket is actually connected to.

    Only drivers that expose a socket file descriptor (psycopg2) can be checked;
    everything else returns None. The fd is borrowed and detached again so the
    wrapper object can never close the driver's socket.
    """
    raw = getattr(connector, "_conn", None)
    fileno = getattr(raw, "fileno", None)
    if fileno is None:
        return None
    try:
        fd = fileno()
        sock = socket.socket(fileno=fd)
    except Exception:
        return None
    try:
        peer = sock.getpeername()
    except Exception:
        return None
    finally:
        sock.detach()
    return peer[0] if isinstance(peer, tuple) and peer else None


class PoolManager:
    """Manages a cache of connected connectors, keyed by (db_type, connection_string).

    Connectors are reused across requests and cleaned up after idle timeout.
    SSH tunnels are automatically managed alongside their connectors.
    """

    def __init__(self, idle_timeout_sec: int = 300):
        self._pools: dict[str, tuple[BaseConnector, float]] = {}
        self._identities: dict[str, str] = {}  # key -> credential identity the connector was built with
        self._tunnels: dict[str, SSHTunnel] = {}  # key -> active tunnel
        self._keepalive_intervals: dict[str, int] = {}  # key -> interval seconds
        self._last_keepalive: dict[str, float] = {}  # key -> last keepalive time
        self._idle_timeout = idle_timeout_sec
        self._lock = asyncio.Lock()
        self._keepalive_task: asyncio.Task | None = None

    # Error substrings that indicate non-transient failures (don't retry these)
    _NON_TRANSIENT_ERRORS = (
        "authentication failed",
        "auth",
        "password",
        "database not found",
        "does not exist",
        "invalid catalog",
        "permission denied",
        "access denied",
        "not installed",
        "no module",
        "import error",
        "invalid connection string",
        "invalid dsn",
        "certificate",
        "ssl",
        "tls",
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
            return (
                "timeout" in err_lower
                or "unreachable" in err_lower
                or "connection refused" in err_lower
                or "connection lost" in err_lower
            )
        return False

    async def acquire(
        self,
        db_type: str,
        connection_string: str,
        credential_extras: dict | None = None,
        max_retries: int = 3,
        org_id: str | None = None,
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
            org_id: Owning organization. Defaults to the current governance context.
        """
        credential_extras, credential_identity = _pop_credential_identity(credential_extras)
        if org_id is None:
            org_id = _current_org_id()
        key = _make_pool_key(db_type, connection_string, org_id, credential_identity)
        async with self._lock:
            if key in self._pools:
                connector, _ = self._pools[key]
                self._pools[key] = (connector, time.monotonic())
                # A pooled connector is only reusable if it was built with the same
                # credential identity: the reuse branch returns before
                # set_credential_extras() runs, so serving a connector built from
                # different extras would hand back another principal's session.
                identity_ok = self._identities.get(key) == (credential_identity or "")
                try:
                    tunnel_ok = True
                    if key in self._tunnels:
                        tunnel_ok = self._tunnels[key].check_tunnel()
                    if identity_ok and tunnel_ok and await connector.health_check():
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
                self._identities.pop(key, None)

            # Cloud mode: reject all local database connections (file-based and in-memory)
            # Only MotherDuck (md:) DuckDB is allowed in cloud mode
            from ..runtime.mode import is_cloud_mode

            if is_cloud_mode():
                if db_type == "sqlite":
                    raise RuntimeError("SQLite connections are not available in cloud mode")
                if db_type == "duckdb" and connection_string and not connection_string.startswith("md:"):
                    raise RuntimeError("Only MotherDuck (md:) DuckDB connections are available in cloud mode")

            # Use the registry to get the right connector — it respects
            # SP_SANDBOX_ENABLED and SP_DISABLE_SANDBOX for file-based DBs.
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
                self._identities[key] = credential_identity or ""
                return connector

            # SSH tunnel setup (for host:port-based databases)
            actual_conn_str = connection_string
            tunnelled = False
            if (
                credential_extras
                and credential_extras.get("ssh_tunnel")
                and credential_extras["ssh_tunnel"].get("enabled")
                and db_type in _TUNNEL_CAPABLE_DB_TYPES
            ):
                tunnelled = True
                ssh_config = credential_extras["ssh_tunnel"]
                remote_host, remote_port = _extract_host_port(connection_string, db_type)

                tunnel = SSHTunnel(ssh_config)
                local_host, local_port = tunnel.start(remote_host, remote_port)

                # Rewrite connection string to use tunnel's local port
                actual_conn_str = _rewrite_connection_string(connection_string, db_type, local_host, local_port)
                self._tunnels[key] = tunnel
                logger.info(
                    "SSH tunnel active for %s, connecting via %s:%d",
                    _safe_pool_key_for_log(key),
                    local_host,
                    local_port,
                )

            # Track keepalive interval if provided
            keepalive = credential_extras.get("keepalive_interval", 0) if credential_extras else 0

            # Connect with retry logic (exponential backoff + jitter)
            last_error: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    if tunnelled:
                        # The warehouse endpoint resolves on the bastion, not here;
                        # the bastion itself is validated inside SSHTunnel.start().
                        await connector.connect(actual_conn_str)
                    else:
                        # Re-resolve and re-check the destination on every attempt:
                        # the address validated when the connection was saved can be
                        # re-pointed at an internal address afterwards. Raises on a
                        # blocked or unresolvable target — no hostname fallback.
                        await _connect_validated(connector, db_type, connection_string, actual_conn_str)
                    now = time.monotonic()
                    self._pools[key] = (connector, now)
                    self._identities[key] = credential_identity or ""
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
                    backoff = (0.5 * (2**attempt)) + random.uniform(0, 0.5)
                    logger.warning(
                        "Transient connection error for %s (attempt %d/%d), retrying in %.1fs: %s",
                        db_type,
                        attempt + 1,
                        max_retries,
                        backoff,
                        e,
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
                            logger.warning(
                                "Keepalive ping failed for %s — removing from pool", _safe_pool_key_for_log(key)
                            )
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

    async def release(
        self,
        db_type: str,
        connection_string: str,
        credential_extras: dict | None = None,
        org_id: str | None = None,
    ) -> None:
        """Mark a connector as available (updates last-used time).

        Pass the same credential_extras used to acquire so the pool key matches.
        """
        _, credential_identity = _pop_credential_identity(credential_extras)
        if org_id is None:
            org_id = _current_org_id()
        key = _make_pool_key(db_type, connection_string, org_id, credential_identity)
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
        logged to the audit trail via BaseConnector.execute().

        Usage:
            async with pool_manager.connection("postgres", conn_str, connection_name="mydb") as connector:
                rows = await connector.execute(sql)
        """
        connector = await self.acquire(db_type, connection_string, credential_extras=credential_extras)
        if connection_name:
            connector._audit_connection_name = connection_name
        try:
            yield connector
        finally:
            connector._audit_connection_name = None
            await self.release(db_type, connection_string, credential_extras=credential_extras)

    async def cleanup_idle(self) -> int:
        """Close connectors that have been idle longer than timeout. Returns count closed."""
        now = time.monotonic()
        closed = 0
        async with self._lock:
            stale_keys = [k for k, (_, last_used) in self._pools.items() if now - last_used > self._idle_timeout]
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
                self._identities.pop(key, None)
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
            self._identities.clear()
            # Close all tunnels
            for tunnel in self._tunnels.values():
                tunnel.stop()
            self._tunnels.clear()
            self._keepalive_intervals.clear()
            self._last_keepalive.clear()

    async def close_pool(self, key_substring: str, org_id: str | None = None) -> int:
        """Close pools whose key contains the given substring.

        Used when connection credentials change and existing pools are stale.
        Pass the connection string or a unique identifier to match, plus the owning
        org so a shared connection string does not evict another tenant's pool.
        Returns number of pools closed.
        """
        closed = 0
        async with self._lock:
            stale_keys = [
                k
                for k in self._pools
                if key_substring in _split_pool_key(k)[0] and (org_id is None or _pool_key_scope(k) == org_id)
            ]
            for key in stale_keys:
                connector, _ = self._pools.pop(key)
                try:
                    await connector.close()
                except Exception:
                    pass
                if key in self._tunnels:
                    self._tunnels[key].stop()
                    del self._tunnels[key]
                self._identities.pop(key, None)
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
                # Redact, do not truncate — the password sits well inside the
                # first 80 characters of a URL-style pool key.
                "key": _safe_pool_key_for_log(key),
                "db_type": db_type,
                "idle_seconds": round(now - last_used, 1),
                "connector_type": type(connector).__name__,
            }
            if key in self._keepalive_intervals:
                pool_info["keepalive_interval"] = self._keepalive_intervals[key]
            pools.append(pool_info)
        tunnels = []
        for key, tunnel in self._tunnels.items():
            tunnels.append(
                {
                    "key": _safe_pool_key_for_log(key),
                    "active": tunnel.is_active if hasattr(tunnel, "is_active") else True,
                }
            )
        return {
            "pool_count": len(self._pools),
            "tunnel_count": len(self._tunnels),
            "max_idle_seconds": self._idle_timeout,
            "pools": pools,
            "tunnels": tunnels,
        }


# Global pool manager singleton
pool_manager = PoolManager()
