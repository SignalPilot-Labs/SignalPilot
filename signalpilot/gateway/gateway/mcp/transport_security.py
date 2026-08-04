"""Host allowlist construction for the MCP streamable-HTTP transport."""

from __future__ import annotations

INTERNAL_GATEWAY_PORT = 3300


def build_allowed_hosts(
    hosts: list[str],
    *,
    public_port: int,
    internal_port: int = INTERNAL_GATEWAY_PORT,
) -> list[str]:
    """Allow configured hosts on both browser-facing and service ports."""
    normalized = list(dict.fromkeys(host.strip() for host in hosts if host.strip()))
    allowed = list(normalized)
    for port in dict.fromkeys((public_port, internal_port)):
        for host in normalized:
            if host.rpartition(":")[2].isdigit():
                continue
            candidate = f"{host}:{port}"
            if candidate not in allowed:
                allowed.append(candidate)
    return allowed
