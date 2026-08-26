"""Multipart upload reservations, scoped by org_id.

Reservations live in the database rather than a process dict so that every
uvicorn worker and replica counts against one per-principal quota, and so the
slot can be taken before the S3 CreateMultipartUpload round-trip is awaited.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid

from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayUploadSession

logger = logging.getLogger(__name__)

# Namespace for the per-principal Postgres advisory lock. Arbitrary but fixed —
# it only has to not collide with another advisory-lock user in this database.
_QUOTA_LOCK_CLASSID = 0x5055


class QuotaExceeded(Exception):
    """The principal's open-upload or concurrent-byte ceiling is already used."""


async def _lock_principal(session: AsyncSession, org_id: str, user_id: str) -> None:
    """Serialize reservations for one principal across workers and replicas.

    The lock is transaction-scoped, so it is held from here until the caller
    commits — which is what makes the count-then-insert below atomic. Non-
    Postgres dialects (sqlite in unit tests) serialize writes themselves.
    """
    try:
        dialect = session.bind.dialect.name  # type: ignore[union-attr]
    except Exception:
        return
    if dialect != "postgresql":
        return
    digest = hashlib.blake2b(f"{org_id}\x00{user_id}".encode(), digest_size=4).digest()
    objid = int.from_bytes(digest, "big", signed=True)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:classid, :objid)"),
        {"classid": _QUOTA_LOCK_CLASSID, "objid": objid},
    )


async def _prune(session: AsyncSession, org_id: str, user_id: str, now: float) -> None:
    """Drop this principal's expired reservations.

    Scoped to the principal, not the org: the reservation path already holds
    that principal's advisory lock, so a per-principal sweep can never contend
    with a concurrent one.
    """
    await session.execute(
        delete(GatewayUploadSession).where(
            GatewayUploadSession.org_id == org_id,
            GatewayUploadSession.user_id == user_id,
            GatewayUploadSession.expires_at <= now,
        )
    )


async def reserve(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    key: str,
    size_bytes: int,
    part_lengths: list[int],
    max_open: int,
    max_bytes: int,
    ttl_s: float,
) -> None:
    """Claim a quota slot, or raise QuotaExceeded leaving nothing reserved."""
    await _lock_principal(session, org_id, user_id)
    now = time.time()
    await _prune(session, org_id, user_id, now)

    result = await session.execute(
        select(GatewayUploadSession).where(
            GatewayUploadSession.org_id == org_id,
            GatewayUploadSession.user_id == user_id,
        )
    )
    open_sessions = list(result.scalars())

    rejection: str | None = None
    if len(open_sessions) >= max_open:
        rejection = f"Too many uploads in progress (limit {max_open}) — finish or abort one first"
    else:
        outstanding = sum(s.size_bytes for s in open_sessions)
        if outstanding + size_bytes > max_bytes:
            rejection = f"Uploads in progress already reserve {outstanding // (1024 * 1024)} MB of the quota"
    if rejection:
        # Commit the pruning so the advisory lock is released now rather than
        # at request teardown.
        await session.commit()
        raise QuotaExceeded(rejection)

    session.add(
        GatewayUploadSession(
            id=str(uuid.uuid4()),
            org_id=org_id,
            user_id=user_id,
            key=key,
            upload_id=None,
            size_bytes=size_bytes,
            part_lengths=list(part_lengths),
            created_at=now,
            expires_at=now + ttl_s,
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise QuotaExceeded("Upload key collision — retry the initiation") from None


async def bind_upload_id(session: AsyncSession, *, org_id: str, key: str, upload_id: str) -> None:
    """Attach the S3 upload id to an already-reserved slot."""
    await session.execute(
        update(GatewayUploadSession)
        .where(GatewayUploadSession.org_id == org_id, GatewayUploadSession.key == key)
        .values(upload_id=upload_id)
    )
    await session.commit()


async def release(session: AsyncSession, *, org_id: str, key: str) -> None:
    """Drop the reservation — on failed initiation, completion, or abort."""
    await session.execute(
        delete(GatewayUploadSession).where(
            GatewayUploadSession.org_id == org_id, GatewayUploadSession.key == key
        )
    )
    await session.commit()


async def get_owned(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    key: str,
    upload_id: str,
) -> GatewayUploadSession | None:
    """Return the live reservation for this exact owner/key/upload_id triple."""
    now = time.time()
    await _prune(session, org_id, user_id, now)
    await session.commit()
    result = await session.execute(
        select(GatewayUploadSession).where(
            GatewayUploadSession.org_id == org_id,
            GatewayUploadSession.user_id == user_id,
            GatewayUploadSession.key == key,
            GatewayUploadSession.upload_id == upload_id,
        )
    )
    return result.scalar_one_or_none()
