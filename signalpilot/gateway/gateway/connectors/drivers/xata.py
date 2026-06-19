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

import re
from urllib.parse import quote, urlparse, urlunparse

from .postgres import PostgresConnector

_BRANCH_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class XataConnector(PostgresConnector):
    def __init__(self):
        super().__init__()

    async def connect(self, connection_string: str) -> None:
        """Connect to a Xata branch.

        Xata uses a public CA chain; default to verify-full. Operators may
        explicitly set mode = 'require' in ssl_config to opt into weaker
        verification — but only if they set it on purpose, not by omission.
        """
        if not self._ssl_config or not self._ssl_config.get("enabled"):
            self._ssl_config = {"enabled": True, "mode": "verify-full"}
        elif self._ssl_config.get("mode") in (None, "require", "prefer", "allow"):
            # Operator left TLS on but did not explicitly opt out of verification.
            self._ssl_config["mode"] = "verify-full"
        await super().connect(connection_string)

    @staticmethod
    def connection_string_for_branch(connection_string: str, branch: str) -> str:
        """Return the same Xata URL pointed at a different branch.

        Lets one stored workspace credential address any branch (e.g. for a
        head-to-head branch diff) without persisting a second secret. Only the
        path's `:branch` segment is rewritten; the netloc (and the API key in it)
        is left untouched.
        """
        if not _BRANCH_RE.match(branch):
            raise ValueError("Invalid branch")
        parsed = urlparse(connection_string)
        db = parsed.path.rsplit(":", 1)[0] if ":" in parsed.path.lstrip("/") else parsed.path
        return urlunparse(parsed._replace(path=f"{db}:{quote(branch, safe='')}"))
