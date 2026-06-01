"""Store operations for GitHub App installations and repo links."""

from __future__ import annotations

import logging
import time

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import GatewayGitHubInstallation, GatewayGitHubRepoLink, GatewayWorkspaceProject
from ..models.github import GitHubInstallationInfo, GitHubRepoLinkInfo
from . import workspace_projects as _wp

logger = logging.getLogger(__name__)


class ProjectNotFoundError(Exception):
    """Project does not exist in the caller's org. Fail-closed for IDOR."""


async def _assert_project_in_org(session: AsyncSession, *, org_id: str, project_id: str) -> None:
    proj = await _wp.get_project(session, org_id=org_id, project_id=project_id)
    if proj is None:
        raise ProjectNotFoundError(project_id)


def _installation_to_info(row: GatewayGitHubInstallation) -> GitHubInstallationInfo:
    return GitHubInstallationInfo(
        id=row.id,
        org_id=row.org_id,
        github_installation_id=row.github_installation_id,
        github_account_login=row.github_account_login,
        github_account_type=row.github_account_type,
        permissions=row.permissions,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _link_to_info(row: GatewayGitHubRepoLink) -> GitHubRepoLinkInfo:
    return GitHubRepoLinkInfo(
        id=row.id,
        org_id=row.org_id,
        project_id=row.project_id,
        installation_id=row.installation_id,
        repo_full_name=row.repo_full_name,
        repo_id=row.repo_id,
        default_branch=row.default_branch,
        status=row.status,
        last_sync_at=row.last_sync_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def upsert_installation(
    session: AsyncSession,
    *,
    org_id: str,
    github_installation_id: int,
    github_account_login: str,
    github_account_type: str,
    access_token_enc: bytes,
    token_expires_at: float,
    permissions: dict | None = None,
    created_by: str | None = None,
) -> GitHubInstallationInfo:
    now = time.time()
    result = await session.execute(
        select(GatewayGitHubInstallation).where(
            GatewayGitHubInstallation.org_id == org_id,
            GatewayGitHubInstallation.github_installation_id == github_installation_id,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.github_account_login = github_account_login
        existing.github_account_type = github_account_type
        existing.access_token_enc = access_token_enc
        existing.token_expires_at = token_expires_at
        existing.permissions = permissions
        existing.status = "active"
        existing.updated_at = now
        await session.commit()
        return _installation_to_info(existing)

    row = GatewayGitHubInstallation(
        org_id=org_id,
        github_installation_id=github_installation_id,
        github_account_login=github_account_login,
        github_account_type=github_account_type,
        access_token_enc=access_token_enc,
        token_expires_at=token_expires_at,
        permissions=permissions,
        status="active",
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()
    return _installation_to_info(row)


async def list_installations(session: AsyncSession, *, org_id: str) -> list[GitHubInstallationInfo]:
    result = await session.execute(
        select(GatewayGitHubInstallation)
        .where(GatewayGitHubInstallation.org_id == org_id, GatewayGitHubInstallation.status == "active")
        .order_by(GatewayGitHubInstallation.created_at.desc())
    )
    return [_installation_to_info(r) for r in result.scalars().all()]


async def get_installation(session: AsyncSession, *, org_id: str, installation_id: str) -> GatewayGitHubInstallation | None:
    result = await session.execute(
        select(GatewayGitHubInstallation).where(
            GatewayGitHubInstallation.id == installation_id,
            GatewayGitHubInstallation.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def delete_installation(session: AsyncSession, *, org_id: str, installation_id: str) -> bool:
    result = await session.execute(
        select(GatewayGitHubInstallation).where(
            GatewayGitHubInstallation.id == installation_id,
            GatewayGitHubInstallation.org_id == org_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return False
    row.status = "disconnected"
    row.updated_at = time.time()
    await session.commit()
    return True


async def get_valid_token(session: AsyncSession, row: GatewayGitHubInstallation) -> str:
    from ..config.github import get_github_settings
    from ..github_client import create_installation_token, generate_app_jwt
    from ..store.crypto import _decrypt_with_migration, _encrypt

    if not row.access_token_enc:
        raise ValueError("Installation has no stored token")

    token, needs_migration = _decrypt_with_migration(row.access_token_enc)
    if needs_migration:
        row.access_token_enc = _encrypt(token)
        row.updated_at = time.time()
        await session.commit()
    if row.token_expires_at and row.token_expires_at > time.time() + 300:
        return token

    settings = get_github_settings()
    app_jwt = generate_app_jwt(settings.sp_github_app_id, settings.sp_github_app_private_key)
    result = await create_installation_token(app_jwt, row.github_installation_id)

    new_token = result["token"]
    from datetime import datetime
    expires_str = result.get("expires_at", "")
    if expires_str:
        expires_at = datetime.fromisoformat(expires_str.replace("Z", "+00:00")).timestamp()
    else:
        expires_at = time.time() + 3600

    row.access_token_enc = _encrypt(new_token)
    row.token_expires_at = expires_at
    row.updated_at = time.time()
    await session.commit()

    logger.info("Refreshed GitHub installation token for %s", row.github_account_login)
    return new_token


# ─── Repo Links ──────────────────────────────────────────────────────────


async def create_repo_link(
    session: AsyncSession,
    *,
    org_id: str,
    project_id: str,
    installation_id: str,
    repo_full_name: str,
    repo_id: int,
    default_branch: str = "main",
) -> GitHubRepoLinkInfo:
    await _assert_project_in_org(session, org_id=org_id, project_id=project_id)
    now = time.time()
    row = GatewayGitHubRepoLink(
        org_id=org_id,
        project_id=project_id,
        installation_id=installation_id,
        repo_full_name=repo_full_name,
        repo_id=repo_id,
        default_branch=default_branch,
        status="active",
        created_at=now,
        updated_at=now,
    )
    session.add(row)

    await session.execute(
        update(GatewayWorkspaceProject)
        .where(GatewayWorkspaceProject.id == project_id, GatewayWorkspaceProject.org_id == org_id)
        .values(source="github", git_remote=f"https://github.com/{repo_full_name}.git", updated_at=now)
    )
    await session.commit()
    return _link_to_info(row)


async def list_repo_links(session: AsyncSession, *, org_id: str, project_id: str | None = None) -> list[GitHubRepoLinkInfo]:
    q = select(GatewayGitHubRepoLink).where(
        GatewayGitHubRepoLink.org_id == org_id,
        GatewayGitHubRepoLink.status == "active",
    )
    if project_id:
        q = q.where(GatewayGitHubRepoLink.project_id == project_id)
    result = await session.execute(q.order_by(GatewayGitHubRepoLink.created_at.desc()))
    return [_link_to_info(r) for r in result.scalars().all()]


async def get_repo_link_for_project(session: AsyncSession, *, org_id: str, project_id: str) -> GatewayGitHubRepoLink | None:
    result = await session.execute(
        select(GatewayGitHubRepoLink).where(
            GatewayGitHubRepoLink.org_id == org_id,
            GatewayGitHubRepoLink.project_id == project_id,
            GatewayGitHubRepoLink.status == "active",
        )
    )
    return result.scalar_one_or_none()


async def delete_repo_link(session: AsyncSession, *, org_id: str, link_id: str) -> bool:
    result = await session.execute(
        select(GatewayGitHubRepoLink).where(
            GatewayGitHubRepoLink.id == link_id,
            GatewayGitHubRepoLink.org_id == org_id,
        )
    )
    link = result.scalar_one_or_none()
    if not link:
        return False

    now = time.time()
    link.status = "disconnected"
    link.updated_at = now

    await session.execute(
        update(GatewayWorkspaceProject)
        .where(GatewayWorkspaceProject.id == link.project_id, GatewayWorkspaceProject.org_id == org_id)
        .values(source="managed", git_remote=None, updated_at=now)
    )
    await session.commit()
    return True
