"""Security status endpoint — admin-only encryption health check."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, or_, select

from ..auth import OrgAdmin, OrgID
from ..config import get_governance_settings
from ..db.models import GatewayBYOKKey, GatewayCredential
from ..store import CURRENT_KEY_VERSION
from ..store.crypto import _validate_encryption_health
from .deps import StoreD

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

_ADMIN_USER_IDS: frozenset[str] = get_governance_settings().admin_user_ids


def _require_admin(store: StoreD) -> None:
    """Raise 403 if the current user is not in the admin set."""
    if not store.user_id:
        raise HTTPException(status_code=403, detail="Admin access required.")
    uid = store.user_id
    if uid not in _ADMIN_USER_IDS:
        raise HTTPException(status_code=403, detail="Admin access required.")


@router.get("/security/status")
async def security_status(store: StoreD, org_id: OrgID, _role: OrgAdmin):
    """Return encryption health and credential storage statistics.

    Admin-only: accessible only to user IDs listed in SP_ADMIN_USER_IDS
    (defaults to "local" for single-user local deployments).
    """
    _require_admin(store)

    key_source = "environment" if os.getenv("SP_ENCRYPTION_KEY") else "auto-generated"
    encryption_healthy = _validate_encryption_health()

    # Count current org's credentials
    result = await store.session.execute(
        select(func.count()).select_from(GatewayCredential).where(GatewayCredential.org_id == store.org_id)
    )
    credentials_encrypted = result.scalar_one()

    # Global count across all users (admin view)
    total_pending_rotation = await store.get_credentials_needing_rotation()

    # ─── BYOK provider info ───────────────────────────────────────────────────

    # Read the module-level provider — import at function scope to pick up the
    # current value (configure_byok may have been called after module import).
    from ..store.byok_state import _byok_provider as current_provider

    byok_provider_type = type(current_provider).__name__ if current_provider is not None else "none"

    # ─── BYOK key counts ──────────────────────────────────────────────────────

    active_result = await store.session.execute(
        select(func.count())
        .select_from(GatewayBYOKKey)
        .where(
            GatewayBYOKKey.status == "active",
            GatewayBYOKKey.org_id == org_id,
        )
    )
    byok_keys_active: int = active_result.scalar_one()

    revoked_result = await store.session.execute(
        select(func.count())
        .select_from(GatewayBYOKKey)
        .where(
            GatewayBYOKKey.status == "revoked",
            GatewayBYOKKey.org_id == org_id,
        )
    )
    byok_keys_revoked: int = revoked_result.scalar_one()

    byok_keys_total = byok_keys_active + byok_keys_revoked

    # ─── Credential encryption mode counts ───────────────────────────────────

    # Treat NULL encryption_mode as "managed" — pre-BYOK rows may have NULL
    # if the server_default was not applied retroactively.
    managed_result = await store.session.execute(
        select(func.count())
        .select_from(GatewayCredential)
        .where(
            GatewayCredential.org_id == store.org_id,
            or_(
                GatewayCredential.encryption_mode == "managed",
                GatewayCredential.encryption_mode.is_(None),
            ),
        )
    )
    credentials_managed: int = managed_result.scalar_one()

    byok_result = await store.session.execute(
        select(func.count())
        .select_from(GatewayCredential)
        .where(
            GatewayCredential.org_id == store.org_id,
            GatewayCredential.encryption_mode == "byok",
        )
    )
    credentials_byok: int = byok_result.scalar_one()

    logger.info(
        "Security status requested by org %s user %s: healthy=%s, credentials=%d, "
        "pending_rotation=%d, byok_provider=%s, byok_keys_total=%d",
        store.org_id,
        store.user_id,
        encryption_healthy,
        credentials_encrypted,
        total_pending_rotation,
        byok_provider_type,
        byok_keys_total,
    )

    return {
        "encryption_algorithm": "Fernet (AES-128-CBC + HMAC-SHA256)",
        "key_source": key_source,
        "encryption_healthy": encryption_healthy,
        "credentials_encrypted": credentials_encrypted,
        "current_key_version": CURRENT_KEY_VERSION,
        "total_credentials_pending_rotation": total_pending_rotation,
        "byok_provider": byok_provider_type,
        "byok_keys_total": byok_keys_total,
        "byok_keys_active": byok_keys_active,
        "byok_keys_revoked": byok_keys_revoked,
        "credentials_managed": credentials_managed,
        "credentials_byok": credentials_byok,
    }
