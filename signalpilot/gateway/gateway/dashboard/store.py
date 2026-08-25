"""Persistence and authorization for private immutable dashboards."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.dashboard.confidence import dashboard_confidence_counts
from gateway.dashboard.domain import DashboardDefinition, dashboard_content_hash, normalize_dashboard_definition
from gateway.db.models import (
    GatewayDashboard,
    GatewayDashboardAuthoringSession,
    GatewayDashboardResult,
    GatewayDashboardVersion,
)
from gateway.models.dashboards import (
    DashboardAuthoringSessionInfo,
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


def _confidence_counts(version: GatewayDashboardVersion | None) -> tuple[int, int]:
    if version is None:
        return 0, 0
    definition = DashboardDefinition.model_validate(version.definition_json)
    return dashboard_confidence_counts(definition)


def _list_item(
    row: GatewayDashboard,
    *,
    viewer_user_id: str,
    version: GatewayDashboardVersion | None = None,
) -> DashboardListItem:
    if not row.current_version_id:
        raise DashboardValidationError("Dashboard has no current version")
    high, low = _confidence_counts(version)
    return DashboardListItem(
        id=row.id,
        name=row.name,
        description=row.description,
        project_id=row.project_id,
        connection_name=row.connection_name,
        timezone=row.timezone,
        current_version_id=row.current_version_id,
        revision=row.revision,
        visibility=row.visibility,
        owner_user_id=row.owner_user_id,
        is_owner=row.owner_user_id == viewer_user_id,
        archived_at=row.archived_at,
        parent_dashboard_id=row.parent_dashboard_id,
        parent_version_id=row.parent_version_id,
        high_confidence_charts=high,
        low_confidence_charts=low,
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
        authoring_provenance=dict(row.authoring_provenance_json or {}),
    )


def _authoring_info(row: GatewayDashboardAuthoringSession) -> DashboardAuthoringSessionInfo:
    definition = DashboardDefinition.model_validate(row.definition_json)
    return DashboardAuthoringSessionInfo(
        id=row.id,
        thread_id=row.thread_id,
        dashboard_id=row.dashboard_id,
        base_version_id=row.base_version_id,
        definition=definition,
        operations=list(row.operations_json or []),
        summary=row.summary,
        agent_run_id=row.agent_run_id,
        model=row.model,
        status=row.status,
        requires_custom_sql_confirmation=row.requires_custom_sql_confirmation,
        custom_sql_confirmed=row.custom_sql_confirmed,
        custom_sql_chart_ids=list(row.pending_custom_sql_chart_ids_json or []),
        draft_revision=row.draft_revision,
        events=list(row.events_json or []),
        created_at=row.created_at,
        updated_at=row.updated_at or row.created_at,
    )


def authoring_info(row: GatewayDashboardAuthoringSession) -> DashboardAuthoringSessionInfo:
    return _authoring_info(row)


def _authoring_event(
    events: list[dict],
    *,
    kind: str,
    message: str,
    status: str = "info",
    metadata: dict | None = None,
) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "sequence": len(events) + 1,
        "kind": kind,
        "status": status,
        "message": message,
        "created_at": datetime.now(UTC).isoformat(),
        "metadata": metadata or {},
    }


async def list_dashboards(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    scope: str = "mine",
    search: str | None = None,
    include_archived: bool = False,
) -> list[DashboardListItem]:
    visibility_clause = (
        GatewayDashboard.owner_user_id == user_id if scope == "mine" else GatewayDashboard.visibility == "organization"
    )
    conditions = [GatewayDashboard.org_id == org_id, visibility_clause]
    if not include_archived or scope != "mine":
        conditions.append(GatewayDashboard.archived_at.is_(None))
    if search:
        escaped = search.replace("%", r"\%").replace("_", r"\_")
        conditions.append(
            or_(
                GatewayDashboard.name.ilike(f"%{escaped}%", escape="\\"),
                GatewayDashboard.description.ilike(f"%{escaped}%", escape="\\"),
            )
        )
    rows = (
        await db.execute(
            select(GatewayDashboard, GatewayDashboardVersion)
            .outerjoin(GatewayDashboardVersion, GatewayDashboardVersion.id == GatewayDashboard.current_version_id)
            .where(*conditions)
            .order_by(GatewayDashboard.updated_at.desc())
        )
    ).all()
    return [_list_item(row, viewer_user_id=user_id, version=version) for row, version in rows]


async def list_private_dashboards(db: AsyncSession, *, org_id: str, user_id: str) -> list[DashboardListItem]:
    return await list_dashboards(db, org_id=org_id, user_id=user_id)


async def get_private_dashboard_rows(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    dashboard_id: str,
    version_id: str | None = None,
) -> tuple[GatewayDashboard, GatewayDashboardVersion] | None:
    return await get_dashboard_rows(
        db,
        org_id=org_id,
        user_id=user_id,
        dashboard_id=dashboard_id,
        version_id=version_id,
        require_owner=True,
    )


async def get_dashboard_rows(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    dashboard_id: str,
    version_id: str | None = None,
    require_owner: bool = False,
    include_archived: bool = False,
) -> tuple[GatewayDashboard, GatewayDashboardVersion] | None:
    access = GatewayDashboard.owner_user_id == user_id
    if not require_owner:
        access = or_(access, GatewayDashboard.visibility == "organization")
    conditions = [
        GatewayDashboard.id == dashboard_id,
        GatewayDashboard.org_id == org_id,
        access,
    ]
    if not include_archived:
        conditions.append(GatewayDashboard.archived_at.is_(None))
    dashboard = (
        await db.execute(
            select(GatewayDashboard).where(
                *conditions,
            )
        )
    ).scalar_one_or_none()
    if dashboard is None:
        return None
    selected_version_id = version_id or dashboard.current_version_id
    version = (
        await db.execute(
            select(GatewayDashboardVersion).where(
                GatewayDashboardVersion.id == selected_version_id,
                GatewayDashboardVersion.dashboard_id == dashboard.id,
                GatewayDashboardVersion.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
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
    return DashboardDetail(
        dashboard=_list_item(dashboard, viewer_user_id=user_id, version=version),
        version=_version_info(version),
    )


async def get_dashboard(
    db: AsyncSession, *, org_id: str, user_id: str, dashboard_id: str, version_id: str | None = None
) -> DashboardDetail | None:
    rows = await get_dashboard_rows(
        db, org_id=org_id, user_id=user_id, dashboard_id=dashboard_id, version_id=version_id
    )
    if rows is None:
        return None
    dashboard, version = rows
    return DashboardDetail(
        dashboard=_list_item(dashboard, viewer_user_id=user_id, version=version),
        version=_version_info(version),
    )


async def create_private_dashboard(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    definition: DashboardDefinition,
    authoring_provenance: dict | None = None,
    parent_dashboard_id: str | None = None,
    parent_version_id: str | None = None,
) -> DashboardDetail:
    dashboard_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    binding_update = {"dashboardId": dashboard_id}
    if parent_version_id:
        binding_update["forkedFromVersionId"] = parent_version_id
    signalpilot = definition.signalPilot.model_copy(update=binding_update)
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
        visibility="private",
        parent_dashboard_id=parent_dashboard_id,
        parent_version_id=parent_version_id,
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
        authoring_provenance_json=authoring_provenance or {},
    )
    db.add_all([dashboard, version])
    await db.commit()
    await db.refresh(dashboard)
    await db.refresh(version)
    return DashboardDetail(
        dashboard=_list_item(dashboard, viewer_user_id=user_id, version=version), version=_version_info(version)
    )


async def create_dashboard_version(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    dashboard_id: str,
    expected_current_version_id: str,
    definition: DashboardDefinition,
    authoring_provenance: dict | None = None,
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
        authoring_provenance_json=authoring_provenance or {},
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
    return DashboardDetail(
        dashboard=_list_item(dashboard, viewer_user_id=user_id, version=version), version=_version_info(version)
    )


async def set_dashboard_visibility(
    db: AsyncSession, *, org_id: str, user_id: str, dashboard_id: str, visibility: str
) -> DashboardDetail:
    rows = await get_dashboard_rows(db, org_id=org_id, user_id=user_id, dashboard_id=dashboard_id, require_owner=True)
    if rows is None:
        raise DashboardNotFoundError
    dashboard, version = rows
    dashboard.visibility = visibility
    dashboard.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(dashboard)
    return DashboardDetail(
        dashboard=_list_item(dashboard, viewer_user_id=user_id, version=version), version=_version_info(version)
    )


async def fork_dashboard(
    db: AsyncSession, *, org_id: str, user_id: str, dashboard_id: str, version_id: str
) -> DashboardDetail:
    rows = await get_dashboard_rows(
        db, org_id=org_id, user_id=user_id, dashboard_id=dashboard_id, version_id=version_id
    )
    if rows is None:
        raise DashboardNotFoundError
    source, version = rows
    definition = DashboardDefinition.model_validate(version.definition_json)
    return await create_private_dashboard(
        db,
        org_id=org_id,
        user_id=user_id,
        definition=definition.model_copy(update={"name": f"{definition.name} (fork)"}),
        authoring_provenance={"forked_from_dashboard_id": source.id, "forked_from_version_id": version.id},
        parent_dashboard_id=source.id,
        parent_version_id=version.id,
    )


async def set_dashboard_archived(
    db: AsyncSession, *, org_id: str, user_id: str, dashboard_id: str, archived: bool
) -> DashboardDetail:
    rows = await get_dashboard_rows(
        db,
        org_id=org_id,
        user_id=user_id,
        dashboard_id=dashboard_id,
        require_owner=True,
        include_archived=True,
    )
    if rows is None:
        raise DashboardNotFoundError
    dashboard, version = rows
    dashboard.archived_at = datetime.now(UTC) if archived else None
    dashboard.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(dashboard)
    return DashboardDetail(
        dashboard=_list_item(dashboard, viewer_user_id=user_id, version=version), version=_version_info(version)
    )


async def create_authoring_session(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    dashboard_id: str | None,
    base_version_id: str | None,
    definition: DashboardDefinition,
    operations: list[dict],
    prompt: str,
    summary: str,
    agent_run_id: str,
    model: str,
    requires_custom_sql_confirmation: bool,
    custom_sql_confirmed: bool,
    thread_id: str | None = None,
    prior_events: list[dict] | None = None,
    pending_custom_sql_chart_ids: list[str] | None = None,
) -> DashboardAuthoringSessionInfo:
    binding = definition.signalPilot
    now = datetime.now(UTC)
    run = {"id": agent_run_id, "model": model, "draft_revision": 1, "created_at": now.isoformat()}
    events = list(prior_events or [])
    if prior_events:
        events.append(
            _authoring_event(
                events,
                kind="system",
                status="success",
                message="Started a new governed draft from the latest saved dashboard version",
            )
        )
    events.append(_authoring_event(events, kind="user", message=prompt))
    events.append(
        _authoring_event(events, kind="progress", status="success", message="Resolved governed semantic context")
    )
    events.append(
        _authoring_event(events, kind="validation", status="success", message="Validated the complete dashboard draft")
    )
    events.append(_authoring_event(events, kind="assistant", status="success", message=summary))
    row = GatewayDashboardAuthoringSession(
        id=str(uuid.uuid4()),
        thread_id=thread_id or str(uuid.uuid4()),
        dashboard_id=dashboard_id,
        base_version_id=base_version_id,
        org_id=org_id,
        owner_user_id=user_id,
        project_id=binding.projectId,
        connection_name=binding.connectionName,
        commit_sha=binding.commitSha,
        semantic_fingerprint=binding.semanticFingerprint,
        prompt=prompt,
        definition_json=normalize_dashboard_definition(definition),
        operations_json=operations,
        events_json=events,
        agent_runs_json=[run],
        confirmations_json=[],
        pending_custom_sql_chart_ids_json=(
            pending_custom_sql_chart_ids
            if pending_custom_sql_chart_ids is not None
            else [chart.id for chart in definition.charts if chart.query.kind == "sql"]
            if requires_custom_sql_confirmation and not custom_sql_confirmed
            else []
        ),
        draft_revision=1,
        summary=summary,
        agent_run_id=agent_run_id,
        model=model,
        requires_custom_sql_confirmation=requires_custom_sql_confirmation,
        custom_sql_confirmed=custom_sql_confirmed,
        updated_at=now,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _authoring_info(row)


async def update_authoring_session_draft(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    session_id: str,
    definition: DashboardDefinition,
    operations: list[dict],
    prompt: str,
    summary: str,
    agent_run_id: str,
    model: str,
    requires_custom_sql_confirmation: bool,
    pending_custom_sql_chart_ids: list[str],
) -> DashboardAuthoringSessionInfo:
    session = await get_authoring_session(db, org_id=org_id, user_id=user_id, session_id=session_id)
    if session is None:
        raise DashboardNotFoundError
    if session.status != "preview":
        raise DashboardValidationError("Authoring conversation is no longer active")
    events = list(session.events_json or [])
    events.append(_authoring_event(events, kind="user", message=prompt))
    events.append(
        _authoring_event(
            events, kind="progress", status="success", message="Applied typed operations to the current draft"
        )
    )
    events.append(
        _authoring_event(events, kind="validation", status="success", message="Validated the updated governed preview")
    )
    events.append(_authoring_event(events, kind="assistant", status="success", message=summary))
    revision = session.draft_revision + 1
    runs = list(session.agent_runs_json or [])
    runs.append(
        {"id": agent_run_id, "model": model, "draft_revision": revision, "created_at": datetime.now(UTC).isoformat()}
    )
    session.definition_json = normalize_dashboard_definition(definition)
    session.operations_json = operations
    session.prompt = prompt
    session.summary = summary
    session.agent_run_id = agent_run_id
    session.model = model
    session.events_json = events
    session.agent_runs_json = runs
    session.draft_revision = revision
    session.requires_custom_sql_confirmation = requires_custom_sql_confirmation
    has_custom_sql = any(chart.query.kind == "sql" for chart in definition.charts)
    session.custom_sql_confirmed = (
        False if requires_custom_sql_confirmation else session.custom_sql_confirmed if has_custom_sql else False
    )
    session.pending_custom_sql_chart_ids_json = pending_custom_sql_chart_ids
    session.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(session)
    return _authoring_info(session)


async def record_authoring_failure(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    session_id: str,
    prompt: str,
    safe_message: str,
) -> None:
    session = await get_authoring_session(db, org_id=org_id, user_id=user_id, session_id=session_id)
    if session is None or session.status not in {"preview", "applied", "discarded"}:
        return
    events = list(session.events_json or [])
    events.append(_authoring_event(events, kind="user", message=prompt))
    events.append(_authoring_event(events, kind="validation", status="error", message=safe_message))
    session.events_json = events
    session.updated_at = datetime.now(UTC)
    await db.commit()


async def discard_authoring_session(
    db: AsyncSession, *, org_id: str, user_id: str, session_id: str
) -> DashboardAuthoringSessionInfo:
    session = await get_authoring_session(db, org_id=org_id, user_id=user_id, session_id=session_id)
    if session is None:
        raise DashboardNotFoundError
    if session.status != "preview":
        raise DashboardValidationError("Authoring conversation is no longer active")
    events = list(session.events_json or [])
    events.append(
        _authoring_event(events, kind="system", status="success", message="Draft discarded; saved dashboard unchanged")
    )
    session.events_json = events
    session.status = "discarded"
    session.discarded_at = datetime.now(UTC)
    session.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(session)
    return _authoring_info(session)


async def decline_authoring_custom_sql(
    db: AsyncSession, *, org_id: str, user_id: str, session_id: str
) -> DashboardAuthoringSessionInfo:
    session = await get_authoring_session(db, org_id=org_id, user_id=user_id, session_id=session_id)
    if session is None:
        raise DashboardNotFoundError
    if session.status != "preview" or not session.requires_custom_sql_confirmation:
        raise DashboardValidationError("Authoring preview has no pending custom SQL confirmation")
    definition = DashboardDefinition.model_validate(session.definition_json)
    removed = set(session.pending_custom_sql_chart_ids_json or [])
    charts = [chart for chart in definition.charts if chart.id not in removed]
    tiles = [tile for tile in definition.tiles if tile.chartId not in removed]
    if not charts or not tiles:
        raise DashboardValidationError("Declining custom SQL would leave no usable governed charts")
    binding = definition.signalPilot
    if binding.evalBindings:
        binding = binding.model_copy(
            update={"evalBindings": [item for item in binding.evalBindings if item.chartId not in removed] or None}
        )
    definition = DashboardDefinition.model_validate(
        definition.model_copy(update={"charts": charts, "tiles": tiles, "signalPilot": binding})
    )
    events = list(session.events_json or [])
    events.append(
        _authoring_event(
            events,
            kind="confirmation",
            status="success",
            message="Declined low-confidence custom SQL; retained the remaining governed draft",
            metadata={"chart_ids": sorted(removed), "accepted": False},
        )
    )
    confirmations = list(session.confirmations_json or [])
    confirmations.append({"chart_ids": sorted(removed), "accepted": False, "created_at": datetime.now(UTC).isoformat()})
    session.definition_json = normalize_dashboard_definition(definition)
    session.events_json = events
    session.confirmations_json = confirmations
    session.requires_custom_sql_confirmation = False
    session.custom_sql_confirmed = False
    session.pending_custom_sql_chart_ids_json = []
    session.draft_revision += 1
    session.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(session)
    return _authoring_info(session)


async def get_authoring_session(
    db: AsyncSession, *, org_id: str, user_id: str, session_id: str
) -> GatewayDashboardAuthoringSession | None:
    return (
        await db.execute(
            select(GatewayDashboardAuthoringSession).where(
                GatewayDashboardAuthoringSession.id == session_id,
                GatewayDashboardAuthoringSession.org_id == org_id,
                GatewayDashboardAuthoringSession.owner_user_id == user_id,
            )
        )
    ).scalar_one_or_none()


async def get_active_authoring_session(
    db: AsyncSession, *, org_id: str, user_id: str, dashboard_id: str
) -> GatewayDashboardAuthoringSession | None:
    return (
        await db.execute(
            select(GatewayDashboardAuthoringSession)
            .where(
                GatewayDashboardAuthoringSession.dashboard_id == dashboard_id,
                GatewayDashboardAuthoringSession.org_id == org_id,
                GatewayDashboardAuthoringSession.owner_user_id == user_id,
            )
            .order_by(GatewayDashboardAuthoringSession.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def confirm_authoring_custom_sql(
    db: AsyncSession, *, org_id: str, user_id: str, session_id: str
) -> DashboardAuthoringSessionInfo:
    session = await get_authoring_session(db, org_id=org_id, user_id=user_id, session_id=session_id)
    if session is None:
        raise DashboardNotFoundError
    if session.status != "preview":
        raise DashboardValidationError("Authoring session is no longer an active preview")
    if not session.requires_custom_sql_confirmation:
        raise DashboardValidationError("Authoring preview does not contain custom SQL")
    chart_ids = list(session.pending_custom_sql_chart_ids_json or [])
    events = list(session.events_json or [])
    events.append(
        _authoring_event(
            events,
            kind="confirmation",
            status="success",
            message="Confirmed low-confidence custom SQL for governed preview execution",
            metadata={"chart_ids": chart_ids, "accepted": True},
        )
    )
    confirmations = list(session.confirmations_json or [])
    confirmations.append({"chart_ids": chart_ids, "accepted": True, "created_at": datetime.now(UTC).isoformat()})
    session.events_json = events
    session.confirmations_json = confirmations
    session.custom_sql_confirmed = True
    session.pending_custom_sql_chart_ids_json = []
    session.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(session)
    return _authoring_info(session)


async def apply_authoring_session(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    session_id: str,
    expected_current_version_id: str | None,
    visible_complete_result_ids: list[str],
) -> DashboardDetail:
    session = await get_authoring_session(db, org_id=org_id, user_id=user_id, session_id=session_id)
    if session is None:
        raise DashboardNotFoundError
    if session.status != "preview":
        raise DashboardValidationError("Authoring session is no longer an active preview")
    if session.requires_custom_sql_confirmation and not session.custom_sql_confirmed:
        raise DashboardValidationError("Custom SQL must be explicitly confirmed before Apply")
    definition = DashboardDefinition.model_validate(session.definition_json)
    provenance = {
        "authoring_session_id": session.id,
        "agent_run_id": session.agent_run_id,
        "agent_run_ids": [run.get("id") for run in (session.agent_runs_json or [])],
        "authoring_model": session.model,
        "base_version_id": session.base_version_id,
        "operations": session.operations_json,
        "prompt": session.prompt,
        "draft_revision": session.draft_revision,
        "draft_content_hash": dashboard_content_hash(definition),
        "confirmation_count": len(session.confirmations_json or []),
    }
    was_new_dashboard = session.dashboard_id is None
    draft_dashboard_id = f"draft:{session.id}" if was_new_dashboard else session.dashboard_id
    if was_new_dashboard:
        detail = await create_private_dashboard(
            db,
            org_id=org_id,
            user_id=user_id,
            definition=definition,
            authoring_provenance=provenance,
        )
        session = await get_authoring_session(db, org_id=org_id, user_id=user_id, session_id=session_id)
        assert session is not None
        session.dashboard_id = detail.dashboard.id
    else:
        if expected_current_version_id is None:
            raise DashboardValidationError("Apply requires the expected current dashboard version")
        detail = await create_dashboard_version(
            db,
            org_id=org_id,
            user_id=user_id,
            dashboard_id=session.dashboard_id,
            expected_current_version_id=expected_current_version_id,
            definition=definition,
            authoring_provenance=provenance,
        )
        session = await get_authoring_session(db, org_id=org_id, user_id=user_id, session_id=session_id)
        assert session is not None
    if visible_complete_result_ids:
        await db.execute(
            update(GatewayDashboardResult)
            .where(
                GatewayDashboardResult.id.in_(visible_complete_result_ids),
                GatewayDashboardResult.org_id == org_id,
                GatewayDashboardResult.dashboard_id == draft_dashboard_id,
                GatewayDashboardResult.version_id == f"draft:{session.id}",
                GatewayDashboardResult.completeness == "complete",
            )
            .values(dashboard_id=detail.dashboard.id, version_id=detail.version.id)
        )
    events = list(session.events_json or [])
    events.append(
        _authoring_event(
            events,
            kind="system",
            status="success",
            message=f"Applied dashboard version {detail.version.ordinal}",
            metadata={"version_id": detail.version.id, "ordinal": detail.version.ordinal},
        )
    )
    session.events_json = events
    session.status = "applied"
    session.applied_version_id = detail.version.id
    session.applied_at = datetime.now(UTC)
    session.updated_at = datetime.now(UTC)
    await db.commit()
    return detail
