"""Persistence and authorization for private immutable dashboards."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.dashboard.domain import DashboardDefinition, dashboard_content_hash, normalize_dashboard_definition
from gateway.db.models import GatewayDashboard, GatewayDashboardVersion
from gateway.models.dashboards import (
    DashboardDetail,
    DashboardListItem,
    DashboardVersionInfo,
)


class DashboardNotFoundError(LookupError):
    pass


class DashboardValidationError(ValueError):
    pass


@dataclass(frozen=True)
class DashboardConflictError(RuntimeError):
    dashboard_id: str
    actual_current_version_id: str


def _list_item(row: GatewayDashboard) -> DashboardListItem:
    if not row.current_version_id:
        raise DashboardValidationError("Dashboard has no current version")
    return DashboardListItem(
        id=row.id,
        name=row.name,
        description=row.description,
        project_id=row.project_id,
        connection_name=row.connection_name,
        timezone=row.timezone,
        current_version_id=row.current_version_id,
        revision=row.revision,
        updated_at=row.updated_at,
    )


def _version_info(row: GatewayDashboardVersion) -> DashboardVersionInfo:
    return DashboardVersionInfo(
        id=row.id,
        ordinal=row.ordinal,
        content_hash=row.content_hash,
        commit_sha=row.commit_sha,
        semantic_fingerprint=row.semantic_fingerprint,
        created_at=row.created_at,
        definition=DashboardDefinition.model_validate(row.definition_json),
    )


async def list_private_dashboards(
    db: AsyncSession, *, org_id: str, user_id: str
) -> list[DashboardListItem]:
    rows = list((await db.execute(
        select(GatewayDashboard).where(
            GatewayDashboard.org_id == org_id,
            GatewayDashboard.owner_user_id == user_id,
            GatewayDashboard.archived_at.is_(None),
        ).order_by(GatewayDashboard.updated_at.desc())
    )).scalars())
    return [_list_item(row) for row in rows]


async def get_private_dashboard_rows(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    dashboard_id: str,
    version_id: str | None = None,
) -> tuple[GatewayDashboard, GatewayDashboardVersion] | None:
    dashboard = (await db.execute(select(GatewayDashboard).where(
        GatewayDashboard.id == dashboard_id,
        GatewayDashboard.org_id == org_id,
        GatewayDashboard.owner_user_id == user_id,
        GatewayDashboard.archived_at.is_(None),
    ))).scalar_one_or_none()
    if dashboard is None:
        return None
    selected_version_id = version_id or dashboard.current_version_id
    version = (await db.execute(select(GatewayDashboardVersion).where(
        GatewayDashboardVersion.id == selected_version_id,
        GatewayDashboardVersion.dashboard_id == dashboard.id,
        GatewayDashboardVersion.org_id == org_id,
        GatewayDashboardVersion.owner_user_id == user_id,
    ))).scalar_one_or_none()
    return (dashboard, version) if version is not None else None


async def get_private_dashboard(
    db: AsyncSession, *, org_id: str, user_id: str, dashboard_id: str, version_id: str | None = None
) -> DashboardDetail | None:
    rows = await get_private_dashboard_rows(
        db, org_id=org_id, user_id=user_id, dashboard_id=dashboard_id, version_id=version_id
    )
    if rows is None:
        return None
    dashboard, version = rows
    return DashboardDetail(dashboard=_list_item(dashboard), version=_version_info(version))


async def create_private_dashboard(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    definition: DashboardDefinition,
) -> DashboardDetail:
    dashboard_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    signalpilot = definition.signalPilot.model_copy(update={"dashboardId": dashboard_id})
    definition = definition.model_copy(update={"signalPilot": signalpilot})
    normalized = normalize_dashboard_definition(definition)
    dashboard = GatewayDashboard(
        id=dashboard_id,
        org_id=org_id,
        owner_user_id=user_id,
        project_id=signalpilot.projectId,
        connection_name=signalpilot.connectionName,
        name=definition.name,
        description=definition.description,
        timezone=signalpilot.timezone,
        current_version_id=version_id,
    )
    version = GatewayDashboardVersion(
        id=version_id,
        dashboard_id=dashboard_id,
        org_id=org_id,
        owner_user_id=user_id,
        ordinal=1,
        definition_json=normalized,
        content_hash=dashboard_content_hash(definition),
        project_id=signalpilot.projectId,
        commit_sha=signalpilot.commitSha,
        semantic_fingerprint=signalpilot.semanticFingerprint,
        connection_name=signalpilot.connectionName,
    )
    db.add_all([dashboard, version])
    await db.commit()
    await db.refresh(dashboard)
    await db.refresh(version)
    return DashboardDetail(dashboard=_list_item(dashboard), version=_version_info(version))


async def create_dashboard_version(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    dashboard_id: str,
    expected_current_version_id: str,
    definition: DashboardDefinition,
) -> DashboardDetail:
    rows = await get_private_dashboard_rows(db, org_id=org_id, user_id=user_id, dashboard_id=dashboard_id)
    if rows is None:
        raise DashboardNotFoundError
    dashboard, current = rows
    if dashboard.current_version_id != expected_current_version_id:
        raise DashboardConflictError(dashboard.id, dashboard.current_version_id or "")
    binding = definition.signalPilot
    if binding.dashboardId != dashboard.id:
        raise DashboardValidationError("Dashboard definition identity cannot change")
    if (
        binding.projectId != dashboard.project_id
        or binding.connectionName != dashboard.connection_name
        or binding.timezone != dashboard.timezone
    ):
        raise DashboardValidationError("Project, connection, and timezone bindings cannot change")
    content_hash = dashboard_content_hash(definition)
    if content_hash == current.content_hash:
        raise DashboardValidationError("Dashboard definition is unchanged")
    version = GatewayDashboardVersion(
        id=str(uuid.uuid4()),
        dashboard_id=dashboard.id,
        org_id=org_id,
        owner_user_id=user_id,
        ordinal=current.ordinal + 1,
        definition_json=normalize_dashboard_definition(definition),
        content_hash=content_hash,
        project_id=binding.projectId,
        commit_sha=binding.commitSha,
        semantic_fingerprint=binding.semanticFingerprint,
        connection_name=binding.connectionName,
    )
    db.add(version)
    dashboard.current_version_id = version.id
    dashboard.revision += 1
    dashboard.name = definition.name
    dashboard.description = definition.description
    dashboard.updated_at = datetime.now(UTC)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise DashboardConflictError(dashboard.id, dashboard.current_version_id or "") from exc
    await db.refresh(dashboard)
    await db.refresh(version)
    return DashboardDetail(dashboard=_list_item(dashboard), version=_version_info(version))
