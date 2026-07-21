"""Org secrets endpoints — encrypted org-scoped API keys."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from ..db.models import GatewayOrgSecrets
from ..notebooks import session_service
from ..security.scope_guard import RequireScope
from ..store import notebook_sessions as ns
from ..store import org_secrets as org_secrets_store
from ..store.crypto import _decrypt_with_migration, _encrypt
from .deps import StoreD

router = APIRouter(prefix="/api/org")
logger = logging.getLogger(__name__)
_get_orchestrator = session_service._get_orchestrator


def _mask_preview(key: str) -> str:
    """Return a safe prefix-only preview of an API key — never the trailing chars."""
    return f"{key[:8]}..." if len(key) >= 8 else "****"


class OrgSecretsUpdate(BaseModel):
    anthropic_api_key: str | None = None


class OrgSecretsResponse(BaseModel):
    has_key: bool
    key_preview: str | None = None
    updated_at: float | None = None


class OrgAnthropicKeyResponse(BaseModel):
    anthropic_api_key: str


def _require_runtime_secret_access(request: Request) -> None:
    auth = getattr(request.state, "auth", None)
    if auth and auth.get("auth_method") in ("notebook_session", "local_key", "local_nokey"):
        return
    raise HTTPException(status_code=403, detail="Runtime secret access required")


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


async def _stop_active_notebook_sessions_for_org(store: StoreD, org_id: str) -> int:
    sessions = await ns.list_active_sessions_for_org(store.session, org_id=org_id)
    if not sessions:
        return 0

    orch = None
    if not os.getenv("SP_NOTEBOOK_DIRECT_URL", "").strip():
        try:
            orch = await _get_orchestrator()
        except Exception:
            logger.warning(
                "Could not initialize notebook orchestrator while rotating org secrets",
                exc_info=True,
            )

    stopped = 0
    try:
        for notebook_session in sessions:
            if orch and notebook_session.pod_name:
                try:
                    await orch.delete_pod(notebook_session.pod_name, org_id=org_id)
                except Exception:
                    logger.warning(
                        "Could not delete notebook pod %s after org secret update",
                        notebook_session.pod_name,
                        exc_info=True,
                    )
            await ns.mark_stopped(
                store.session,
                session_id=notebook_session.id,
                org_id=notebook_session.org_id,
            )
            stopped += 1
    finally:
        if orch:
            try:
                await orch.close()
            except Exception:
                logger.debug("Could not close notebook orchestrator", exc_info=True)

    return stopped


@router.get("/secrets", response_model=OrgSecretsResponse, dependencies=[RequireScope("read")])
async def get_org_secrets(store: StoreD) -> OrgSecretsResponse:
    """Get org-scoped secrets metadata, with secret values masked."""
    org_id = store.org_id or "local"
    return await _response_for_row(store, org_id)


@router.get("/secrets/anthropic-key", response_model=OrgAnthropicKeyResponse, dependencies=[RequireScope("execute")])
async def get_org_anthropic_key_for_runtime(request: Request, store: StoreD) -> OrgAnthropicKeyResponse:
    """Return the org Anthropic key to a trusted notebook runtime only."""
    _require_runtime_secret_access(request)
    org_id = store.org_id or "local"
    key = await org_secrets_store.resolve_anthropic_key(store.session, org_id)
    if not key:
        raise HTTPException(status_code=404, detail="Anthropic key not configured")
    return OrgAnthropicKeyResponse(anthropic_api_key=key)


@router.put("/secrets", response_model=OrgSecretsResponse, dependencies=[RequireScope("write")])
async def update_org_secrets(body: OrgSecretsUpdate, store: StoreD) -> OrgSecretsResponse:
    """Store, rotate, or clear org-scoped secrets. Values are encrypted at rest."""
    org_id = store.org_id or "local"
    key = body.anthropic_api_key.strip() if body.anthropic_api_key is not None else ""
    if key:
        await org_secrets_store.set_org_anthropic_key(store.session, org_id, key)
    else:
        await org_secrets_store.clear_org_anthropic_key(store.session, org_id)
    stopped = await _stop_active_notebook_sessions_for_org(store, org_id)
    if stopped:
        logger.info("Stopped %d active notebook session(s) after org secret update", stopped)
    return await _response_for_row(store, org_id)
