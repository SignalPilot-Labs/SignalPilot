"""Conversation file manifest persistence.

One row per conversation-relative path. The newest write wins; the unique
constraint on (conversation_id, path) enforces that. Content lives in
object storage under the conversation prefix.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayChatFile, GatewayChatRun
from gateway.standalone_chat.domain import TERMINAL_RUN_STATUSES

_KIND_BY_EXTENSION = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".py": "code",
    ".sql": "code",
    ".js": "code",
    ".ts": "code",
    ".sh": "code",
    ".yml": "code",
    ".yaml": "code",
    ".json": "code",
    ".toml": "code",
    ".html": "html",
    ".htm": "html",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".svg": "image",
    ".webp": "image",
    ".ipynb": "notebook",
    ".csv": "data",
    ".parquet": "data",
    ".jsonl": "data",
}

_KIND_BY_MIME = {
    "text/markdown": "markdown",
    "text/html": "html",
}


def derive_file_kind(filename: str, mime_type: str | None) -> str:
    """Classify a file for the artifacts panel from its extension and MIME type."""
    extension = PurePosixPath(filename.lower()).suffix
    kind = _KIND_BY_EXTENSION.get(extension)
    if kind:
        return kind
    mime = (mime_type or "").split(";", 1)[0].strip().lower()
    if mime.startswith("image/"):
        return "image"
    return _KIND_BY_MIME.get(mime, "other")


async def upsert_conversation_file(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
    path: str,
    filename: str,
    mime_type: str | None,
    byte_size: int,
    content_hash: str,
    object_key: str,
    origin_run_id: str | None,
    origin: str,
    kind: str | None = None,
    file_id: str | None = None,
) -> GatewayChatFile:
    """Insert or refresh the manifest row for one path. The latest write wins.

    Pass kind to override the extension-derived kind. Pass file_id to fix the
    id of a new row. The id is ignored when a row for the path exists.
    """
    values = {
        "filename": filename,
        "kind": kind or derive_file_kind(filename, mime_type),
        "mime_type": mime_type,
        "byte_size": byte_size,
        "content_hash": content_hash,
        "object_key": object_key,
        "origin_run_id": origin_run_id,
        "origin": origin,
        "status": "active",
    }
    existing = (
        await db.execute(
            select(GatewayChatFile).where(
                GatewayChatFile.org_id == org_id,
                GatewayChatFile.user_id == user_id,
                GatewayChatFile.conversation_id == conversation_id,
                GatewayChatFile.path == path,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        for name, value in values.items():
            setattr(existing, name, value)
        await db.commit()
        await db.refresh(existing)
        return existing
    row = GatewayChatFile(
        org_id=org_id,
        user_id=user_id,
        conversation_id=conversation_id,
        path=path,
        **values,
    )
    if file_id:
        row.id = file_id
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent writer inserted the same path first. Update its row.
        await db.rollback()
        await db.execute(
            update(GatewayChatFile)
            .where(
                GatewayChatFile.org_id == org_id,
                GatewayChatFile.user_id == user_id,
                GatewayChatFile.conversation_id == conversation_id,
                GatewayChatFile.path == path,
            )
            .values(**values)
        )
        await db.commit()
        return (
            await db.execute(
                select(GatewayChatFile).where(
                    GatewayChatFile.conversation_id == conversation_id,
                    GatewayChatFile.path == path,
                )
            )
        ).scalar_one()
    await db.refresh(row)
    return row


async def list_conversation_files(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
) -> list[GatewayChatFile]:
    """Return the active manifest, newest change first. One query."""
    rows = (
        await db.execute(
            select(GatewayChatFile)
            .where(
                GatewayChatFile.org_id == org_id,
                GatewayChatFile.user_id == user_id,
                GatewayChatFile.conversation_id == conversation_id,
                GatewayChatFile.status == "active",
            )
            .order_by(GatewayChatFile.updated_at.desc())
        )
    ).scalars()
    return list(rows)


async def get_conversation_file(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
    file_id: str,
) -> GatewayChatFile | None:
    return (
        await db.execute(
            select(GatewayChatFile).where(
                GatewayChatFile.id == file_id,
                GatewayChatFile.org_id == org_id,
                GatewayChatFile.user_id == user_id,
                GatewayChatFile.conversation_id == conversation_id,
                GatewayChatFile.status == "active",
            )
        )
    ).scalar_one_or_none()


async def get_conversation_file_by_path(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
    path: str,
) -> GatewayChatFile | None:
    """Return the row for one conversation-relative path, active or deleted."""
    return (
        await db.execute(
            select(GatewayChatFile).where(
                GatewayChatFile.org_id == org_id,
                GatewayChatFile.user_id == user_id,
                GatewayChatFile.conversation_id == conversation_id,
                GatewayChatFile.path == path,
            )
        )
    ).scalar_one_or_none()


async def mark_conversation_file_deleted(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
    path: str,
) -> bool:
    """Soft-delete one path. Return True when an active row changed."""
    result = await db.execute(
        update(GatewayChatFile)
        .where(
            GatewayChatFile.org_id == org_id,
            GatewayChatFile.user_id == user_id,
            GatewayChatFile.conversation_id == conversation_id,
            GatewayChatFile.path == path,
            GatewayChatFile.status == "active",
        )
        .values(status="deleted")
    )
    await db.commit()
    return bool(result.rowcount)


async def conversation_file_usage(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
) -> tuple[int, int]:
    """Return (active_row_count, active_byte_total) for quota checks."""
    row = (
        await db.execute(
            select(
                func.count(GatewayChatFile.id),
                func.coalesce(func.sum(GatewayChatFile.byte_size), 0),
            ).where(
                GatewayChatFile.org_id == org_id,
                GatewayChatFile.user_id == user_id,
                GatewayChatFile.conversation_id == conversation_id,
                GatewayChatFile.status == "active",
            )
        )
    ).one()
    return int(row[0] or 0), int(row[1] or 0)


def _shared_file_query(*, org_id: str, owner_user_id: str, conversation_id: str):
    """Select active files whose origin run is terminal or absent.

    A file written by a running run is not share-safe yet. A forked copy has
    no origin run and is always safe.
    """
    return (
        select(GatewayChatFile)
        .outerjoin(GatewayChatRun, GatewayChatRun.id == GatewayChatFile.origin_run_id)
        .where(
            GatewayChatFile.org_id == org_id,
            GatewayChatFile.user_id == owner_user_id,
            GatewayChatFile.conversation_id == conversation_id,
            GatewayChatFile.status == "active",
            or_(
                GatewayChatRun.id.is_(None),
                GatewayChatRun.status.in_(TERMINAL_RUN_STATUSES),
            ),
        )
    )


async def list_shared_conversation_files(
    db: AsyncSession,
    *,
    org_id: str,
    owner_user_id: str,
    conversation_id: str,
) -> list[GatewayChatFile]:
    """Return the share-safe manifest, newest change first."""
    rows = (
        await db.execute(
            _shared_file_query(
                org_id=org_id,
                owner_user_id=owner_user_id,
                conversation_id=conversation_id,
            ).order_by(GatewayChatFile.updated_at.desc())
        )
    ).scalars()
    return list(rows)


async def get_shared_conversation_file(
    db: AsyncSession,
    *,
    org_id: str,
    owner_user_id: str,
    conversation_id: str,
    file_id: str,
) -> GatewayChatFile | None:
    return (
        await db.execute(
            _shared_file_query(
                org_id=org_id,
                owner_user_id=owner_user_id,
                conversation_id=conversation_id,
            ).where(GatewayChatFile.id == file_id)
        )
    ).scalar_one_or_none()
