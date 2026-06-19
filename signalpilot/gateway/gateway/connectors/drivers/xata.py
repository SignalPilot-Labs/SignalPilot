"""Xata connector — Postgres-wire-compatible branches with server-side endpoint resolution.

A Xata connection is a *workspace*, not a single database. The stored secret is a
scoped Xata API key (embedded in the encrypted connection string as the password).
The actual per-branch Postgres endpoint is resolved here, server-side — the agent
never sees a URL and never holds a credential. Branches are addressed per-call, so
one registered workspace serves every branch.

The data path (queries, schema introspection, governance) is identical to Postgres,
so this subclasses PostgresConnector. We only differ in:
  - TLS is mandatory (Xata requires it),
  - we can mint a connection string for a *different* branch using the same key.
"""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse

from .postgres import PostgresConnector


class XataConnector(PostgresConnector):
    def __init__(self):
        super().__init__()
        self._xata_workspace: str | None = None
        self._xata_region: str | None = None
        self._xata_database: str | None = None
        self._xata_branch: str | None = None

    def _set_connector_specific_extras(self, extras: dict) -> None:
        super()._set_connector_specific_extras(extras)
        self._xata_workspace = extras.get("xata_workspace")
        self._xata_region = extras.get("xata_region")
        self._xata_database = extras.get("xata_database")
        self._xata_branch = extras.get("xata_branch")

    async def connect(self, connection_string: str) -> None:
        # Xata always requires TLS — force it even if the stored config omitted it.
        if not self._ssl_config or not self._ssl_config.get("enabled"):
            self._ssl_config = {"enabled": True, "mode": "require"}
        await super().connect(connection_string)

    @staticmethod
    def connection_string_for_branch(connection_string: str, branch: str) -> str:
        """Return the same Xata URL pointed at a different branch.

        Lets one stored workspace credential address any branch (e.g. for a
        head-to-head branch diff) without persisting a second secret. Only the
        path's `:branch` segment is rewritten; the netloc (and the API key in it)
        is left untouched.
        """
        parsed = urlparse(connection_string)
        db = parsed.path.rsplit(":", 1)[0] if ":" in parsed.path.lstrip("/") else parsed.path
        return urlunparse(parsed._replace(path=f"{db}:{branch}"))
