"""GitHub App installation lifecycle: claim, live repository scope, webhooks.

Installation model (Vercel-style): GitHub redirects the browser back with
``installation_id`` + our HMAC ``state``; the app JWT proves the installation
exists and tells us which account it belongs to; the installation's own
repository list defines the token scope. No OAuth user code is exchanged.

Tenancy boundary: a GitHub installation id is claimed by at most one org.
``complete_installation`` refuses to move a claimed installation to another
org, and webhooks only ever UPDATE rows that a browser flow already created.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import GatewayGitHubInstallation
from ..models.github import GitHubInstallationInfo

logger = logging.getLogger(__name__)


class InstallationClaimedError(Exception):
    """The GitHub installation is already connected to a different org."""


class InstallationNotFoundError(Exception):
    """GitHub does not know this installation id for our app."""


class RepositoryListingError(Exception):
    """The installation exists but its repositories could not be listed."""


def _expires_at(token_data: dict) -> float:
    expires_str = token_data.get("expires_at", "")
    if expires_str:
        return datetime.fromisoformat(expires_str.replace("Z", "+00:00")).timestamp()
    return time.time() + 3600


def _app_jwt() -> str:
    from ..config.github import get_github_settings
    from ..github_client import generate_app_jwt

    settings = get_github_settings()
    return generate_app_jwt(settings.sp_github_app_id, settings.sp_github_app_private_key)


async def list_installation_repositories_via_app(github_installation_id: int) -> list[dict]:
    """Repositories the installation grants, listed through the app.

    Mints an installation-wide token for the listing call only and discards
    it. The token never leaves this function (SP-SEC-005: handed-out tokens
    stay repository-scoped).
    """
    from ..github_client import create_unrestricted_installation_token, list_installation_repos

    token_data = await create_unrestricted_installation_token(_app_jwt(), github_installation_id)
    return await list_installation_repos(token_data["token"])


async def refresh_installation_repositories(
    session: AsyncSession, row: GatewayGitHubInstallation
) -> list[dict]:
    """Re-list the installation's repositories and store them as the scope.

    Updates ``authorized_repository_ids`` and ``authorized_repositories`` on
    the row and commits. Returns the raw repository dicts from GitHub so the
    caller can serve them without a second round trip.
    """
    try:
        repos = await list_installation_repositories_via_app(row.github_installation_id)
    except Exception as exc:
        raise RepositoryListingError(str(exc)) from exc
    ids = [int(r["id"]) for r in repos if r.get("id") is not None]
    previous = {int(i) for i in (row.authorized_repository_ids or [])}
    row.authorized_repository_ids = ids
    row.authorized_repositories = [
        {"id": int(r["id"]), "full_name": str(r.get("full_name") or "")}
        for r in repos
        if r.get("id") is not None
    ]
    if set(ids) != previous:
        # The cached token was minted for the old repository set; drop it so
        # the next get_valid_token re-mints with the new scope instead of
        # serving a token that 404s on repositories added since.
        row.access_token_enc = None
        row.token_expires_at = None
    row.updated_at = time.time()
    await session.commit()
    logger.info(
        "Installation %s (%s): repository scope refreshed, %d repositories",
        row.github_installation_id, row.github_account_login, len(ids),
    )
    return repos


async def get_rows_by_github_id(
    session: AsyncSession, github_installation_id: int
) -> list[GatewayGitHubInstallation]:
    result = await session.execute(
        select(GatewayGitHubInstallation).where(
            GatewayGitHubInstallation.github_installation_id == github_installation_id
        )
    )
    return list(result.scalars().all())


async def active_claim_owners(session: AsyncSession, github_installation_id: int) -> list[str]:
    """Orgs that currently hold a non-disconnected row for this installation."""
    owners: list[str] = []
    for row in await get_rows_by_github_id(session, github_installation_id):
        if row.status != "disconnected" and row.org_id not in owners:
            owners.append(row.org_id)
    return owners


async def active_claim_owner(session: AsyncSession, github_installation_id: int) -> str | None:
    """Org that currently holds an active row for this installation, if any."""
    owners = await active_claim_owners(session, github_installation_id)
    return owners[0] if owners else None


async def complete_installation(
    session: AsyncSession,
    *,
    org_id: str,
    github_installation_id: int,
    created_by: str | None = None,
) -> GitHubInstallationInfo:
    """Create or refresh the org's row for a GitHub installation.

    1. Verify the installation exists via the app JWT; capture account and
       permissions.
    2. Refuse when a different org already holds it (tenancy boundary).
    3. List the installation's repositories through the app; that list is
       the token scope.
    4. Mint a repository-scoped token when there are repositories (local
       mode falls back to an installation-wide token, as before).
    5. Upsert the row.
    """
    from ..github_client import (
        create_installation_token,
        create_unrestricted_installation_token,
        get_installation_details,
    )
    from ..runtime.mode import is_cloud_mode
    from ..store import github as gh_store
    from ..store.crypto import _encrypt

    app_jwt = _app_jwt()
    try:
        details = await get_installation_details(app_jwt, github_installation_id)
    except Exception as exc:
        raise InstallationNotFoundError(str(exc)) from exc

    owner = await active_claim_owner(session, github_installation_id)
    if owner is not None and owner != org_id:
        logger.warning(
            "GitHub installation %s is claimed by org %s; refusing claim for org %s",
            github_installation_id, owner, org_id,
        )
        raise InstallationClaimedError(f"installation {github_installation_id} belongs to another org")

    try:
        repos = await list_installation_repositories_via_app(github_installation_id)
    except Exception as exc:
        raise RepositoryListingError(str(exc)) from exc
    repo_ids = [int(r["id"]) for r in repos if r.get("id") is not None]
    repo_list = [
        {"id": int(r["id"]), "full_name": str(r.get("full_name") or "")}
        for r in repos
        if r.get("id") is not None
    ]

    access_token_enc: bytes | None = None
    token_expires_at: float | None = None
    if repo_ids:
        token_data = await create_installation_token(app_jwt, github_installation_id, repository_ids=repo_ids)
        access_token_enc = _encrypt(token_data["token"])
        token_expires_at = _expires_at(token_data)
    elif not is_cloud_mode():
        token_data = await create_unrestricted_installation_token(app_jwt, github_installation_id)
        access_token_enc = _encrypt(token_data["token"])
        token_expires_at = _expires_at(token_data)

    account = details.get("account") or {}
    info = await gh_store.upsert_installation(
        session,
        org_id=org_id,
        github_installation_id=github_installation_id,
        github_account_login=account.get("login", "unknown"),
        github_account_type=account.get("type", "User"),
        access_token_enc=access_token_enc,
        token_expires_at=token_expires_at,
        permissions=details.get("permissions"),
        created_by=created_by,
        authorized_repository_ids=repo_ids,
        authorized_repositories=repo_list,
    )
    logger.info(
        "GitHub App installation %s (%s) linked to org %s with %d repositories",
        github_installation_id, info.github_account_login, org_id, len(repo_ids),
    )
    return info


async def discover_installations_for_account(
    session: AsyncSession, *, org_id: str, account_login: str, created_by: str | None = None
) -> list[GitHubInstallationInfo]:
    """Link every unclaimed installation of the app on *account_login* to *org_id*.

    Repair path for a lost redirect. Raises InstallationNotFoundError when the
    account has no installation, InstallationClaimedError when every match is
    owned by another org.
    """
    from ..github_client import list_app_installations

    wanted = account_login.strip().lower()
    if not wanted:
        raise InstallationNotFoundError("account login is empty")
    matches = [
        inst
        for inst in await list_app_installations(_app_jwt())
        if str((inst.get("account") or {}).get("login", "")).lower() == wanted
    ]
    if not matches:
        raise InstallationNotFoundError(f"no installation for account {account_login}")

    linked: list[GitHubInstallationInfo] = []
    claimed = 0
    for inst in matches:
        try:
            linked.append(
                await complete_installation(
                    session,
                    org_id=org_id,
                    github_installation_id=int(inst["id"]),
                    created_by=created_by,
                )
            )
        except InstallationClaimedError:
            claimed += 1
    if not linked and claimed:
        raise InstallationClaimedError(f"installation for {account_login} belongs to another org")
    return linked


_INSTALLATION_STATUS_BY_ACTION = {
    "created": "active",
    "unsuspend": "active",
    "suspend": "suspended",
    "deleted": "disconnected",
}


async def apply_installation_webhook(
    session: AsyncSession,
    *,
    event: str,
    action: str,
    github_installation_id: int,
    permissions: dict | None = None,
) -> dict:
    """Apply an ``installation`` / ``installation_repositories`` delivery.

    Only rows created by the browser flow are touched; a delivery for an
    unknown installation is ignored (never creates a row, which would let a
    webhook claim an installation for an org).
    """
    rows = [
        r for r in await get_rows_by_github_id(session, github_installation_id)
        if r.status != "disconnected"
    ]
    if not rows:
        return {"ignored": "installation not linked", "installation_id": github_installation_id}

    updated: list[str] = []
    refreshed: list[str] = []
    for row in rows:
        if event == "installation":
            status = _INSTALLATION_STATUS_BY_ACTION.get(action)
            if status is not None:
                row.status = status
                row.updated_at = time.time()
                updated.append(row.id)
            if action == "new_permissions_accepted" and permissions is not None:
                row.permissions = permissions
                row.updated_at = time.time()
                updated.append(row.id)
            await session.commit()
            if action in ("created", "unsuspend", "new_permissions_accepted"):
                try:
                    await refresh_installation_repositories(session, row)
                    refreshed.append(row.id)
                except RepositoryListingError as exc:
                    logger.warning("installation webhook: refresh failed for %s: %s", row.id, exc)
        elif event == "installation_repositories" and action in ("added", "removed"):
            if row.status != "active":
                continue
            try:
                await refresh_installation_repositories(session, row)
                refreshed.append(row.id)
            except RepositoryListingError as exc:
                logger.warning("installation_repositories webhook: refresh failed for %s: %s", row.id, exc)
    return {"updated": updated, "refreshed": refreshed}
