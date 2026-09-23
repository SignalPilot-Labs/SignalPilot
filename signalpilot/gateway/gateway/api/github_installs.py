"""GitHub App installation maintenance endpoints (split from api/github.py).

Mounted by ``api/github.py`` via ``router.include_router``.

- POST /api/github/installations/{id}/refresh: re-list the installation's
  repositories through the app and update the stored token scope.
- POST /api/github/installations/discover?account=<login>: admin repair path
  when the install redirect was lost. Links the app's installations on that
  GitHub account to the calling org, but only when no other org holds them.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from ..auth import OrgAdmin
from ..models.github import GitHubInstallationInfo
from ..security.scope_guard import RequireScope
from .deps import StoreD

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/api/github/installations/{installation_id}/refresh",
    response_model=GitHubInstallationInfo,
    dependencies=[RequireScope("write")],
)
async def refresh_installation(installation_id: str, store: StoreD):
    from ..store import github as gh_store
    from ..store.github_installs import RepositoryListingError, refresh_installation_repositories

    org_id = store.org_id or "local"
    row = await gh_store.get_installation(store.session, org_id=org_id, installation_id=installation_id)
    if not row:
        raise HTTPException(status_code=404, detail="Installation not found")
    try:
        await refresh_installation_repositories(store.session, row)
    except RepositoryListingError as exc:
        raise HTTPException(status_code=502, detail=f"Could not list installation repositories: {exc}")
    return gh_store._installation_to_info(row)


@router.post(
    "/api/github/installations/discover",
    response_model=list[GitHubInstallationInfo],
    dependencies=[RequireScope("admin")],
)
async def discover_installations(
    store: StoreD,
    _role: OrgAdmin,
    account: str = Query(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9-]*$"),
):
    """Link existing installations of the app on *account* to this org.

    Org-admin only (Clerk org:admin role, plus admin scope): it binds a GitHub
    account's installation to the tenant without the GitHub redirect. An
    installation already claimed by another org is never moved (409).
    """
    from ..config.github import get_github_settings
    from ..store.github_installs import (
        InstallationClaimedError,
        InstallationNotFoundError,
        RepositoryListingError,
        discover_installations_for_account,
    )

    if not get_github_settings().is_configured:
        raise HTTPException(status_code=503, detail="GitHub App not configured")
    org_id = store.org_id or "local"
    try:
        linked = await discover_installations_for_account(
            store.session, org_id=org_id, account_login=account, created_by=store.user_id
        )
    except InstallationNotFoundError:
        raise HTTPException(status_code=404, detail=f"No installation of the GitHub App found for account {account!r}")
    except InstallationClaimedError:
        raise HTTPException(
            status_code=409,
            detail="This GitHub installation is already claimed by a different organization",
        )
    except RepositoryListingError as exc:
        raise HTTPException(status_code=502, detail=f"Could not list installation repositories: {exc}")
    logger.info("GitHub installations discovered for org=%s account=%s: %d", org_id, account, len(linked))
    return linked
