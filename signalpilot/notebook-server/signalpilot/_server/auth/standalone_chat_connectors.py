"""Per-run external MCP connectors for standalone chat execution.

The gateway resolves the connectors a run may use and sends them in the
execute body as ``mcp_connectors``. This module validates that list, turns it
into standard ``mcpServers`` entries for the agent SDK, and derives the
``mcp__<slug>__<tool>`` allowlist.

Body shape consumed (produced by ``gateway/standalone_chat/execution.py``)::

    "mcp_connectors": [
      {"slug": str, "kind": "remote", "url": str, "allowed_tools": [str, ...]},
      {"slug": str, "kind": "sandbox", "command": str, "args": [str, ...],
       "env": {str: str}, "allowed_tools": [str, ...]}
    ]

Sandbox ``env`` values are per-run secrets. They are held only on the parsed
connector, copied into the SDK ``mcp_servers`` config, and never logged or
exported into the notebook process environment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from starlette.exceptions import HTTPException

from signalpilot import _loggers

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

LOGGER = _loggers.sp_logger()

# Server names owned by SignalPilot itself. A connector may never shadow them.
RESERVED_MCP_SERVER_NAMES = frozenset(
    {"signalpilot", "standalone-chat", "signalpilot-notebook"}
)
# Spec R9: slug = [a-z0-9_]{2,40}.
_SLUG_RE = re.compile(r"^[a-z0-9_]{2,40}$")
# Tool names as the SDK addresses them; no wildcard characters.
_TOOL_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_MAX_CONNECTORS = 32
_MAX_TOOLS_PER_CONNECTOR = 256

ConnectorKind = Literal["remote", "sandbox"]


@dataclass(frozen=True)
class ChatConnector:
    """One validated connector from the execute body."""

    slug: str
    kind: ConnectorKind
    allowed_tools: tuple[str, ...]
    url: str | None = None
    command: str | None = None
    args: tuple[str, ...] = ()
    # Secret-bearing. Excluded from repr so a stray log line cannot leak it.
    env: dict[str, str] = field(default_factory=dict, repr=False)

    @property
    def server_name(self) -> str:
        return self.slug

    def mcp_server(self, *, gateway_token: str) -> dict[str, Any]:
        """Standard ``mcpServers`` entry for the agent SDK."""
        if self.kind == "remote":
            return {
                "type": "http",
                "url": self.url,
                "headers": {"Authorization": f"Bearer {gateway_token}"},
            }
        server: dict[str, Any] = {"type": "stdio", "command": self.command}
        if self.args:
            server["args"] = list(self.args)
        if self.env:
            server["env"] = dict(self.env)
        return server

    def tool_allowlist(self) -> list[str]:
        return [f"mcp__{self.slug}__{tool}" for tool in self.allowed_tools]


def parse_mcp_connectors(body: Mapping[str, Any]) -> list[ChatConnector]:
    """Validate ``body["mcp_connectors"]``.

    Malformed entries and reserved or duplicate slugs are skipped with a log
    line that never includes env values. A non-list value is a 400.
    """
    raw = body.get("mcp_connectors")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="Invalid mcp_connectors")
    connectors: list[ChatConnector] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw[:_MAX_CONNECTORS]):
        connector = _parse_entry(entry, index=index)
        if connector is None:
            continue
        if connector.slug in seen:
            LOGGER.warning(
                "Skipping duplicate MCP connector slug=%s", connector.slug
            )
            continue
        seen.add(connector.slug)
        connectors.append(connector)
    if len(raw) > _MAX_CONNECTORS:
        LOGGER.warning(
            "Ignoring %d MCP connectors beyond the limit of %d",
            len(raw) - _MAX_CONNECTORS,
            _MAX_CONNECTORS,
        )
    return connectors


def _parse_entry(entry: object, *, index: int) -> ChatConnector | None:
    if not isinstance(entry, dict):
        LOGGER.warning("Skipping MCP connector #%d: not an object", index)
        return None
    slug = str(entry.get("slug") or "")
    if not _SLUG_RE.fullmatch(slug):
        LOGGER.warning("Skipping MCP connector #%d: invalid slug", index)
        return None
    if slug in RESERVED_MCP_SERVER_NAMES:
        LOGGER.warning(
            "Skipping MCP connector slug=%s: reserved server name", slug
        )
        return None
    kind = str(entry.get("kind") or "")
    allowed_tools = _parse_allowed_tools(entry.get("allowed_tools"), slug=slug)
    if not allowed_tools:
        LOGGER.info("Skipping MCP connector slug=%s: no allowed tools", slug)
        return None
    if kind == "remote":
        url = str(entry.get("url") or "").strip()
        if not url.startswith(("https://", "http://")):
            LOGGER.warning(
                "Skipping MCP connector slug=%s: invalid remote url", slug
            )
            return None
        return ChatConnector(
            slug=slug, kind="remote", url=url, allowed_tools=allowed_tools
        )
    if kind == "sandbox":
        command = str(entry.get("command") or "").strip()
        args = entry.get("args") or []
        env = entry.get("env") or {}
        if (
            not command
            or not isinstance(args, list)
            or not all(isinstance(value, str) for value in args)
            or not isinstance(env, dict)
            or not all(
                isinstance(name, str)
                and _ENV_NAME_RE.fullmatch(name)
                and isinstance(value, str)
                for name, value in env.items()
            )
        ):
            LOGGER.warning(
                "Skipping MCP connector slug=%s: invalid sandbox command", slug
            )
            return None
        return ChatConnector(
            slug=slug,
            kind="sandbox",
            command=command,
            args=tuple(args),
            env=dict(env),
            allowed_tools=allowed_tools,
        )
    LOGGER.warning("Skipping MCP connector slug=%s: unknown kind", slug)
    return None


def _parse_allowed_tools(raw: object, *, slug: str) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    tools: list[str] = []
    for tool in raw[:_MAX_TOOLS_PER_CONNECTOR]:
        if isinstance(tool, str) and _TOOL_RE.fullmatch(tool):
            if tool not in tools:
                tools.append(tool)
        else:
            LOGGER.warning(
                "Ignoring invalid tool name on MCP connector slug=%s", slug
            )
    return tuple(tools)


def connector_mcp_servers(
    connectors: Iterable[ChatConnector], *, gateway_token: str
) -> dict[str, dict[str, Any]]:
    """``mcpServers`` entries keyed by slug. Reserved names never appear."""
    return {
        connector.server_name: connector.mcp_server(
            gateway_token=gateway_token
        )
        for connector in connectors
        if connector.server_name not in RESERVED_MCP_SERVER_NAMES
    }


def connector_allowed_tools(connectors: Iterable[ChatConnector]) -> list[str]:
    """Explicit ``mcp__<slug>__<tool>`` names. Never a bare server wildcard."""
    names: list[str] = []
    for connector in connectors:
        names.extend(connector.tool_allowlist())
    return list(dict.fromkeys(names))


def connector_secret_values(
    connectors: Iterable[ChatConnector],
) -> tuple[str, ...]:
    """Sandbox env values, for output redaction."""
    values: list[str] = []
    for connector in connectors:
        values.extend(value for value in connector.env.values() if value)
    return tuple(dict.fromkeys(values))


def connector_slugs(connectors: Sequence[ChatConnector]) -> list[str]:
    return [connector.slug for connector in connectors]
