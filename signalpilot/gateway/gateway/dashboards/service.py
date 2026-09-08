"""Dashboard lifecycle: publish, versions, settings, edit chats.

The service takes a session, a storage facade, and plain inputs. It raises
``DashboardError`` with an HTTP status; the API maps it to a response. The
refresh path lives in ``refresh.py`` and reuses ``write_version`` here.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import (
    GatewayChatFile,
    GatewayPublishedDashboard,
    GatewayPublishedDashboardVersion,
)
from gateway.db.models.dashboards import new_dashboard_id, new_version_id

from . import schema, store
from .datasets import (
    ManifestRow,
    Row,
    dataset_extension,
    inline_rows,
    parse_dataset_bytes,
    resolve_dataset_refs,
)
from .schedule import DEFAULT_ANCHOR, DEFAULT_TIMEZONE, compute_next_refresh_at
from .serializers import PublishDashboardRequest, RefreshSettingsIn, UpdateDashboardRequest
from .storage import MAX_DATASET_BYTES, MAX_SPEC_BYTES, DashboardStorage, dataset_key, spec_key

PROMPTS_DIR = Path(__file__).with_name("prompts")
EDIT_MESSAGE_CAP_BYTES = 200 * 1024
EDIT_CHAT_ORIGIN = "user"
EDIT_CHAT_BUDGET_USD = 2.0


class DashboardError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


@dataclass
class DatasetPayload:
    """Bytes of one file-backed dataset ready to be stored."""

    data: bytes
    filename: str
    rows: list[Row]

    @property
    def meta(self) -> dict[str, Any]:
        return {"row_count": len(self.rows), "byte_size": len(self.data), "filename": self.filename}


@dataclass
class VersionMaterial:
    """Everything a new version needs: the spec, new bytes, and carried keys."""

    spec: dict[str, Any]
    payloads: dict[str, DatasetPayload] = field(default_factory=dict)
    # Datasets whose bytes did not change: reference the previous key.
    carried: dict[str, tuple[str, dict[str, Any]]] = field(default_factory=dict)


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def render_prompt(name: str, values: dict[str, str]) -> str:
    text = load_prompt(name)
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text.strip() + "\n"


def dashboard_artifact_path(dashboard: GatewayPublishedDashboard) -> str:
    return f"artifacts/{dashboard.slug}.dashboard.json"


# ── Versions ────────────────────────────────────────────────────────────────


async def write_version(
    db: AsyncSession,
    storage: DashboardStorage,
    dashboard: GatewayPublishedDashboard,
    material: VersionMaterial,
    *,
    produced_by: str,
    producer_ref: str | None,
) -> GatewayPublishedDashboardVersion:
    """Store the material under a fresh version id and make it current.

    Carried datasets reference the previous version's object key. Objects are
    only ever deleted with the whole dashboard prefix, so a shared key stays
    valid for every version that points at it.

    The row is flushed, not committed: the caller commits it together with
    whatever else belongs to the same step (publish settings, refresh status).
    """
    version_id = new_version_id()
    org_id = dashboard.org_id
    await storage.put_spec(spec_key(org_id, dashboard.id, version_id), material.spec)
    dataset_keys: dict[str, str] = {}
    dataset_meta: dict[str, dict[str, Any]] = {}
    for name, payload in material.payloads.items():
        key = dataset_key(org_id, dashboard.id, version_id, name, dataset_extension(payload.filename))
        await storage.put_dataset(key, payload.data, filename=payload.filename)
        dataset_keys[name] = key
        dataset_meta[name] = payload.meta
    for name, (key, meta) in material.carried.items():
        dataset_keys[name] = key
        dataset_meta[name] = dict(meta)
    return await store.create_version(
        db,
        dashboard=dashboard,
        version_id=version_id,
        spec_key=spec_key(org_id, dashboard.id, version_id),
        dataset_keys=dataset_keys,
        dataset_meta=dataset_meta,
        chart_count=schema.chart_count(material.spec),
        produced_by=produced_by,
        producer_ref=producer_ref,
    )


async def restore_version(
    db: AsyncSession,
    storage: DashboardStorage,
    dashboard: GatewayPublishedDashboard,
    version: GatewayPublishedDashboardVersion,
    *,
    user_id: str,
) -> GatewayPublishedDashboardVersion:
    """A new current version that points at the restored version's objects."""
    spec = await storage.get_spec(version.spec_key)
    material = VersionMaterial(
        spec=spec,
        carried={name: (key, (version.dataset_meta or {}).get(name) or {}) for name, key in (version.dataset_keys or {}).items()},
    )
    version = await write_version(db, storage, dashboard, material, produced_by="restore", producer_ref=user_id)
    await db.commit()
    return version


async def load_bundle_datasets(
    storage: DashboardStorage,
    spec: dict[str, Any],
    version: GatewayPublishedDashboardVersion,
) -> dict[str, list[Row]]:
    """Rows for every dataset of a version, inline ones included."""
    datasets: dict[str, list[Row]] = {}
    keys = version.dataset_keys or {}
    for name, definition in schema.dataset_definitions(spec).items():
        rows = inline_rows(definition)
        if rows is not None:
            datasets[name] = rows
            continue
        key = keys.get(name)
        if not key:
            datasets[name] = []
            continue
        filename = str(definition.get("file") or f"{name}.csv")
        try:
            datasets[name] = parse_dataset_bytes(await storage.get_dataset(key), filename)
        except ValueError:
            datasets[name] = []
    return datasets


# ── Publish ─────────────────────────────────────────────────────────────────


async def collect_publish_material(
    storage: DashboardStorage,
    *,
    file_row: GatewayChatFile,
    manifest: list[ManifestRow],
) -> VersionMaterial:
    """Read and validate the spec and every dataset file of a chat dashboard."""
    if file_row.kind != "dashboard":
        raise DashboardError(422, {"message": "File is not a dashboard", "errors": []})
    raw = await storage.get_chat_object(file_row.object_key, max_bytes=MAX_SPEC_BYTES)
    spec, errors = schema.parse_spec(raw)
    if spec is None:
        raise DashboardError(422, {"message": "Dashboard spec is invalid", "errors": errors})
    resolved = resolve_dataset_refs(schema.dataset_file_refs(spec), manifest, run_id=file_row.origin_run_id)
    missing = [item.name for item in resolved if item.row is None]
    if missing:
        raise DashboardError(
            422,
            {
                "message": "Dataset files are missing from the conversation",
                "missing_datasets": missing,
                "errors": [item.error for item in resolved if item.error],
            },
        )
    material = VersionMaterial(spec=spec)
    for item in resolved:
        assert item.row is not None
        data = await storage.get_chat_object(item.row.object_key, max_bytes=MAX_DATASET_BYTES)
        try:
            rows = parse_dataset_bytes(data, item.row.filename)
        except ValueError as exc:
            raise DashboardError(422, {"message": f"Dataset '{item.name}' could not be parsed", "errors": [str(exc)]}) from exc
        material.payloads[item.name] = DatasetPayload(data=data, filename=item.row.filename, rows=rows)
    return material


def apply_settings(
    dashboard: GatewayPublishedDashboard,
    *,
    now: datetime,
    name: str | None = None,
    description: str | None = None,
    description_set: bool = False,
    visibility: str | None = None,
    refresh: RefreshSettingsIn | None = None,
    notify_on_failure: bool | None = None,
) -> None:
    """Apply editable fields. Recompute the schedule when refresh changes."""
    if name is not None:
        dashboard.name = name.strip()
    if description_set:
        dashboard.description = (description or "").strip() or None
    if visibility is not None:
        dashboard.visibility = visibility
    if notify_on_failure is not None:
        dashboard.notify_on_failure = bool(notify_on_failure)
    if refresh is not None:
        dashboard.refresh_interval_minutes = refresh.interval_minutes
        dashboard.refresh_anchor_time = refresh.anchor_time or DEFAULT_ANCHOR
        dashboard.refresh_timezone = refresh.timezone or DEFAULT_TIMEZONE
        dashboard.refresh_mode = refresh.mode
        dashboard.next_refresh_at = compute_next_refresh_at(
            now, refresh.interval_minutes, dashboard.refresh_anchor_time, dashboard.refresh_timezone
        )
    dashboard.updated_at = now


async def publish(
    db: AsyncSession,
    storage: DashboardStorage,
    *,
    org_id: str,
    user_id: str,
    is_admin: bool,
    conversation_id: str,
    file_row: GatewayChatFile,
    manifest: list[ManifestRow],
    body: PublishDashboardRequest,
    project_id: str | None,
) -> tuple[GatewayPublishedDashboard, GatewayPublishedDashboardVersion]:
    """Publish a chat dashboard file as a new dashboard or a new version."""
    material = await collect_publish_material(storage, file_row=file_row, manifest=manifest)
    now = store.utcnow()
    if body.target_dashboard_id:
        dashboard = await store.get_dashboard(db, org_id=org_id, id_or_slug=body.target_dashboard_id)
        if dashboard is None:
            raise DashboardError(404, "Target dashboard not found")
        if not store.can_edit(dashboard, user_id, is_admin=is_admin):
            raise DashboardError(403, "You cannot publish to this dashboard")
        if dashboard.archived_at is not None:
            raise DashboardError(409, "Unarchive the dashboard before publishing a new version to it")
        if body.slug and body.slug != dashboard.slug:
            dashboard.slug = await store.unique_slug(db, org_id=org_id, base=body.slug, exclude_id=dashboard.id)
    else:
        slug = await store.unique_slug(db, org_id=org_id, base=body.slug or store.slugify(body.name))
        dashboard = GatewayPublishedDashboard(
            id=new_dashboard_id(),
            org_id=org_id,
            project_id=project_id,
            slug=slug,
            name=body.name.strip(),
            created_by_user_id=user_id,
            created_at=now,
            updated_at=now,
        )
        db.add(dashboard)
        await db.flush()
    # The new version came from this chat; later refreshes and edit chats
    # follow the latest source, not the one the dashboard was first published from.
    dashboard.project_id = project_id
    dashboard.source_conversation_id = conversation_id
    dashboard.source_file_id = file_row.id
    apply_settings(
        dashboard,
        now=now,
        name=body.name,
        description=body.description,
        description_set=body.description is not None or not body.target_dashboard_id,
        visibility=body.visibility,
        refresh=body.refresh,
        notify_on_failure=body.notify_on_failure,
    )
    version = await write_version(db, storage, dashboard, material, produced_by="publish", producer_ref=user_id)
    await db.commit()
    return dashboard, version


# ── Settings, archive, delete ───────────────────────────────────────────────


async def update_settings(
    db: AsyncSession,
    dashboard: GatewayPublishedDashboard,
    body: UpdateDashboardRequest,
) -> GatewayPublishedDashboard:
    fields = body.model_dump(exclude_unset=True)
    apply_settings(
        dashboard,
        now=store.utcnow(),
        name=body.name,
        description=body.description,
        description_set="description" in fields,
        visibility=body.visibility,
        refresh=body.refresh,
        notify_on_failure=body.notify_on_failure,
    )
    await db.commit()
    return dashboard


async def set_archived(db: AsyncSession, dashboard: GatewayPublishedDashboard, archived: bool) -> None:
    now = store.utcnow()
    dashboard.archived_at = now if archived else None
    if not archived and dashboard.refresh_interval_minutes is not None:
        dashboard.next_refresh_at = compute_next_refresh_at(
            now, dashboard.refresh_interval_minutes, dashboard.refresh_anchor_time, dashboard.refresh_timezone
        )
    dashboard.updated_at = now
    await db.commit()


async def delete(db: AsyncSession, storage: DashboardStorage, dashboard: GatewayPublishedDashboard) -> None:
    org_id, dashboard_id = dashboard.org_id, dashboard.id
    await store.delete_dashboard(db, dashboard)
    try:
        await storage.delete_dashboard(org_id, dashboard_id)
    except Exception:  # best effort: the rows are gone, orphaned objects are harmless
        pass


# ── Edit chat ───────────────────────────────────────────────────────────────


def edit_message(
    dashboard: GatewayPublishedDashboard,
    spec: dict[str, Any],
    dataset_bytes: dict[str, tuple[str, bytes]],
) -> str:
    """The first user message of an edit chat: spec and datasets inline.

    The gateway cannot seed files into a fresh run's scratch directory, so
    the datasets travel inline as fenced blocks under a 200 KB cap. Datasets
    past the cap are listed as omitted.
    """
    spec_json = json.dumps(spec, indent=2, ensure_ascii=False)
    budget = EDIT_MESSAGE_CAP_BYTES - len(spec_json.encode("utf-8"))
    blocks: list[str] = []
    omitted: list[str] = []
    for name, (path, data) in dataset_bytes.items():
        text = data.decode("utf-8", errors="replace")
        fence = "```" if "```" not in text else "````"
        block = f"Dataset `{name}` at `{path}`:\n\n{fence}\n{text.rstrip()}\n{fence}\n"
        size = len(block.encode("utf-8"))
        if size > budget:
            omitted.append(f"{name} ({path})")
            continue
        budget -= size
        blocks.append(block)
    if omitted:
        blocks.append("Datasets omitted because they are too large to inline; reproduce them from their `source`:\n- " + "\n- ".join(omitted))
    return render_prompt(
        "edit_prompt.md",
        {
            "dashboard_name": dashboard.name,
            "dashboard_path": dashboard_artifact_path(dashboard),
            "spec_json": spec_json,
            "dataset_blocks": "\n".join(blocks),
        },
    )


async def seed_dashboard_chat(
    db: AsyncSession,
    dashboard: GatewayPublishedDashboard,
    *,
    user_id: str,
    message: str,
    title: str,
    origin: str,
    chat_budget_usd: float,
    per_query_budget_usd: float = 0.25,
) -> tuple[str, str]:
    """Create a conversation and its queued first run in the dashboard's project.

    Shared by the edit chat and the agent-mode refresh. Raises
    ``DashboardError(409)`` when the project is missing or not chat-ready.
    Returns ``(conversation_id, run_id)``.
    """
    from gateway.git.repos import branch_head_sha
    from gateway.standalone_chat.projects import authorize_chat_project, evaluate_project_readiness
    from gateway.store.standalone_chat import create_conversation_with_run

    if not dashboard.project_id:
        raise DashboardError(409, "This dashboard has no project; publish it from a project chat first")
    project = await authorize_chat_project(
        db, org_id=dashboard.org_id, user_id=user_id, project_id=dashboard.project_id
    )
    if project is None:
        raise DashboardError(409, "The dashboard's project no longer exists")
    readiness = await evaluate_project_readiness(db, org_id=dashboard.org_id, user_id=user_id, project=project)
    if not readiness.ready or not readiness.branch:
        raise DashboardError(409, f"Project is not chat-ready ({readiness.code}): {readiness.message}")
    commit_sha = branch_head_sha(project.id, readiness.branch)
    if not commit_sha or len(commit_sha) != 40:
        raise DashboardError(409, f"Project has no resolvable head commit on {readiness.branch}")
    conversation, run = await create_conversation_with_run(
        db,
        org_id=dashboard.org_id,
        user_id=user_id,
        project=project,
        branch=readiness.branch,
        message=message,
        commit_sha=commit_sha,
        per_query_budget_usd=per_query_budget_usd,
        chat_budget_usd=chat_budget_usd,
        origin=origin,
    )
    conversation.title = title[:200]
    conversation.updated_at = time.time()
    await db.commit()
    return conversation.id, run.id


async def create_edit_chat(
    db: AsyncSession,
    storage: DashboardStorage,
    dashboard: GatewayPublishedDashboard,
    version: GatewayPublishedDashboardVersion,
    *,
    user_id: str,
) -> str:
    """Create a conversation seeded with the current spec and datasets."""
    spec = await storage.get_spec(version.spec_key)
    dataset_bytes: dict[str, tuple[str, bytes]] = {}
    refs = schema.dataset_file_refs(spec)
    for name, key in (version.dataset_keys or {}).items():
        dataset_bytes[name] = (refs.get(name, f"artifacts/{name}.csv"), await storage.get_dataset(key))
    conversation_id, _run_id = await seed_dashboard_chat(
        db,
        dashboard,
        user_id=user_id,
        message=edit_message(dashboard, spec, dataset_bytes),
        title=f"Edit dashboard: {dashboard.name}",
        origin=EDIT_CHAT_ORIGIN,
        chat_budget_usd=EDIT_CHAT_BUDGET_USD,
    )
    return conversation_id
