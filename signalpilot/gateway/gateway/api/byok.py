"""BYOK key management and migration API endpoints.

All endpoints require admin scope. Key queries are org-scoped (not user-scoped).
org_id is always derived from the JWT via the OrgID dependency — never from
user-supplied query params or request body.
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import DBSession, OrgID, UserID
from ..byok import (
    BYOKKeyError,
    decrypt_envelope,
    encrypt_envelope,
    migrate_to_byok,
    revert_to_managed,
    rotate_byok_key,
)
from ..db.models import GatewayBYOKKey, GatewayConnection, GatewayCredential, GatewayOrg
from ..models import (
    BYOKKeyCreate,
    BYOKKeyResponse,
    BYOKKeyUpdate,
    BYOKMigrateRequest,
    BYOKMigrateResponse,
    BYOKMigrationStatusResponse,
    BYOKRotateRequest,
    BYOKRotateResponse,
)
from ..scope_guard import RequireScope
from ..store import _decrypt_with_migration, _encrypt
from .deps import StoreD
from sqlalchemy import func, select

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

BYOK_HEALTH_CHECK_PLAINTEXT = "byok-health-check"


def _key_to_response(key: GatewayBYOKKey) -> BYOKKeyResponse:
    return BYOKKeyResponse(
        id=key.id,
        org_id=key.org_id,
        key_alias=key.key_alias,
        provider_type=key.provider_type,
        provider_config=None,
        status=key.status,
        created_at=key.created_at,
        revoked_at=key.revoked_at,
    )


async def _upsert_org(session: AsyncSession, org_id: str) -> None:
    """Ensure a GatewayOrg row exists for org_id with byok_enabled=True."""
    result = await session.execute(
        select(GatewayOrg).where(GatewayOrg.org_id == org_id)
    )
    org_row = result.scalar_one_or_none()
    if org_row is None:
        session.add(GatewayOrg(
            org_id=org_id,
            byok_enabled=True,
            created_at=time.time(),
        ))
    else:
        org_row.byok_enabled = True
    await session.commit()


@router.post("/byok/keys", dependencies=[RequireScope("admin")])
async def create_byok_key(
    body: BYOKKeyCreate,
    db: DBSession,
    _user_id: UserID,
    org_id: OrgID,
) -> BYOKKeyResponse:
    """Register a BYOK key for an org. org_id is derived from JWT, not body."""
    # Check uniqueness
    existing = await db.execute(
        select(GatewayBYOKKey).where(
            GatewayBYOKKey.org_id == org_id,
            GatewayBYOKKey.key_alias == body.key_alias,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail="BYOK key with this alias already exists",
        )

    key_id = str(uuid.uuid4())
    key = GatewayBYOKKey(
        id=key_id,
        org_id=org_id,
        key_alias=body.key_alias,
        provider_type=body.provider_type,
        provider_config=body.provider_config,
        status="active",
        created_at=time.time(),
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)

    await _upsert_org(db, org_id)
    await db.refresh(key)

    return _key_to_response(key)


@router.get("/byok/keys", dependencies=[RequireScope("admin")])
async def list_byok_keys(
    db: DBSession,
    _user_id: UserID,
    org_id: OrgID,
) -> list[BYOKKeyResponse]:
    """List BYOK keys for the org derived from JWT."""
    query = select(GatewayBYOKKey).where(GatewayBYOKKey.org_id == org_id)
    result = await db.execute(query)
    return [_key_to_response(k) for k in result.scalars()]


@router.get("/byok/keys/{key_id}", dependencies=[RequireScope("admin")])
async def get_byok_key(
    key_id: str,
    db: DBSession,
    _user_id: UserID,
    org_id: OrgID,
) -> BYOKKeyResponse:
    """Get a single BYOK key by ID, scoped to the org derived from JWT."""
    result = await db.execute(
        select(GatewayBYOKKey).where(GatewayBYOKKey.id == key_id)
    )
    key = result.scalar_one_or_none()
    if key is None or key.org_id != org_id:
        raise HTTPException(status_code=404, detail="Key not found")
    return _key_to_response(key)


@router.put("/byok/keys/{key_id}", dependencies=[RequireScope("admin")])
async def update_byok_key(
    key_id: str,
    body: BYOKKeyUpdate,
    db: DBSession,
    _user_id: UserID,
    org_id: OrgID,
) -> BYOKKeyResponse:
    """Update a BYOK key's alias or status, scoped to the org derived from JWT."""
    result = await db.execute(
        select(GatewayBYOKKey).where(GatewayBYOKKey.id == key_id)
    )
    key = result.scalar_one_or_none()
    if key is None or key.org_id != org_id:
        raise HTTPException(status_code=404, detail="Key not found")

    if body.key_alias is not None:
        key.key_alias = body.key_alias
    if body.status is not None:
        key.status = body.status
        if body.status == "revoked" and key.revoked_at is None:
            key.revoked_at = time.time()

    await db.commit()
    await db.refresh(key)
    return _key_to_response(key)


@router.delete("/byok/keys/{key_id}", dependencies=[RequireScope("admin")])
async def delete_byok_key(
    key_id: str,
    db: DBSession,
    _user_id: UserID,
    org_id: OrgID,
) -> Response:
    """Delete a BYOK key. Returns 409 if key is in use by credentials."""
    result = await db.execute(
        select(GatewayBYOKKey).where(GatewayBYOKKey.id == key_id)
    )
    key = result.scalar_one_or_none()
    if key is None or key.org_id != org_id:
        raise HTTPException(status_code=404, detail="Key not found")

    cred_result = await db.execute(
        select(GatewayCredential).where(GatewayCredential.byok_key_id == key_id)
    )
    credentials_using_key = cred_result.scalars().all()
    if credentials_using_key:
        count = len(credentials_using_key)
        logger.warning("Cannot delete key %s: in use by %d credential(s)", key_id, count)
        raise HTTPException(
            status_code=409,
            detail="Key is in use by existing credentials and cannot be deleted",
        )

    await db.delete(key)
    await db.commit()
    return Response(status_code=204)


@router.post("/byok/keys/{key_id}/validate", dependencies=[RequireScope("admin")])
async def validate_byok_key(
    key_id: str,
    db: DBSession,
    _user_id: UserID,
    org_id: OrgID,
) -> dict:
    """Round-trip encrypt/decrypt test for a BYOK key, scoped to the org from JWT."""
    from ..store import _byok_provider as provider

    if provider is None:
        raise HTTPException(status_code=503, detail="BYOK provider not configured")

    result = await db.execute(
        select(GatewayBYOKKey).where(GatewayBYOKKey.id == key_id)
    )
    key = result.scalar_one_or_none()
    if key is None or key.org_id != org_id:
        raise HTTPException(status_code=404, detail="Key not found")

    try:
        ciphertext, wrapped_dek = await encrypt_envelope(
            provider, key.org_id, key.key_alias, BYOK_HEALTH_CHECK_PLAINTEXT
        )
        recovered = await decrypt_envelope(
            provider, key.org_id, key.key_alias, wrapped_dek, ciphertext
        )
        if recovered != BYOK_HEALTH_CHECK_PLAINTEXT:
            return {"valid": False, "error": "Round-trip produced incorrect plaintext"}
        return {"valid": True}
    except BYOKKeyError as exc:
        logger.warning(
            "BYOK key validation failed for key_id=%s: %s", key_id, exc
        )
        return {"valid": False, "error": "Key validation failed"}
    except Exception:
        logger.exception("BYOK key validation failed for key_id=%s", key_id)
        return {"valid": False, "error": "Validation failed due to an internal error"}


@router.post("/byok/migrate", dependencies=[RequireScope("admin")])
async def migrate_credentials_to_byok(
    body: BYOKMigrateRequest,
    store: StoreD,
    org_id: OrgID,
) -> BYOKMigrateResponse:
    """Migrate org credentials from managed to BYOK encryption.

    org_id is derived from JWT, not the request body.
    """
    from ..store import _byok_provider as provider

    if provider is None:
        raise HTTPException(status_code=503, detail="BYOK provider not configured")

    result = await store.session.execute(
        select(GatewayBYOKKey).where(
            GatewayBYOKKey.id == body.key_id,
            GatewayBYOKKey.status == "active",
        )
    )
    key = result.scalar_one_or_none()
    if key is None or key.org_id != org_id:
        raise HTTPException(
            status_code=404,
            detail="Active BYOK key not found",
        )

    migrated, failed, errors = await migrate_to_byok(
        session=store.session,
        provider=provider,
        org_id=org_id,
        key_id=body.key_id,
        key_alias=key.key_alias,
        managed_decrypt=_decrypt_with_migration,
    )
    return BYOKMigrateResponse(migrated=migrated, failed=failed, errors=errors)


@router.post("/byok/revert", dependencies=[RequireScope("admin")])
async def revert_credentials_to_managed(
    store: StoreD,
    org_id: OrgID,
) -> BYOKMigrateResponse:
    """Revert org credentials from BYOK back to managed encryption.

    org_id is derived from JWT, not the request body.
    """
    from ..store import _byok_provider as provider, _dek_cache as cache

    if provider is None:
        raise HTTPException(status_code=503, detail="BYOK provider not configured")

    org_result = await store.session.execute(
        select(GatewayOrg).where(GatewayOrg.org_id == org_id)
    )
    if org_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    migrated, failed, errors = await revert_to_managed(
        session=store.session,
        provider=provider,
        org_id=org_id,
        managed_encrypt=_encrypt,
        cache=cache,
    )
    return BYOKMigrateResponse(migrated=migrated, failed=failed, errors=errors)


@router.post("/byok/keys/{key_id}/rotate", dependencies=[RequireScope("admin")])
async def rotate_byok_key_endpoint(
    key_id: str,
    body: BYOKRotateRequest,
    store: StoreD,
    org_id: OrgID,
) -> BYOKRotateResponse:
    """Rotate credentials from one BYOK key to another.

    org_id is derived from JWT. key_id is the OLD key to rotate FROM.
    """
    from ..store import _byok_provider as provider, _dek_cache as cache

    if provider is None:
        raise HTTPException(status_code=503, detail="BYOK provider not configured")

    if body.new_key_id == key_id:
        raise HTTPException(status_code=400, detail="new_key_id must differ from key_id")

    old_key_result = await store.session.execute(
        select(GatewayBYOKKey).where(GatewayBYOKKey.id == key_id)
    )
    old_key = old_key_result.scalar_one_or_none()
    if old_key is None or old_key.org_id != org_id or old_key.status not in ("active", "rotating"):
        raise HTTPException(status_code=404, detail="Key not found")

    new_key_result = await store.session.execute(
        select(GatewayBYOKKey).where(GatewayBYOKKey.id == body.new_key_id)
    )
    new_key = new_key_result.scalar_one_or_none()
    if new_key is None or new_key.org_id != org_id or new_key.status != "active":
        raise HTTPException(status_code=404, detail="Target key not found")

    old_key.status = "rotating"
    await store.session.commit()

    try:
        rotated, failed, errors = await rotate_byok_key(
            session=store.session,
            provider=provider,
            org_id=org_id,
            old_key_id=key_id,
            old_key_alias=old_key.key_alias,
            new_key_id=body.new_key_id,
            new_key_alias=new_key.key_alias,
            cache=cache,
        )

        if failed == 0:
            old_key.status = "inactive"
            await store.session.commit()
    except Exception:
        old_key.status = "active"
        await store.session.commit()
        raise

    return BYOKRotateResponse(rotated=rotated, failed=failed, errors=errors)


@router.get("/byok/migrate/status", dependencies=[RequireScope("admin")])
async def get_migration_status(
    db: DBSession,
    _user_id: UserID,
    org_id: OrgID,
) -> BYOKMigrationStatusResponse:
    """Return migration status for org credentials.

    Counts credentials by encryption_mode and derives a status string.
    """
    result = await db.execute(
        select(func.count(), GatewayCredential.encryption_mode)
        .join(
            GatewayConnection,
            (GatewayConnection.user_id == GatewayCredential.user_id)
            & (GatewayConnection.name == GatewayCredential.connection_name),
        )
        .where(GatewayConnection.org_id == org_id)
        .group_by(GatewayCredential.encryption_mode)
    )
    rows = result.all()

    byok_count = 0
    managed_count = 0
    for count, mode in rows:
        if mode == "byok":
            byok_count = count
        else:
            managed_count += count

    total = byok_count + managed_count

    if total == 0 or byok_count == 0:
        status = "none"
    elif managed_count == 0:
        status = "complete"
    else:
        status = "partial"

    return BYOKMigrationStatusResponse(
        total=total,
        byok=byok_count,
        managed=managed_count,
        status=status,
    )
