"""Org secrets endpoints — encrypted org-scoped API keys."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from ..db.models import GatewayOrgSecrets
from ..security.scope_guard import RequireScope
from ..store import org_secrets as org_secrets_store
from ..store.crypto import _decrypt_with_migration, _encrypt
from .deps import StoreD

router = APIRouter(prefix="/api/org")


def _mask_preview(key: str) -> str:
    """Return a safe prefix-only preview of an API key — never the trailing chars."""
    return f"{key[:8]}..." if len(key) >= 8 else "****"


class OrgSecretsUpdate(BaseModel):
    anthropic_api_key: str | None = None


class OrgSecretsResponse(BaseModel):
    has_key: bool
    key_preview: str | None = None
    updated_at: float | None = None


async def _get_org_secret_row(store: StoreD, org_id: str) -> GatewayOrgSecrets | None:
    result = await store.session.execute(select(GatewayOrgSecrets).where(GatewayOrgSecrets.org_id == org_id))
    return result.scalar_one_or_none()


async def _response_for_row(store: StoreD, org_id: str) -> OrgSecretsResponse:
    row = await _get_org_secret_row(store, org_id)
    if not row or not row.anthropic_api_key_enc:
        return OrgSecretsResponse(
            has_key=False,
            updated_at=row.updated_at if row else None,
        )

    try:
        key, needs_migration = _decrypt_with_migration(row.anthropic_api_key_enc)
        if needs_migration:
            row.anthropic_api_key_enc = _encrypt(key)
            await store.session.commit()
        return OrgSecretsResponse(
            has_key=True,
            key_preview=_mask_preview(key),
            updated_at=row.updated_at,
        )
    except Exception:
        return OrgSecretsResponse(has_key=False, updated_at=row.updated_at)


@router.get("/secrets", response_model=OrgSecretsResponse, dependencies=[RequireScope("read")])
async def get_org_secrets(store: StoreD) -> OrgSecretsResponse:
    """Get org-scoped secrets metadata, with secret values masked."""
    org_id = store.org_id or "local"
    return await _response_for_row(store, org_id)


@router.put("/secrets", response_model=OrgSecretsResponse, dependencies=[RequireScope("write")])
async def update_org_secrets(body: OrgSecretsUpdate, store: StoreD) -> OrgSecretsResponse:
    """Store, rotate, or clear org-scoped secrets. Values are encrypted at rest."""
    org_id = store.org_id or "local"
    key = body.anthropic_api_key.strip() if body.anthropic_api_key is not None else ""
    if key:
        await org_secrets_store.set_org_anthropic_key(store.session, org_id, key)
    else:
        await org_secrets_store.clear_org_anthropic_key(store.session, org_id)
    return await _response_for_row(store, org_id)
