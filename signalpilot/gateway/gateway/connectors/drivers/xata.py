"""Xata connector — new Xata platform (xata.tech), Postgres-wire with server-side
branch-endpoint resolution.

A Xata connection is a *project*, not a single database. The stored secret is a
scoped Xata API key (control-plane, `xau_...`). Each branch is its own Postgres
host (`<branchID>.<region>.xata.tech`); the gateway resolves that endpoint and the
branch's data-plane credentials server-side — the agent never sees a URL or a
password and can address any branch in the project by name.

The data path (queries, schema introspection, governance) is identical to
Postgres, so this subclasses PostgresConnector. We differ in:
  - branch endpoints are resolved via the Xata control-plane API at connect time,
  - TLS is mandatory (Xata requires it; real cloud cert → verify-full).
"""

from __future__ import annotations

from .postgres import PostgresConnector


class XataConnector(PostgresConnector):
    def __init__(self):
        super().__init__()
        self._credential_extras: dict = {}

    def set_credential_extras(self, extras: dict) -> None:
        super().set_credential_extras(extras)
        self._credential_extras = extras or {}

    async def connect(self, connection_string: str) -> None:
        """Connect to a Xata branch.

        If given a real Postgres URL, connect directly. Otherwise (the normal
        path — a `xata://org/project/branch` sentinel), resolve the branch's
        Postgres endpoint via the control plane from the stored API key.
        """
        cs = connection_string
        if not cs or not cs.startswith("postgres"):
            cs = await self._resolve_endpoint(self._credential_extras)

        # Xata uses a public CA chain → verify-full. Operators may explicitly opt
        # into weaker verification via ssl_config, but never by omission.
        if not self._ssl_config or not self._ssl_config.get("enabled"):
            self._ssl_config = {"enabled": True, "mode": "verify-full"}
        elif self._ssl_config.get("mode") in (None, "require", "prefer", "allow"):
            self._ssl_config["mode"] = "verify-full"
        await super().connect(cs)

    @staticmethod
    async def _resolve_endpoint(extras: dict) -> str:
        """Resolve a branch (by name) to a Postgres connection string via the API."""
        api_key = extras.get("xata_api_key")
        api_url = extras.get("xata_api_url") or "https://api.xata.tech"
        org = extras.get("xata_organization") or extras.get("xata_org")
        project = extras.get("xata_project")
        branch = extras.get("branch") or "main"
        database = extras.get("xata_database") or "xata"
        if not (api_key and org and project):
            raise RuntimeError(
                "Xata connection requires xata_api_key, xata_organization, and xata_project"
            )
        # Lazy import to avoid an import cycle.
        from gateway.connectors.xata_control import XataControlClient, XataControlConfig

        cfg = XataControlConfig(api_url=api_url, org=org, bearer_token=api_key)
        async with XataControlClient(cfg) as cc:
            return await cc.resolve_branch_endpoint(project, branch, database)

    async def branch_endpoint(self, branch_name: str) -> str:
        """Resolve a *different* branch's connection string (for a branch diff)."""
        return await self._resolve_endpoint({**self._credential_extras, "branch": branch_name})
