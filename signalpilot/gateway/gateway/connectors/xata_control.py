"""Manage Xata branches through the Xata platform REST API.

This client lists, creates, reads, and deletes control-plane resources.
XataConnector manages data-plane queries, schemas, and governance through PostgreSQL.
The gateway resolves branch endpoints and credentials on the server.
The client sends a static API key as an authorization bearer token.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote as _url_quote

import httpx


@dataclass
class XataControlConfig:
    api_url: str  # e.g. https://api.xata.io  or  http://localhost:5001
    org: str = "default-org"
    bearer_token: str | None = None  # static control-plane API key / token


class XataControlError(RuntimeError):
    pass


class XataControlClient:
    def __init__(self, cfg: XataControlConfig, *, timeout: float = 60.0):
        self._cfg = cfg
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> XataControlClient:
        self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, *a: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _token(self) -> str:
        if not self._cfg.bearer_token:
            raise XataControlError("no bearer_token configured")
        return self._cfg.bearer_token

    async def _request(self, method: str, path: str, *, json: Any = None) -> Any:
        if self._client is None:
            raise XataControlError("client not opened — use async with")
        url = f"{self._cfg.api_url.rstrip('/')}{path}"
        tok = self._token()
        r = await self._client.request(method, url, json=json,
                                       headers={"Authorization": f"Bearer {tok}"})
        if r.status_code >= 400:
            raise XataControlError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else None

    # ---- projects ----------------------------------------------------------
    async def list_projects(self) -> list[dict]:
        data = await self._request("GET", f"/organizations/{_url_quote(self._cfg.org, safe='')}/projects")
        return data.get("projects", [])

    async def create_project(self, name: str) -> dict:
        return await self._request(
            "POST", f"/organizations/{_url_quote(self._cfg.org, safe='')}/projects", json={"name": name}
        )

    # ---- branches ----------------------------------------------------------
    async def list_branches(self, project_id: str) -> list[dict]:
        data = await self._request(
            "GET", f"/organizations/{_url_quote(self._cfg.org, safe='')}/projects/{project_id}/branches"
        )
        return data.get("branches", [])

    async def get_branch(self, project_id: str, branch_id: str) -> dict:
        return await self._request(
            "GET",
            f"/organizations/{_url_quote(self._cfg.org, safe='')}/projects/{project_id}/branches/{branch_id}",
        )

    async def create_child_branch(self, project_id: str, name: str, parent_id: str) -> dict:
        """Instant copy-on-write branch from a parent."""
        return await self._request(
            "POST",
            f"/organizations/{_url_quote(self._cfg.org, safe='')}/projects/{project_id}/branches",
            json={"name": name, "mode": "inherit", "parentID": parent_id},
        )

    async def create_base_branch(
        self,
        project_id: str,
        name: str,
        *,
        region: str = "local",
        image: str = "postgres:17.10",
        instance_type: str = "xata.micro",
        replicas: int = 0,
    ) -> dict:
        return await self._request(
            "POST",
            f"/organizations/{_url_quote(self._cfg.org, safe='')}/projects/{project_id}/branches",
            json={
                "name": name,
                "mode": "custom",
                "configuration": {
                    "region": region,
                    "image": image,
                    "instanceType": instance_type,
                    "replicas": replicas,
                },
            },
        )

    async def delete_branch(self, project_id: str, branch_id: str) -> None:
        await self._request(
            "DELETE",
            f"/organizations/{_url_quote(self._cfg.org, safe='')}/projects/{project_id}/branches/{branch_id}",
        )

    async def branch_connection_string(self, project_id: str, branch_id: str) -> str | None:
        """The branch's Postgres endpoint (None until the cluster is ready)."""
        return (await self.get_branch(project_id, branch_id)).get("connectionString")

    # ---- new Xata (xata.tech): build endpoint from branch + credentials --------
    async def get_branch_credentials(self, project_id: str, branch_id: str, username: str = "xata") -> dict:
        """Return {username, password} for a branch's Postgres role (new Xata API)."""
        org = _url_quote(self._cfg.org, safe="")
        return await self._request(
            "GET",
            f"/organizations/{org}/projects/{project_id}/branches/{branch_id}/credentials"
            f"?username={_url_quote(username, safe='')}",
        )

    async def resolve_branch_endpoint(self, project_id: str, branch_name: str, database: str = "xata") -> str:
        """Resolve a branch (by name) to a full Postgres connection string.

        New Xata: each branch is its own host (<branchID>.<region>.xata.tech). We
        look up the branch by name, fetch the xata-user credentials, and assemble
        the URL server-side: the agent never sees host or password.
        """
        branches = await self.list_branches(project_id)
        b = next((x for x in branches if x.get("name") == branch_name), None)
        if not b:
            raise XataControlError(f"branch '{branch_name}' not found in project {project_id}")
        creds = await self.get_branch_credentials(project_id, b["id"])
        user = _url_quote(creds.get("username", "xata"), safe="")
        pw = _url_quote(creds.get("password", ""), safe="")
        host = f"{b['id']}.{b['region']}.xata.tech"
        return f"postgresql://{user}:{pw}@{host}/{_url_quote(database, safe='')}?sslmode=require"
