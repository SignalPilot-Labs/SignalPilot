"""GitHub App API client — JWT generation, token exchange, repo listing."""

from __future__ import annotations

import logging
import time

import httpx
import jwt

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


def generate_app_jwt(app_id: str, private_key: str) -> str:
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": str(app_id)}
    return jwt.encode(payload, private_key, algorithm="RS256")


async def exchange_code_for_token(
    client_id: str, client_secret: str, code: str
) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://github.com/login/oauth/access_token",
            json={"client_id": client_id, "client_secret": client_secret, "code": code},
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()


async def get_installation_details(app_jwt: str, installation_id: int) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{GITHUB_API}/app/installations/{installation_id}",
            headers={"Authorization": f"Bearer {app_jwt}", "Accept": "application/vnd.github+json"},
        )
        resp.raise_for_status()
        return resp.json()


async def create_installation_token(app_jwt: str, installation_id: int) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {app_jwt}", "Accept": "application/vnd.github+json"},
        )
        resp.raise_for_status()
        return resp.json()


async def list_installation_repos(token: str, per_page: int = 100) -> list[dict]:
    repos: list[dict] = []
    page = 1
    async with httpx.AsyncClient(timeout=15) as client:
        while True:
            resp = await client.get(
                f"{GITHUB_API}/installation/repositories",
                params={"per_page": per_page, "page": page},
                headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"},
            )
            resp.raise_for_status()
            data = resp.json()
            repos.extend(data.get("repositories", []))
            if len(data.get("repositories", [])) < per_page:
                break
            page += 1
    return repos
