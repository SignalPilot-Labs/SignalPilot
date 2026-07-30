"""SSRF host validation for TCP-based database connections.

Validates that connection hostnames do not resolve to internal/private network
addresses. Prevents Server-Side Request Forgery (SSRF) attacks where a user
supplies a hostname like metadata.internal or a crafted DNS name that resolves
to an AWS metadata address (169.254.169.254) or other internal endpoints.

DNS resolution failure is treated as rejection (fail closed).
"""

from __future__ import annotations

import contextlib
import ipaddress
import logging
import os
import re
import socket
import threading
from collections.abc import Iterator, Sequence
from typing import Any, cast
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Networks always blocked for SSRF protection, regardless of SP_ALLOW_PRIVATE_CONNECTIONS.
# These ranges have no stdlib property (unlike loopback/link-local/private), so explicit
# network-range checks are required.
ALWAYS_BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT / Shared Address Space (RFC 6598)
    ipaddress.ip_network("192.88.99.0/24"),  # Deprecated 6to4 relay anycast (RFC 7526)
)

# TCP-based db_types that require SSRF validation.
# Cloud services (snowflake, bigquery, databricks) use HTTPS to external
# cloud endpoints. Embedded databases (duckdb, sqlite) use file paths.
TCP_DB_TYPES: frozenset[str] = frozenset(
    {
        "postgres",
        "mysql",
        "mssql",
        "redshift",
        "clickhouse",
        "trino",
    }
)

# DNS resolution timeout in seconds.
DNS_TIMEOUT_SECONDS: int = 5

_ALLOW_PRIVATE_ENV_VAR: str = "SP_ALLOW_PRIVATE_CONNECTIONS"

# Lock to protect the process-wide socket.setdefaulttimeout during DNS resolution.
_dns_timeout_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Cloud warehouse parameter format validators (Issue #25)
# ---------------------------------------------------------------------------
# Snowflake accounts: alphanumeric, dots (org-account format), hyphens, underscores.
_SNOWFLAKE_ACCOUNT_RE = re.compile(r"^[a-zA-Z0-9._-]{1,255}$")

# Databricks hosts: must end with a known Databricks domain.
_DATABRICKS_HOST_RE = re.compile(
    r"^[a-zA-Z0-9.-]+"
    r"\.(cloud\.databricks\.com|azuredatabricks\.net|gcp\.databricks\.com|databricksapps\.com)$"
)

# BigQuery project IDs: lowercase letters, digits, hyphens; 6-30 chars.
_BIGQUERY_PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")


def validate_cloud_warehouse_params(
    db_type: str,
    host: str | None = None,
    account: str | None = None,
    project_id: str | None = None,
) -> None:
    """Validate cloud warehouse connection parameters to prevent SSRF.

    Cloud warehouses (snowflake, bigquery, databricks) are not TCP-connected
    via raw sockets, so they skip the normal DNS-based SSRF check. Instead we
    validate that user-supplied identifiers conform to expected formats, which
    prevents an attacker from injecting arbitrary hostnames/URLs.

    Raises:
        ValueError: if the parameter format is invalid.
    """
    if db_type == "snowflake":
        val = account or host or ""
        if val and not _SNOWFLAKE_ACCOUNT_RE.match(val):
            raise ValueError("Invalid Snowflake account identifier: contains disallowed characters")
    elif db_type == "databricks":
        val = host or ""
        if val and not _DATABRICKS_HOST_RE.match(val):
            raise ValueError(
                "Invalid Databricks host: must match *.cloud.databricks.com, "
                "*.azuredatabricks.net, *.gcp.databricks.com, or *.databricksapps.com"
            )
    elif db_type == "bigquery":
        val = project_id or ""
        if val and not _BIGQUERY_PROJECT_RE.match(val):
            raise ValueError("Invalid BigQuery project_id format")


def _allow_private_connections() -> bool:
    """Return True if SP_ALLOW_PRIVATE_CONNECTIONS is set to a truthy value."""
    val = os.environ.get(_ALLOW_PRIVATE_ENV_VAR, "").strip().lower()
    return val in ("1", "true", "yes")


def _is_blocked_address(addr: ipaddress.IPv4Address | ipaddress.IPv6Address, allow_private: bool) -> bool:
    """Return True if this IP address should be blocked for SSRF protection.

    Always blocked (regardless of SP_ALLOW_PRIVATE_CONNECTIONS):
    - Loopback: 127.0.0.0/8, ::1
    - Link-local: 169.254.0.0/16 (includes AWS metadata 169.254.169.254),
      fe80::/10
    - Unspecified: 0.0.0.0, ::
    - ALWAYS_BLOCKED_NETWORKS: CGNAT 100.64.0.0/10 (RFC 6598), 6to4 relay
      192.88.99.0/24 (RFC 7526) — no stdlib property covers these ranges

    Blocked only when SP_ALLOW_PRIVATE_CONNECTIONS is unset/false:
    - RFC1918 private ranges: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
    - IPv6 unique-local: fc00::/7

    Note: _check_ip_address() is the single call site for both direct IPv4/IPv6
    and IPv4-mapped IPv6 paths — no changes to _check_ip_address() are needed.
    """
    if addr.is_loopback:
        return True
    if addr.is_link_local:
        return True
    if addr.is_unspecified:
        return True

    if any(addr in net for net in ALWAYS_BLOCKED_NETWORKS):
        return True

    if not allow_private:
        if addr.is_private:
            return True

    return False


def _check_ip_address(ip_str: str, allow_private: bool) -> None:
    """Parse and check a single IP address string. Raises ValueError if blocked.

    Also handles IPv4-mapped IPv6 addresses (::ffff:x.x.x.x) by extracting
    and checking the embedded IPv4 address, preventing bypass via IPv6 notation.
    """
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError as exc:
        raise ValueError(f"Cannot parse resolved IP address: {ip_str!r}") from exc

    # Check IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1) by extracting embedded IPv4.
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        mapped = addr.ipv4_mapped
        if _is_blocked_address(mapped, allow_private):
            raise ValueError(f"Connection refused: resolved address {ip_str!r} maps to blocked IPv4 address {mapped!s}")
        return

    if _is_blocked_address(addr, allow_private):
        raise ValueError(f"Connection refused: resolved address {ip_str!r} is a blocked internal/private address")


def assert_address_allowed(ip: str) -> None:
    """Raise ValueError if a literal IP address is on the SSRF denylist.

    Used to re-check the address a driver actually connected to, which is the only
    control available for drivers that resolve outside socket.getaddrinfo.
    """
    _check_ip_address(ip, _allow_private_connections())


def validate_connection_host(host: str) -> None:
    """Validate that a hostname does not resolve to a blocked address.

    Resolves ALL IPs for the hostname (prevents DNS rebinding by checking every
    returned address) and rejects if any IP is in a blocked range.

    Raises:
        ValueError: if the host resolves to a blocked address, resolution fails,
                    or the host string is empty.
    """
    if not host or not host.strip():
        raise ValueError("Host must not be empty")

    host = host.strip()
    allow_private = _allow_private_connections()

    try:
        # socket.getaddrinfo does not accept a timeout argument directly, so we
        # use the socket-level default timeout as a process-wide guard.
        # A threading lock prevents concurrent requests from racing on the
        # process-wide timeout value.
        with _dns_timeout_lock:
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(DNS_TIMEOUT_SECONDS)
            try:
                results = socket.getaddrinfo(host, None)
            finally:
                socket.setdefaulttimeout(old_timeout)
    except socket.gaierror as exc:
        raise ValueError(
            f"DNS resolution failed for host {host!r}: {exc}. "
            "Refusing connection — DNS failure is treated as rejection."
        ) from exc
    except OSError as exc:
        raise ValueError(f"Network error resolving host {host!r}: {exc}. Refusing connection.") from exc

    if not results:
        raise ValueError(f"DNS resolution returned no addresses for host {host!r}. Refusing connection.")

    # Check ALL resolved addresses to prevent DNS rebinding.
    # sockaddr is always (ip_str, port, ...) — position 0 is always str.
    for _family, _socktype, _proto, _canonname, sockaddr in results:
        ip_str = cast(str, sockaddr[0])
        _check_ip_address(ip_str, allow_private)


def resolve_and_validate(host: str, port: int, db_type: str) -> list[str]:
    """Resolve hostname, validate against SSRF denylist, return validated IP strings.

    This combines DNS resolution and SSRF validation into a single step, returning
    the resolved IPs so the caller can connect directly to the IP (not the hostname).
    This eliminates DNS rebinding TOCTOU attacks where DNS records change between
    validation and connection.

    Raises:
        ValueError: if the host resolves to a blocked address, resolution fails,
                    or the host string is empty.
    """
    if not host or not host.strip():
        raise ValueError("Host must not be empty")

    host = host.strip()
    allow_private = _allow_private_connections()

    try:
        with _dns_timeout_lock:
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(DNS_TIMEOUT_SECONDS)
            try:
                addrs = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
            finally:
                socket.setdefaulttimeout(old_timeout)
    except socket.gaierror as exc:
        raise ValueError(
            f"DNS resolution failed for host {host!r}: {exc}. "
            "Refusing connection — DNS failure is treated as rejection."
        ) from exc
    except OSError as exc:
        raise ValueError(f"Network error resolving host {host!r}: {exc}. Refusing connection.") from exc

    if not addrs:
        raise ValueError(f"DNS resolution returned no addresses for host {host!r}. Refusing connection.")

    ips = list({addr[4][0] for addr in addrs})

    # Validate every resolved IP against the SSRF denylist.
    for ip_str in ips:
        _check_ip_address(ip_str, allow_private)

    return ips


# ---------------------------------------------------------------------------
# Resolution pinning
# ---------------------------------------------------------------------------
# resolve_and_validate checks the addresses a hostname resolves to, but every
# driver then performs its OWN lookup when it connects, so a rebinding record can
# swap in an internal address in between. Substituting the validated IP into the
# DSN would close that window but breaks TLS hostname verification
# (sslmode=verify-full) and SNI-based routing, which managed Postgres/Snowflake
# style endpoints depend on. Instead the resolver itself is pinned for the
# duration of the connect: the driver still receives the hostname — so the
# certificate check and the SNI extension are unchanged — but its lookup can only
# return addresses that were already validated.
#
# Coverage is exactly "lookups that go through socket.getaddrinfo", which
# includes asyncpg (via loop.getaddrinfo), pymysql, clickhouse-driver and the
# requests/urllib3 stack behind trino. Drivers that resolve inside a C library
# (psycopg2/libpq, pymssql/FreeTDS) never call it and are NOT pinned.

# Captured at import so pinned entries are always resolved by the real stdlib
# function — never by a wrapper or a patched-in replacement.
_STDLIB_GETADDRINFO = socket.getaddrinfo

_pin_lock = threading.RLock()
# host (lowercased) -> (validated addresses, active pin count)
_pinned_hosts: dict[str, tuple[tuple[str, ...], int]] = {}
# The callable our hook displaced, restored when the last pin is released.
_displaced_getaddrinfo: Any = None


def _pinning_getaddrinfo(host: Any, port: Any, family: int = 0, type: int = 0, proto: int = 0, flags: int = 0) -> list:
    """socket.getaddrinfo replacement that answers pinned hosts from cache."""
    name = host
    if isinstance(name, bytes):
        name = name.decode("ascii", "ignore")

    pinned: tuple[str, ...] | None = None
    with _pin_lock:
        passthrough = _displaced_getaddrinfo or _STDLIB_GETADDRINFO
        if isinstance(name, str):
            entry = _pinned_hosts.get(name.strip().lower())
            if entry is not None:
                pinned = entry[0]

    if pinned is None:
        return passthrough(host, port, family, type, proto, flags)

    results: list = []
    for ip in pinned:
        try:
            results.extend(_STDLIB_GETADDRINFO(ip, port, family, type, proto, flags | socket.AI_NUMERICHOST))
        except socket.gaierror:
            continue
    if not results:
        raise socket.gaierror(
            socket.EAI_NONAME,
            f"No validated address for {name!r} matches the requested address family",
        )
    return results


@contextlib.contextmanager
def pinned_resolution(host: str, ips: Sequence[str]) -> Iterator[None]:
    """Pin ``host`` to ``ips`` for the duration of the block.

    ``ips`` must already have passed the SSRF denylist. Nested and concurrent
    pins of the same host are reference counted; the hook is uninstalled once the
    last pin is released, so the stdlib resolver is untouched outside a connect.
    """
    key = (host or "").strip().lower()
    if not key or not ips:
        yield
        return

    global _displaced_getaddrinfo
    addrs = tuple(ips)
    with _pin_lock:
        existing = _pinned_hosts.get(key)
        # A concurrent pin for the same host already validated its own addresses;
        # keep the first set rather than widening it.
        _pinned_hosts[key] = (existing[0], existing[1] + 1) if existing else (addrs, 1)
        if _displaced_getaddrinfo is None:
            _displaced_getaddrinfo = socket.getaddrinfo
            socket.getaddrinfo = _pinning_getaddrinfo  # type: ignore[assignment]
    try:
        yield
    finally:
        with _pin_lock:
            current = _pinned_hosts.get(key)
            if current is not None:
                if current[1] <= 1:
                    del _pinned_hosts[key]
                else:
                    _pinned_hosts[key] = (current[0], current[1] - 1)
            if not _pinned_hosts and _displaced_getaddrinfo is not None:
                # Only restore if nothing else replaced the hook underneath us.
                if socket.getaddrinfo is _pinning_getaddrinfo:
                    socket.getaddrinfo = _displaced_getaddrinfo  # type: ignore[assignment]
                _displaced_getaddrinfo = None


def validate_connection_params(
    host: str | None,
    port: int | None,
    db_type: str,
    connection_string: str | None,
) -> None:
    """Top-level SSRF validation called at connection create/update/test boundaries.

    Decides whether to run SSRF validation based on db_type.
    Only TCP-based db_types (postgres, mysql, mssql, redshift, clickhouse, trino)
    are validated. Cloud and embedded db_types are skipped.

    When connection_string is provided, parses it to extract the hostname.
    When host is provided directly, uses that.

    Raises:
        ValueError: if the db_type is TCP-based and the host resolves to a
                    blocked address, or if DNS resolution fails.
    """
    if db_type not in TCP_DB_TYPES:
        # Cloud warehouses: validate parameter format even though we skip TCP checks.
        if db_type in ("snowflake", "bigquery", "databricks"):
            validate_cloud_warehouse_params(
                db_type,
                host=host,
                account=host,  # Snowflake passes account via host param
                project_id=host,  # BigQuery passes project via host param
            )
        return

    # Local mode: SSRF validation disabled (local/private connections expected)
    if os.environ.get("SP_DEPLOYMENT_MODE", "local") != "cloud":
        return

    target_host: str | None = None

    if connection_string:
        parsed = urlparse(connection_string if "://" in connection_string else f"dummy://{connection_string}")
        target_host = parsed.hostname or host
    else:
        target_host = host

    if not target_host:
        raise ValueError(
            f"No host could be determined for TCP-based connection type "
            f"'{db_type}'. A valid host is required for SSRF validation."
        )

    validate_connection_host(target_host)


def validate_xata_control_url(url: str) -> None:
    """Reject non-https or SSRF-risky xata_api_url / xata_token_url.

    https scheme + non-empty hostname are enforced in any mode. The SSRF
    deny-list (loopback / link-local / private / IMDS) is applied in cloud
    mode only, matching validate_connection_host's cloud-mode gating.
    """
    from gateway.runtime.mode import is_cloud_mode

    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("xata_api_url/xata_token_url must use https://")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("xata_api_url/xata_token_url must include a valid hostname")
    if is_cloud_mode():
        validate_connection_host(hostname)


def log_startup_warning() -> None:
    """Log a warning at startup if SP_ALLOW_PRIVATE_CONNECTIONS is set."""
    if _allow_private_connections():
        logger.warning(
            "SP_ALLOW_PRIVATE_CONNECTIONS is enabled. RFC1918 private ranges "
            "are allowed for TCP database connections. Loopback and link-local "
            "addresses (including 169.254.169.254) are still blocked."
        )
