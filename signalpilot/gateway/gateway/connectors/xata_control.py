"""Xata control-plane client — branch lifecycle over the Xata platform REST API.

This is the CONTROL plane (list/create/delete branches, read a branch's Postgres
endpoint). The DATA plane (queries, schema, governance) is XataConnector, which
speaks plain Postgres. The agent never sees a URL or a key: it names a workspace
connection + a branch, and the gateway resolves everything server-side.

Auth models (both supported, since the OSS self-hosted platform and Xata Cloud
differ):
  - bearer:   a static API key / token sent as `Authorization: Bearer <token>`
              (Xata Cloud API keys).
  - oidc:     OAuth2 password grant against a Keycloak/OIDC token endpoint
              (self-hosted dev: client `cli`, secret `devsecret`, user dev@xata.tech).

Verified against the OSS platform (openapi/projects.yaml): endpoints
  GET  /organizations
  GET  /organizations/{org}/projects
  POST /organizations/{org}/projects
  GET  /organizations/{org}/projects/{proj}/branches
  POST /organizations/{org}/projects/{proj}/branches
  GET  /organizations/{org}/projects/{proj}/branches/{branch}
  DELETE .../branches/{branch}
  GET  /organizations/{org}/regions | /images | /instanceTypes?region=<r>
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class XataControlConfig:
    api_url: str  # e.g. https://api.xata.io  or  http://localhost:5001
    org: str = "default-org"
    # --- auth: bearer ---
    bearer_token: str | None = None  # static API key / token
    # --- auth: oidc password grant (self-hosted dev) ---
    token_url: str | None = None  # e.g. http://localhost:8080/realms/xata/protocol/openid-connect/token
    client_id: str | None = None
    client_secret: str | None = None
    username: str | None = None
    password: str | None = None


class XataControlError(RuntimeError):
    pass


class XataControlClient:
    def __init__(self, cfg: XataControlConfig, *, timeout: float = 60.0):
        self._cfg = cfg
        self._timeout = timeout
        self._cached_token: str | None = cfg.bearer_token
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> XataControlClient:
        self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, *a: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _token(self, client: httpx.AsyncClient, *, force: bool = False) -> str:
        if self._cfg.bearer_token:
            return self._cfg.bearer_token
        if self._cached_token and not force:
            return self._cached_token
        if not self._cfg.token_url:
            raise XataControlError("no bearer_token and no token_url configured")
        if not self._cfg.client_id or not self._cfg.client_secret or not self._cfg.username or not self._cfg.password:
            raise XataControlError("OIDC credentials missing")
        r = await client.post(
            self._cfg.token_url,
            data={
                "grant_type": "password",
                "client_id": self._cfg.client_id,
                "client_secret": self._cfg.client_secret,
                "username": self._cfg.username,
                "password": self._cfg.password,
                "scope": "openid",
            },
        )
        if r.status_code != 200:
            raise XataControlError(f"token request failed: {r.status_code}: {r.text[:300]}")
        self._cached_token = r.json().get("access_token")
        if not self._cached_token:
            raise XataControlError("token response had no access_token")
        return self._cached_token

    async def _request(self, method: str, path: str, *, json: Any = None) -> Any:
        if self._client is None:
            raise XataControlError("client not opened — use async with")
        url = f"{self._cfg.api_url.rstrip('/')}{path}"
        tok = await self._token(self._client)
        r = await self._client.request(method, url, json=json,
                                       headers={"Authorization": f"Bearer {tok}"})
        if r.status_code == 401:  # token may have expired — refresh once
            tok = await self._token(self._client, force=True)
            r = await self._client.request(method, url, json=json,
                                           headers={"Authorization": f"Bearer {tok}"})
        if r.status_code >= 400:
            raise XataControlError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else None

    # ---- projects ----------------------------------------------------------
    async def list_projects(self) -> list[dict]:
        data = await self._request("GET", f"/organizations/{self._cfg.org}/projects")
        return data.get("projects", [])

    async def create_project(self, name: str) -> dict:
        return await self._request(
            "POST", f"/organizations/{self._cfg.org}/projects", json={"name": name}
        )

    # ---- branches ----------------------------------------------------------
    async def list_branches(self, project_id: str) -> list[dict]:
        data = await self._request(
            "GET", f"/organizations/{self._cfg.org}/projects/{project_id}/branches"
        )
        return data.get("branches", [])

    async def get_branch(self, project_id: str, branch_id: str) -> dict:
        return await self._request(
            "GET",
            f"/organizations/{self._cfg.org}/projects/{project_id}/branches/{branch_id}",
        )

    async def create_child_branch(self, project_id: str, name: str, parent_id: str) -> dict:
        """Instant copy-on-write branch from a parent."""
        return await self._request(
            "POST",
            f"/organizations/{self._cfg.org}/projects/{project_id}/branches",
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
            f"/organizations/{self._cfg.org}/projects/{project_id}/branches",
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
            f"/organizations/{self._cfg.org}/projects/{project_id}/branches/{branch_id}",
        )

    async def branch_connection_string(self, project_id: str, branch_id: str) -> str | None:
        """The branch's Postgres endpoint (None until the cluster is ready)."""
        return (await self.get_branch(project_id, branch_id)).get("connectionString")
