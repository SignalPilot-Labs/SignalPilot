"""Persistent (DB-backed) API key CRUD + validation, scoped by org_id.

Distinct from gateway.store.local_api_key, which manages the file-based
local-mode sentinel key. This module owns the GatewayApiKey table."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayApiKey
from gateway.models import ApiKeyRecord
from gateway.runtime.mode import is_cloud_mode

logger = logging.getLogger(__name__)


async def list_api_keys(
    session: AsyncSession,
    *,
    org_id: str | None,
    allow_unscoped: bool,
) -> list[ApiKeyRecord]:
    if allow_unscoped:
        result = await session.execute(select(GatewayApiKey))
    else:
        result = await session.execute(select(GatewayApiKey).where(GatewayApiKey.org_id == org_id))
    return [
        ApiKeyRecord(
            id=r.id,
            name=r.name,
            prefix=r.prefix,
            key_hash=r.key_hash,
            scopes=r.scopes,
            created_at=r.created_at,
            last_used_at=r.last_used_at,
            expires_at=r.expires_at,
            user_id=r.user_id,
            org_id=r.org_id,
        )
        for r in result.scalars()
    ]


async def create_api_key(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str | None,
    name: str,
    scopes: list[str],
    expires_at: str | None = None,
) -> tuple[ApiKeyRecord, str]:
    # In cloud mode, refuse to mint keys without a real org_id.
    if is_cloud_mode() and (not org_id or org_id == "local"):
        raise ValueError(
            "Cannot create API key in cloud mode without a valid org_id. org_id must not be None, empty, or 'local'."
        )
    raw_key = "sp_" + secrets.token_hex(16)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    db_key = GatewayApiKey(
        id=key_id,
        org_id=org_id,
        user_id=user_id,
        name=name,
        prefix=raw_key[:11],
        key_hash=key_hash,
        scopes=scopes,
        created_at=now,
        expires_at=expires_at,
    )
    session.add(db_key)
    await session.commit()

    record = ApiKeyRecord(
        id=key_id,
        name=name,
        prefix=raw_key[:11],
        key_hash=key_hash,
        scopes=scopes,
        created_at=now,
        last_used_at=None,
        expires_at=expires_at,
        user_id=user_id,
        org_id=org_id,
    )
    return record, raw_key


async def delete_api_key(
    session: AsyncSession,
    *,
    org_id: str,
    key_id: str,
) -> bool:
    result = await session.execute(
        select(GatewayApiKey).where(GatewayApiKey.org_id == org_id, GatewayApiKey.id == key_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        return False
    await session.delete(row)
    await session.commit()
    return True


async def validate_stored_api_key(
    session: AsyncSession,
    raw_key: str,
) -> ApiKeyRecord | None:
    """Validate an API key by its raw token and return the matching record.

    TRUST BOUNDARY NOTE: This function searches cross-tenant by design.
    The key hash is the sole lookup mechanism — there is no org_id filter
    because the caller does not yet know which org the key belongs to.
    The ``org_id`` on the matched key becomes the authoritative tenant
    context for the rest of the request.  In cloud mode we reject keys
    whose org_id is missing or set to "local" to prevent accidental
    cross-tenant access to shared namespaces.
    """
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    # Search all keys (not org-scoped — validation doesn't know org yet)
    result = await session.execute(select(GatewayApiKey).where(GatewayApiKey.key_hash == key_hash))
    row = result.scalar_one_or_none()
    if not row:
        return None
    if not hmac.compare_digest(row.key_hash, key_hash):
        return None
    # In cloud mode, reject keys with missing or "local" org_id to prevent
    # a compromised/buggy key from granting access to the shared namespace.
    if is_cloud_mode() and (not row.org_id or row.org_id == "local"):
        logger.warning("Rejecting API key %s with invalid org_id in cloud mode", row.id)
        return None
    # Check expiry before allowing access
    if row.expires_at is not None:
        try:
            expiry = datetime.fromisoformat(row.expires_at)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
            if expiry <= datetime.now(UTC):
                return None
        except (ValueError, TypeError):
            return None  # Corrupt expiry data → treat as expired (fail closed)
    row.last_used_at = datetime.now(UTC).isoformat()
    await session.commit()
    return ApiKeyRecord(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        key_hash=row.key_hash,
        scopes=row.scopes,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        user_id=row.user_id,
        org_id=row.org_id,
    )
