"""Security status endpoint — admin-only encryption health check."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from ..db.models import GatewayCredential
from ..store import CURRENT_KEY_VERSION, _validate_encryption_health
from .deps import StoreD

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

_ADMIN_USER_IDS: frozenset[str] = frozenset(
    uid.strip()
    for uid in os.getenv("SP_ADMIN_USER_IDS", "local").split(",")
    if uid.strip()
)


def _require_admin(store: StoreD) -> None:
    """Raise 403 if the current user is not in the admin set."""
    if not store.user_id:
        raise HTTPException(status_code=403, detail="Admin access required.")
    uid = store.user_id
    if uid not in _ADMIN_USER_IDS:
        raise HTTPException(status_code=403, detail="Admin access required.")


@router.get("/security/status")
async def security_status(store: StoreD):
    """Return encryption health and credential storage statistics.

    Admin-only: accessible only to user IDs listed in SP_ADMIN_USER_IDS
    (defaults to "local" for single-user local deployments).
    """
    _require_admin(store)

    key_source = "environment" if os.getenv("SP_ENCRYPTION_KEY") else "auto-generated"
    encryption_healthy = _validate_encryption_health()

    # Count current user's own credentials
    result = await store.session.execute(
        select(func.count()).select_from(GatewayCredential).where(
            GatewayCredential.user_id == store.user_id
        )
    )
    credentials_encrypted = result.scalar_one()

    # Global count across all users (admin view)
    total_pending_rotation = await store.get_credentials_needing_rotation()

    logger.info(
        "Security status requested by user %s: healthy=%s, credentials=%d, pending_rotation=%d",
        store.user_id,
        encryption_healthy,
        credentials_encrypted,
        total_pending_rotation,
    )

    return {
        "encryption_algorithm": "Fernet (AES-128-CBC + HMAC-SHA256)",
        "key_source": key_source,
        "encryption_healthy": encryption_healthy,
        "credentials_encrypted": credentials_encrypted,
        "current_key_version": CURRENT_KEY_VERSION,
        "total_credentials_pending_rotation": total_pending_rotation,
    }
