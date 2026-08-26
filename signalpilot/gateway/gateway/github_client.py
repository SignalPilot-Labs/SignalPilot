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


async def create_installation_token(
    app_jwt: str, installation_id: int, *, repository_ids: list[int]
) -> dict:
    """Mint an installation token RESTRICTED to *repository_ids*.

    SP-SEC-005 (permission amplification): a body-less POST to
    ``/access_tokens`` mints a token carrying the installation's full
    permissions across **every** repository in the installation. Passing
    ``repository_ids`` narrows the token to the repositories the authorizing
    user can actually access, preserving the user/app intersection that
    GitHub's user-access-token model would normally enforce.

    ``repository_ids`` is a required keyword argument and must be non-empty —
    an empty list would be serialized by GitHub as "no restriction requested"
    on some paths, so we refuse rather than risk minting a wide token. Callers
    that genuinely need installation-wide scope must call
    ``create_unrestricted_installation_token`` explicitly.

    ``permissions`` is deliberately NOT narrowed here: the product exercises
    contents(write), pull_requests(write), issues(write) and statuses(write)
    across the git sync path and the PR bot, which is effectively the whole
    granted set. The meaningful reduction available is repository scope.
    """
    if not repository_ids:
        raise ValueError(
            "create_installation_token requires a non-empty repository_ids list; "
            "use create_unrestricted_installation_token if installation-wide scope is intended"
        )
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {app_jwt}", "Accept": "application/vnd.github+json"},
            json={"repository_ids": list(repository_ids)},
        )
        resp.raise_for_status()
        return resp.json()


async def create_unrestricted_installation_token(app_jwt: str, installation_id: int) -> dict:
    """Mint a token with the installation's FULL permissions on ALL its repos.

    DANGEROUS — only legitimate where there is no tenant boundary to cross.
    The single intended caller is the local/single-tenant install path, where
    no user token exists to intersect against. Never call this on a cloud
    (multi-tenant) code path; use ``create_installation_token`` instead.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {app_jwt}", "Accept": "application/vnd.github+json"},
        )
        resp.raise_for_status()
        return resp.json()


async def list_user_installations(user_token: str, per_page: int = 100) -> list[dict]:
    installations: list[dict] = []
    page = 1
    async with httpx.AsyncClient(timeout=15) as client:
        while True:
            resp = await client.get(
                f"{GITHUB_API}/user/installations",
                params={"per_page": per_page, "page": page},
                headers={"Authorization": f"Bearer {user_token}", "Accept": "application/vnd.github+json"},
            )
            resp.raise_for_status()
            data = resp.json()
            installations.extend(data.get("installations", []))
            if len(data.get("installations", [])) < per_page:
                break
            page += 1
    return installations


async def list_user_installation_repositories(
    user_token: str, installation_id: int, per_page: int = 100
) -> list[dict]:
    """Repositories the authorizing USER can access within *installation_id*.

    Uses the user token, so the result is the user∩installation intersection —
    an org member who can reach only a subset of the installation's repos gets
    only that subset. Paginated the same way as ``list_user_installations``.
    """
    repos: list[dict] = []
    page = 1
    async with httpx.AsyncClient(timeout=15) as client:
        while True:
            resp = await client.get(
                f"{GITHUB_API}/user/installations/{installation_id}/repositories",
                params={"per_page": per_page, "page": page},
                headers={"Authorization": f"Bearer {user_token}", "Accept": "application/vnd.github+json"},
            )
            resp.raise_for_status()
            data = resp.json()
            batch = data.get("repositories", [])
            repos.extend(batch)
            if len(batch) < per_page:
                break
            page += 1
    return repos


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
