"""Minimal GitHub REST client for the PipelineProof bot.

One httpx.AsyncClient per GitHubBotClient instance (connection reuse across a
scan's ~6 calls); transient failures (403 secondary rate limit, 429, 5xx) are
retried with backoff honoring Retry-After.

Token resolution (per repo): explicit token → App installation token for a
linked repo (gateway_github_installations) → SP_GITHUB_BOT_TOKEN PAT.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from gateway.config.github_bot import get_github_bot_settings

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

# Marker that identifies the bot's own comment so re-scans update in place
# instead of stacking new comments on every push.
COMMENT_MARKER = "<!-- signalpilot-pipelineproof -->"

STATUS_CONTEXT = "signalpilot/pipelineproof"

_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3


class GitHubBotClient:
    def __init__(self, token: str) -> None:
        self._headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=20, headers=self._headers)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        client = self._get_client()
        last_exc: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = await client.request(method, f"{GITHUB_API}{path}", **kwargs)
                retryable = resp.status_code in _RETRY_STATUSES or (
                    # Secondary rate limits surface as 403 with Retry-After.
                    resp.status_code == 403 and "retry-after" in resp.headers
                )
                if retryable and attempt < _MAX_ATTEMPTS - 1:
                    delay = float(resp.headers.get("retry-after", 2 ** (attempt + 1)))
                    logger.info("GitHub %s %s → %d, retrying in %.0fs", method, path, resp.status_code, delay)
                    await asyncio.sleep(min(delay, 60))
                    continue
                resp.raise_for_status()
                return resp
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt < _MAX_ATTEMPTS - 1:
                    await asyncio.sleep(2 ** (attempt + 1))
                    continue
                raise
        raise last_exc or RuntimeError("unreachable")

    async def get_pr(self, repo: str, pr_number: int) -> dict:
        return (await self._request("GET", f"/repos/{repo}/pulls/{pr_number}")).json()

    async def list_pr_files(self, repo: str, pr_number: int) -> list[dict]:
        files: list[dict] = []
        page = 1
        while True:
            resp = await self._request(
                "GET", f"/repos/{repo}/pulls/{pr_number}/files", params={"per_page": 100, "page": page}
            )
            batch = resp.json()
            files.extend(batch)
            if len(batch) < 100:
                return files
            page += 1

    async def upsert_pr_comment(self, repo: str, pr_number: int, body: str) -> dict:
        """Create the bot comment, or update it in place if one already exists.

        A PATCH 404 (comment deleted between list and update) falls back to
        creating a fresh comment rather than failing the scan.
        """
        page = 1
        while True:
            resp = await self._request(
                "GET", f"/repos/{repo}/issues/{pr_number}/comments", params={"per_page": 100, "page": page}
            )
            batch = resp.json()
            for comment in batch:
                if COMMENT_MARKER in (comment.get("body") or ""):
                    try:
                        return (
                            await self._request(
                                "PATCH", f"/repos/{repo}/issues/comments/{comment['id']}", json={"body": body}
                            )
                        ).json()
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code != 404:
                            raise
                        break  # deleted meanwhile — create fresh below
            if len(batch) < 100:
                break
            page += 1
        return (await self._request("POST", f"/repos/{repo}/issues/{pr_number}/comments", json={"body": body})).json()

    async def set_commit_status(self, repo: str, sha: str, state: str, description: str, target_url: str = "") -> None:
        """state: pending | success | failure | error"""
        payload: dict = {"state": state, "context": STATUS_CONTEXT, "description": description[:140]}
        if target_url:
            payload["target_url"] = target_url
        await self._request("POST", f"/repos/{repo}/statuses/{sha}", json=payload)

    async def create_pull_request(
        self, repo: str, *, title: str, head: str, base: str, body: str, draft: bool = False
    ) -> dict:
        return (
            await self._request(
                "POST",
                f"/repos/{repo}/pulls",
                json={"title": title, "head": head, "base": base, "body": body, "draft": draft},
            )
        ).json()

    async def get_default_branch(self, repo: str) -> str:
        return (await self._request("GET", f"/repos/{repo}")).json().get("default_branch", "main")

    async def get_ref_sha(self, repo: str, branch: str) -> str:
        data = (await self._request("GET", f"/repos/{repo}/git/ref/heads/{branch}")).json()
        return data["object"]["sha"]

    async def create_branch(self, repo: str, branch: str, from_sha: str) -> None:
        await self._request("POST", f"/repos/{repo}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": from_sha})

    async def put_file(
        self, repo: str, path: str, *, content_b64: str, message: str, branch: str, sha: str | None = None
    ) -> dict:
        payload: dict = {"message": message, "content": content_b64, "branch": branch}
        if sha:
            payload["sha"] = sha
        return (await self._request("PUT", f"/repos/{repo}/contents/{path}", json=payload)).json()

    async def get_file_sha(self, repo: str, path: str, branch: str) -> str | None:
        try:
            resp = await self._request("GET", f"/repos/{repo}/contents/{path}", params={"ref": branch})
            return resp.json().get("sha")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise


async def resolve_bot_token(repo_full_name: str) -> str | None:
    """Best token for a repo: App installation token (linked repo) → PAT env."""
    try:
        from gateway.db.engine import get_session_factory
        from gateway.store import github as github_store

        factory = get_session_factory()
        async with factory() as session:
            token = await github_store.get_token_for_repo(session, repo_full_name=repo_full_name)
            if token:
                return token
    except Exception as exc:
        logger.warning(
            "GitHub App lookup failed for repository %s (%s). Using the configured fallback.",
            repo_full_name,
            type(exc).__name__,
        )
    cfg = get_github_bot_settings()
    return cfg.token or None
