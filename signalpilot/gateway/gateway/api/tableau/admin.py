"""Tableau integration settings: one site + PAT per org (admin writes)."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ...auth import OrgAdmin
from ...common.ip import request_meta
from ...models import AuditEntry
from ...security.scope_guard import RequireScope
from ...store import tableau as tableau_store
from ...tableau import service as tableau_service
from ...tableau.client import TableauCredentials, TableauError, forget_token
from ...tableau.urls import TableauSiteUrlError, parse_site_url
from ..deps import StoreD

router = APIRouter(prefix="/api/tableau")
logger = logging.getLogger(__name__)


class TableauIntegrationUpdate(BaseModel):
    site_url: str = Field(min_length=1, max_length=2048)
    pat_name: str = Field(min_length=1, max_length=255)
    pat_secret: str | None = Field(default=None, max_length=4096)
    enabled: bool | None = None


class TableauIntegrationToggle(BaseModel):
    enabled: bool


class TableauIntegrationInfo(BaseModel):
    configured: bool
    enabled: bool
    active: bool
    server_url: str | None = None
    site_content_url: str | None = None
    site_url: str | None = None
    pat_name: str | None = None
    status: str | None = None
    last_error: str | None = None
    user_name: str | None = None
    site_role: str | None = None
    verified_at: float | None = None
    updated_at: float | None = None


def _org(store: StoreD) -> str:
    return store.org_id or "local"


async def _audit(store: StoreD, request: Request, event_type: str, metadata: dict) -> None:
    """Best-effort audit entry; never carries the PAT secret."""
    client_ip, user_agent = request_meta(request)
    try:
        await store.append_audit(
            AuditEntry(
                id=str(uuid.uuid4()),
                timestamp=time.time(),
                event_type=event_type,
                metadata=metadata,
                client_ip=client_ip,
                user_agent=user_agent,
            )
        )
    except Exception:
        logger.warning("Failed to append audit log for %s", event_type)


@router.get("/integration", response_model=TableauIntegrationInfo, dependencies=[RequireScope("read")])
async def get_tableau_integration(store: StoreD) -> TableauIntegrationInfo:
    """The org's Tableau integration status. Never returns the PAT secret."""
    row = await tableau_store.get_integration(store.session, _org(store))
    return TableauIntegrationInfo(**tableau_store.info_dict(row))


@router.put("/integration", response_model=TableauIntegrationInfo, dependencies=[RequireScope("admin")])
async def put_tableau_integration(
    body: TableauIntegrationUpdate, request: Request, store: StoreD, _role: OrgAdmin
) -> TableauIntegrationInfo:
    """Save the site URL + PAT after a successful sign-in. Nothing is saved on failure."""
    org_id = _org(store)
    try:
        site = parse_site_url(body.site_url)
    except TableauSiteUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    existing = await tableau_store.get_integration(store.session, org_id)
    secret = (body.pat_secret or "").strip()
    if not secret:
        if existing is None:
            raise HTTPException(status_code=400, detail="pat_secret is required when connecting Tableau")
        try:
            secret = await tableau_store.decrypt_secret(store.session, existing)
        except Exception:
            raise HTTPException(
                status_code=400, detail="The stored token cannot be read; enter the PAT secret again"
            ) from None
    creds = TableauCredentials(
        server_url=site.server_url,
        site_content_url=site.site_content_url,
        pat_name=body.pat_name.strip(),
        pat_secret=secret,
    )
    try:
        verified = await tableau_service.verify_credentials(creds, cache_key=org_id)
    except TableauError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from None
    row = await tableau_store.save_integration(
        store.session,
        org_id,
        server_url=creds.server_url,
        site_content_url=creds.site_content_url,
        pat_name=creds.pat_name,
        pat_secret=secret,
        enabled=body.enabled,
        site_id=verified.site_id,
        user_name=verified.user_name,
        site_role=verified.site_role,
        user_id=store.user_id,
    )
    await _audit(
        store,
        request,
        "tableau_integration_save",
        {"server_url": creds.server_url, "site_content_url": creds.site_content_url, "pat_name": creds.pat_name},
    )
    return TableauIntegrationInfo(**tableau_store.info_dict(row))


@router.post("/integration/test", response_model=TableauIntegrationInfo, dependencies=[RequireScope("admin")])
async def test_tableau_integration(request: Request, store: StoreD, _role: OrgAdmin) -> TableauIntegrationInfo:
    """Sign in again with the stored credentials and record the result."""
    org_id = _org(store)
    row = await tableau_store.get_integration(store.session, org_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Tableau is not connected")
    try:
        secret = await tableau_store.decrypt_secret(store.session, row)
    except Exception:
        await tableau_store.record_check(store.session, row, error="The stored token cannot be decrypted")
        return TableauIntegrationInfo(**tableau_store.info_dict(row))
    creds = TableauCredentials(row.server_url, row.site_content_url or "", row.pat_name, secret)
    try:
        verified = await tableau_service.verify_credentials(creds, cache_key=org_id)
    except TableauError as exc:
        await tableau_store.record_check(store.session, row, error=exc.message)
    else:
        await tableau_store.record_check(
            store.session,
            row,
            error=None,
            site_id=verified.site_id,
            user_name=verified.user_name,
            site_role=verified.site_role,
        )
    await _audit(store, request, "tableau_integration_test", {"status": row.status})
    return TableauIntegrationInfo(**tableau_store.info_dict(row))


@router.patch("/integration", response_model=TableauIntegrationInfo, dependencies=[RequireScope("admin")])
async def patch_tableau_integration(
    body: TableauIntegrationToggle, request: Request, store: StoreD, _role: OrgAdmin
) -> TableauIntegrationInfo:
    """Turn the integration on or off without re-entering the secret."""
    row = await tableau_store.get_integration(store.session, _org(store))
    if row is None:
        raise HTTPException(status_code=404, detail="Tableau is not connected")
    await tableau_store.set_enabled(store.session, row, body.enabled)
    await _audit(store, request, "tableau_integration_toggle", {"enabled": body.enabled})
    return TableauIntegrationInfo(**tableau_store.info_dict(row))


@router.delete("/integration", status_code=204, dependencies=[RequireScope("admin")])
async def delete_tableau_integration(request: Request, store: StoreD, _role: OrgAdmin) -> Response:
    """Disconnect: sign out the cached session and delete the row."""
    org_id = _org(store)
    row = await tableau_store.get_integration(store.session, org_id)
    if row is not None:
        try:
            secret = await tableau_store.decrypt_secret(store.session, row)
            creds = TableauCredentials(row.server_url, row.site_content_url or "", row.pat_name, secret)
            async with tableau_service.make_client(creds, cache_key=org_id) as client:
                await client.sign_out()
        except Exception:
            logger.info("tableau sign-out on disconnect failed for org=%s", org_id)
        await tableau_store.delete_integration(store.session, org_id)
        await _audit(store, request, "tableau_integration_delete", {"server_url": row.server_url})
    forget_token(org_id)
    return Response(status_code=204)
