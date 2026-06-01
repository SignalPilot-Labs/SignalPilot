"""User secrets endpoints — encrypted per-user API keys.

One row per user. Currently stores: Anthropic API key.
All values Fernet-encrypted at rest using the gateway's encryption key.
"""

import time

from fastapi import APIRouter
from pydantic import BaseModel

from ..security.scope_guard import RequireScope
from .deps import StoreD

router = APIRouter(prefix="/api/user")


def _mask_preview(key: str) -> str:
    """Return a safe prefix-only preview of an API key — never the trailing chars."""
    return f"{key[:8]}..." if len(key) >= 8 else "****"


class UserSecretsUpdate(BaseModel):
    anthropic_api_key: str | None = None


class UserSecretsResponse(BaseModel):
    has_anthropic_key: bool
    anthropic_key_preview: str | None = None
    updated_at: float | None = None


@router.get("/secrets", response_model=UserSecretsResponse, dependencies=[RequireScope("read")])
async def get_secrets(store: StoreD):
    """Get user's stored secrets (masked for display)."""
    from sqlalchemy import select

    from ..db.models import GatewayUserSecrets
    from ..store.crypto import _decrypt_with_migration, _encrypt

    org_id = store.org_id or "local"
    user_id = store.user_id or "local"

    result = await store.session.execute(
        select(GatewayUserSecrets).where(
            GatewayUserSecrets.org_id == org_id,
            GatewayUserSecrets.user_id == user_id,
        )
    )
    row = result.scalar_one_or_none()

    if not row or not row.anthropic_api_key_enc:
        return UserSecretsResponse(has_anthropic_key=False)

    try:
        key, needs_migration = _decrypt_with_migration(row.anthropic_api_key_enc)
        if needs_migration:
            row.anthropic_api_key_enc = _encrypt(key)
            await store.session.commit()
        preview = _mask_preview(key)
    except Exception:
        preview = "****"

    return UserSecretsResponse(
        has_anthropic_key=True,
        anthropic_key_preview=preview,
        updated_at=row.updated_at,
    )


@router.put("/secrets", response_model=UserSecretsResponse, dependencies=[RequireScope("write")])
async def update_secrets(body: UserSecretsUpdate, store: StoreD):
    """Store or update user secrets. Values are encrypted at rest."""
    from sqlalchemy import select

    from ..db.models import GatewayUserSecrets
    from ..store.crypto import _decrypt_with_migration, _encrypt

    org_id = store.org_id or "local"
    user_id = store.user_id or "local"
    now = time.time()

    result = await store.session.execute(
        select(GatewayUserSecrets).where(
            GatewayUserSecrets.org_id == org_id,
            GatewayUserSecrets.user_id == user_id,
        )
    )
    row = result.scalar_one_or_none()

    if not row:
        row = GatewayUserSecrets(org_id=org_id, user_id=user_id, updated_at=now)
        store.session.add(row)

    if body.anthropic_api_key is not None:
        if body.anthropic_api_key == "":
            row.anthropic_api_key_enc = None
        else:
            row.anthropic_api_key_enc = _encrypt(body.anthropic_api_key)

    row.updated_at = now
    await store.session.commit()

    has_key = row.anthropic_api_key_enc is not None
    preview = None
    if has_key and row.anthropic_api_key_enc is not None:
        try:
            key, needs_migration = _decrypt_with_migration(row.anthropic_api_key_enc)
            if needs_migration:
                row.anthropic_api_key_enc = _encrypt(key)
                await store.session.commit()
            preview = _mask_preview(key)
        except Exception:
            preview = "****"

    return UserSecretsResponse(
        has_anthropic_key=has_key,
        anthropic_key_preview=preview,
        updated_at=row.updated_at,
    )


async def get_user_anthropic_key(session, org_id: str, user_id: str) -> str | None:
    """Internal: get the decrypted Anthropic API key for pod injection."""
    from sqlalchemy import select

    from ..db.models import GatewayUserSecrets
    from ..store.crypto import _decrypt_with_migration, _encrypt

    result = await session.execute(
        select(GatewayUserSecrets).where(
            GatewayUserSecrets.org_id == org_id,
            GatewayUserSecrets.user_id == user_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row or not row.anthropic_api_key_enc:
        return None
    try:
        plaintext, needs_migration = _decrypt_with_migration(row.anthropic_api_key_enc)
        if needs_migration:
            row.anthropic_api_key_enc = _encrypt(plaintext)
            await session.commit()
        return plaintext
    except Exception:
        return None
