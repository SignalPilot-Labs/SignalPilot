"""SSRF guard for every user-supplied URL (R8).

https only (http only for localhost / 127.0.0.1 outside cloud mode); DNS is
resolved and private, link-local, loopback, metadata and ULA ranges are
rejected; redirects are re-checked per hop through an httpx request hook;
10 s probe timeout; 1 MB response cap.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx

from gateway.runtime.mode import is_cloud_mode

PROBE_TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_BYTES = 1_048_576
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})
_BLOCKED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::ffff:0:0/96"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
)


class UnsafeUrlError(ValueError):
    """The URL points somewhere the gateway must not connect to."""


def is_blocked_ip(ip: str) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return True
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return any(address in network for network in _BLOCKED_NETWORKS)


def _is_local_dev_host(host: str) -> bool:
    return host.lower() in _LOCAL_HOSTS and not is_cloud_mode()


def validate_url_syntax(url: str) -> str:
    """Scheme/host checks that need no network. Returns the URL stripped."""
    candidate = (url or "").strip()
    parts = urlsplit(candidate)
    if parts.scheme not in {"http", "https"}:
        raise UnsafeUrlError("The address must start with https://")
    host = parts.hostname or ""
    if not host:
        raise UnsafeUrlError("The address has no host")
    if parts.username or parts.password:
        raise UnsafeUrlError("The address must not contain credentials")
    if parts.scheme == "http" and not _is_local_dev_host(host):
        raise UnsafeUrlError("Only https:// addresses are allowed")
    if parts.fragment:
        candidate = candidate.split("#", 1)[0]
    return candidate


async def resolve_public_addresses(host: str, port: int | None) -> list[str]:
    """Resolve the host and return its addresses, raising when any is non-public."""
    if _is_local_dev_host(host):
        return [host]
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        address = None
    if address is not None:
        if is_blocked_ip(str(address)):
            raise UnsafeUrlError("The address points at a private or internal network")
        return [str(address)]
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(
            loop.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM),
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except (socket.gaierror, TimeoutError, OSError) as exc:
        raise UnsafeUrlError("We couldn't resolve this address") from exc
    addresses = sorted({str(info[4][0]) for info in infos})
    if not addresses:
        raise UnsafeUrlError("We couldn't resolve this address")
    for ip in addresses:
        if is_blocked_ip(ip):
            raise UnsafeUrlError("The address points at a private or internal network")
    return addresses


async def validate_remote_url(url: str) -> str:
    """Full check: syntax + DNS. Returns the normalized URL."""
    normalized = validate_url_syntax(url)
    parts = urlsplit(normalized)
    await resolve_public_addresses(parts.hostname or "", parts.port)
    return normalized


async def _guard_request(request: httpx.Request) -> None:
    """httpx request hook: re-validate every hop, including redirects."""
    await validate_remote_url(str(request.url))


async def _cap_response(response: httpx.Response) -> None:
    length = response.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_RESPONSE_BYTES:
        await response.aclose()
        raise UnsafeUrlError("The response is larger than 1 MB")


def safe_async_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | float | None = None,
    auth: httpx.Auth | None = None,
    *,
    follow_redirects: bool = True,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """httpx client whose every request (and redirect hop) passes the SSRF guard.

    ``transport`` lets tests substitute ``httpx.MockTransport`` while keeping
    the guard hooks in place.
    """
    if timeout is None:
        timeout = httpx.Timeout(PROBE_TIMEOUT_SECONDS, read=60.0)
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        auth=auth,
        follow_redirects=follow_redirects,
        max_redirects=3,
        transport=transport,
        event_hooks={"request": [_guard_request], "response": [_cap_response]},
    )


async def read_capped(response: httpx.Response) -> bytes:
    """Read at most MAX_RESPONSE_BYTES from a streamed response."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise UnsafeUrlError("The response is larger than 1 MB")
        chunks.append(chunk)
    return b"".join(chunks)


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()
