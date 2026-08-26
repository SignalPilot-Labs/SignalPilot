"""Unified artifact index — a read model over existing artifact provenance rows.

Artifacts are produced in two places today, with two disjoint surfaces:

- **Chat artifacts** live as rows in ``gateway_chat_artifacts``
  (:class:`~gateway.db.models.GatewayChatArtifact`), one row per published
  artifact, downloadable via ``/api/chat/artifacts/{id}/download``.
- **Eval artifacts** live as *blobs* in the evals object store under
  ``evals/<org>/runs/<run>/artifacts/<task>/<file>``. The database does not
  keep one row per artifact, but the capture pipeline records the stored
  filenames and byte sizes on the task row
  (:class:`~gateway.db.models.GatewayEvalRunTask` ``capture_result`` —
  ``stored`` lists the filenames actually uploaded, ``tables[*].file`` /
  ``tables[*].file_bytes`` carry per-file sizes). This module derives the
  eval listing from those rows alone — it never calls S3.

**Notebook artifacts do not exist yet.** Workspace revisions (the S3-backed
project filesystem) are versioned source files, not artifacts, so they are
deliberately not surfaced here. When Notebook Runtime v2 grows a real
artifact-producing surface, it gets a third branch in :func:`list_artifacts`;
until then ``kind="notebook"`` simply yields nothing rather than inventing a
table.

Retention interaction: eval retention (:mod:`gateway.evals.retention`) prunes
*blobs* by prefix and flips ``GatewayEvalRun.artifacts_pruned`` — it never
deletes the task rows inside the artifact window, so pruned runs still list
here with ``available: False``. Chat artifacts are row-owned (inline bytes or
an object key on the row), so a row present means the record lists.

This module is read-only: no new tables, no writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import (
    GatewayChatArtifact,
    GatewayChatRun,
    GatewayEvalRun,
    GatewayEvalRunTask,
)

KINDS = ("chat", "eval", "notebook")

_EPOCH = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True)
class ArtifactRecord:
    """One unified artifact entry, whatever produced it."""

    id: str
    kind: str  # "chat" | "eval" ("notebook" reserved — see module docstring)
    name: str
    content_type: str
    byte_size: int | None
    created_at: str | None  # ISO-8601, UTC
    available: bool
    provenance: dict[str, str] = field(default_factory=dict)
    download: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "content_type": self.content_type,
            "byte_size": self.byte_size,
            "created_at": self.created_at,
            "available": self.available,
            "provenance": self.provenance,
            "download": self.download,
        }


def _as_utc(value: Any) -> datetime | None:
    """Normalize a row timestamp (datetime or ISO string) to aware UTC."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, str) and value:
        try:
            return _as_utc(datetime.fromisoformat(value))
        except ValueError:
            return None
    return None


def _iso(value: Any) -> str | None:
    normalized = _as_utc(value)
    return normalized.isoformat() if normalized is not None else None


async def _chat_records(
    session: AsyncSession,
    *,
    org_id: str,
    project_id: str | None,
    run_id: str | None,
) -> list[tuple[datetime, ArtifactRecord]]:
    stmt = (
        select(GatewayChatArtifact, GatewayChatRun)
        .join(
            GatewayChatRun,
            and_(
                GatewayChatRun.id == GatewayChatArtifact.run_id,
                GatewayChatRun.org_id == org_id,
            ),
            isouter=True,
        )
        .where(GatewayChatArtifact.org_id == org_id)
    )
    if run_id is not None:
        stmt = stmt.where(GatewayChatArtifact.run_id == run_id)
    if project_id is not None:
        stmt = stmt.where(GatewayChatRun.project_id == project_id)

    out: list[tuple[datetime, ArtifactRecord]] = []
    for artifact, run in (await session.execute(stmt)).all():
        provenance: dict[str, str] = {
            "conversation_id": artifact.conversation_id,
            "run_id": artifact.run_id,
        }
        if run is not None:
            provenance["project_id"] = run.project_id
            if run.execution_session_id:
                provenance["session_id"] = run.execution_session_id
        # A chat artifact row always carries a renderable snapshot; only an
        # object-storage artifact whose key is missing is undownloadable.
        available = not (artifact.storage_kind == "object" and not artifact.object_key)
        out.append(
            (
                _as_utc(artifact.created_at) or _EPOCH,
                ArtifactRecord(
                    id=artifact.id,
                    kind="chat",
                    name=artifact.filename,
                    content_type=artifact.mime_type,
                    byte_size=artifact.byte_size,
                    created_at=_iso(artifact.created_at),
                    available=available,
                    provenance=provenance,
                    download={"route": f"/api/chat/artifacts/{artifact.id}/download"},
                ),
            )
        )
    return out


async def _eval_records(
    session: AsyncSession,
    *,
    org_id: str,
    run_id: str | None,
) -> list[tuple[datetime, ArtifactRecord]]:
    stmt = (
        select(GatewayEvalRunTask, GatewayEvalRun)
        .join(
            GatewayEvalRun,
            and_(
                GatewayEvalRun.id == GatewayEvalRunTask.run_id,
                GatewayEvalRun.org_id == org_id,
            ),
        )
        .where(GatewayEvalRunTask.org_id == org_id)
    )
    if run_id is not None:
        stmt = stmt.where(GatewayEvalRunTask.run_id == run_id)

    out: list[tuple[datetime, ArtifactRecord]] = []
    for task, run in (await session.execute(stmt)).all():
        capture = task.capture_result or {}
        stored = capture.get("stored") or []
        if not stored:
            continue
        sizes: dict[str, int | None] = {}
        for entry in (capture.get("tables") or {}).values():
            if isinstance(entry, dict) and entry.get("file"):
                size = entry.get("file_bytes")
                sizes[str(entry["file"])] = int(size) if isinstance(size, int) else None
        created_raw = task.finished_at or task.started_at or run.created_at
        created = _as_utc(created_raw) or _EPOCH
        for filename in stored:
            filename = str(filename)
            out.append(
                (
                    created,
                    ArtifactRecord(
                        id=f"eval:{task.run_id}:{task.task_id}:{filename}",
                        kind="eval",
                        name=filename,
                        content_type="application/octet-stream",
                        byte_size=sizes.get(filename),
                        created_at=_iso(created_raw),
                        # Retention deletes eval blobs by prefix and flips this
                        # flag; the provenance rows survive, so the record
                        # still lists — just not downloadable any more.
                        available=not run.artifacts_pruned,
                        provenance={"run_id": task.run_id, "task_id": task.task_id},
                        download={
                            "route": (
                                f"/api/evals/runs/{task.run_id}"
                                f"/artifacts/{task.task_id}/{filename}"
                            )
                        },
                    ),
                )
            )
    return out


async def list_artifacts(
    session: AsyncSession,
    *,
    org_id: str,
    project_id: str | None = None,
    kind: str | None = None,
    run_id: str | None = None,
    since: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ArtifactRecord], int]:
    """List unified artifact records for one organization, newest first.

    Returns ``(page, total)`` where ``total`` counts every record matching the
    filters (before pagination). ``org_id`` scopes every underlying query —
    there is no unscoped path.
    """
    if not org_id:
        raise ValueError("org_id is required — the artifact index is always org-scoped")
    if kind is not None and kind not in KINDS:
        raise ValueError(f"unknown artifact kind {kind!r}; expected one of {KINDS}")

    dated: list[tuple[datetime, ArtifactRecord]] = []
    if kind in (None, "chat"):
        dated.extend(
            await _chat_records(
                session, org_id=org_id, project_id=project_id, run_id=run_id
            )
        )
    # Eval runs carry no workspace project — a project filter excludes them.
    if kind in (None, "eval") and project_id is None:
        dated.extend(await _eval_records(session, org_id=org_id, run_id=run_id))
    # kind == "notebook": nothing exists yet (see module docstring).

    if since is not None:
        floor = since.replace(tzinfo=UTC) if since.tzinfo is None else since.astimezone(UTC)
        dated = [item for item in dated if item[0] >= floor]

    dated.sort(key=lambda item: (item[0], item[1].id), reverse=True)
    total = len(dated)
    page = [record for _, record in dated[offset : offset + max(limit, 0)]]
    return page, total
