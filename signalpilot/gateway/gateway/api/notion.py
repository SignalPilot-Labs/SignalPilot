"""Notion integration CRUD and test endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api.deps import StoreD
from gateway.auth import OrgAdmin
from gateway.db.engine import get_db, get_session_factory
from gateway.models.notion import (
    NotionIntegrationCreate,
    NotionIntegrationInfo,
    NotionIntegrationUpdate,
    NotionOAuthInstallationInfo,
    NotionOAuthStartResponse,
    NotionPageOption,
    NotionProvisionRequest,
    NotionProvisionResponse,
    NotionWebhookResponse,
)
from gateway.notion import analysis as notion_analysis
from gateway.notion import client as notion_client
from gateway.notion import webhooks as notion_webhooks
from gateway.notion.client import test_connection
from gateway.security.scope_guard import RequireScope
from gateway.store import Store
from gateway.store import notion as notion_store

router = APIRouter(prefix="/api/integrations/notion")
webhook_router = APIRouter(prefix="/api/notion")
logger = logging.getLogger(__name__)
_notion_event_tasks: set[asyncio.Task[None]] = set()


def _notion_oauth_client_id() -> str:
    value = os.getenv("NOTION_OAUTH_CLIENT_ID")
    if not value:
        raise HTTPException(status_code=503, detail="NOTION_OAUTH_CLIENT_ID is not configured")
    return value


def _notion_oauth_client_secret() -> str:
    value = os.getenv("NOTION_OAUTH_CLIENT_SECRET")
    if not value:
        raise HTTPException(status_code=503, detail="NOTION_OAUTH_CLIENT_SECRET is not configured")
    return value


def _notion_redirect_uri(request: Request) -> str:
    return os.getenv("NOTION_OAUTH_REDIRECT_URI") or str(request.url_for("notion_oauth_callback"))


def _webhook_verification_token() -> str | None:
    value = os.getenv("NOTION_WEBHOOK_VERIFICATION_TOKEN") or os.getenv("WEBHOOK_VERIFICATION_TOKEN")
    if value:
        return value
    if os.getenv("SP_DEPLOYMENT_MODE", "local").lower() != "cloud":
        return None
    raise HTTPException(status_code=503, detail="NOTION_WEBHOOK_VERIFICATION_TOKEN is not configured")


def _redirect_fallback_url() -> str:
    web_url = os.getenv("SIGNALPILOT_WEB_URL") or os.getenv("SP_WEB_URL")
    if web_url:
        return f"{web_url.rstrip('/')}/integrations"
    return "/integrations"


def _origin_for_url(value: str) -> str | None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _allowed_redirect_origins() -> set[str]:
    origins: set[str] = set()
    for value in (os.getenv("SIGNALPILOT_WEB_URL"), os.getenv("SP_WEB_URL")):
        if value and (origin := _origin_for_url(value)):
            origins.add(origin)
    for value in (os.getenv("SP_ALLOWED_ORIGINS") or "").split(","):
        if value and (origin := _origin_for_url(value.strip())):
            origins.add(origin)
    if not origins:
        origins.update(
            {
                "http://localhost:3000",
                "http://localhost:3200",
                "http://localhost:3210",
                "http://127.0.0.1:3000",
                "http://127.0.0.1:3200",
                "http://127.0.0.1:3210",
            }
        )
    return origins


def _is_safe_redirect_target(target: str) -> bool:
    if not target or target.startswith(("//", "\\")):
        return False
    parsed = urlparse(target)
    if not parsed.scheme and not parsed.netloc:
        return target.startswith("/")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    return _origin_for_url(target) in _allowed_redirect_origins()


def _safe_redirect_url(value: str | None, installation_id: str | None = None, status: str = "connected") -> str:
    fallback = _redirect_fallback_url()
    target = value or fallback
    if not _is_safe_redirect_target(target):
        target = fallback if _is_safe_redirect_target(fallback) else "/integrations"

    parsed = urlparse(target)
    params = {"notion": status}
    if installation_id:
        params["installation_id"] = installation_id
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.extend(params.items())
    return urlunparse(parsed._replace(query=urlencode(query)))


async def _refresh_installation_token(store: Store, installation_id: str) -> str | None:
    tokens = await store.get_notion_oauth_installation_tokens(installation_id)
    if tokens is None:
        return None
    _, refresh_token = tokens
    if not refresh_token:
        return None
    response = await notion_client.refresh_oauth_token(
        _notion_oauth_client_id(),
        _notion_oauth_client_secret(),
        refresh_token,
    )
    access_token = response.get("access_token")
    if not access_token:
        return None
    await store.update_notion_oauth_installation_tokens(
        installation_id,
        str(access_token),
        response.get("refresh_token") or refresh_token,
    )
    return str(access_token)


async def _run_notion_operation_with_refresh(store: Store, installation_id: str, operation):
    token = await store.get_notion_oauth_installation_token(installation_id)
    if not token:
        raise HTTPException(status_code=404, detail="Notion installation not found")
    try:
        return await operation(token)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 401:
            raise
        refreshed = await _refresh_installation_token(store, installation_id)
        if not refreshed:
            raise
        return await operation(refreshed)


async def _process_notion_event_task(event_id: str, installation_id: str, payload: dict) -> None:
    factory = get_session_factory()
    async with factory() as session:
        record = await notion_store.get_installation_record(session, installation_id)
        if record is None:
            await notion_store.record_webhook_delivery(
                session,
                event_id,
                status="failed",
                installation_id=installation_id,
                error="Notion installation disappeared before processing",
                processed=True,
            )
            return
        installation, config, token = record
        if config is None:
            await notion_store.record_webhook_delivery(
                session,
                event_id,
                status="failed",
                installation_id=installation_id,
                org_id=installation.org_id,
                error="Notion installation is not provisioned",
                processed=True,
            )
            return
        routed = notion_webhooks.RoutedNotionInstallation(installation=installation, config=config, access_token=token)
        try:
            result = await notion_analysis.process_routed_comment_event(routed, payload)
        except Exception as exc:
            await notion_store.record_webhook_delivery(
                session,
                event_id,
                status="failed",
                installation_id=installation_id,
                org_id=installation.org_id,
                error=str(exc)[:1000],
                processed=True,
            )
            return
        if result.status == "ignored":
            await notion_store.record_webhook_delivery(
                session,
                event_id,
                status="ignored",
                installation_id=installation_id,
                org_id=installation.org_id,
                error=result.reason,
                processed=True,
            )
            return
        await notion_store.record_webhook_delivery(
            session,
            event_id,
            status="processed",
            installation_id=installation_id,
            org_id=installation.org_id,
            processed=True,
        )


def _handle_notion_event_task_done(event_id: str, task: asyncio.Task[None]) -> None:
    _notion_event_tasks.discard(task)
    try:
        task.result()
    except asyncio.CancelledError:
        logger.warning("Notion webhook processing task cancelled (event_id=%s)", event_id)
    except Exception as exc:
        logger.error(
            "Unhandled Notion webhook processing task failure (event_id=%s)",
            event_id,
            exc_info=(type(exc), exc, exc.__traceback__),
        )


def _schedule_notion_event_processing(event_id: str, installation_id: str, payload: dict) -> None:
    task = asyncio.create_task(
        _process_notion_event_task(event_id, installation_id, payload),
        name=f"notion-webhook-{event_id}",
    )
    _notion_event_tasks.add(task)
    task.add_done_callback(lambda completed: _handle_notion_event_task_done(event_id, completed))


@router.get("/oauth/start", dependencies=[RequireScope("write")])
async def start_notion_oauth(
    request: Request,
    store: StoreD,
    _role: OrgAdmin,
    redirect_after: str | None = Query(default=None),
) -> NotionOAuthStartResponse:
    """Create OAuth state and return the Notion authorization URL."""
    redirect_uri = _notion_redirect_uri(request)
    state = await store.create_notion_oauth_state(redirect_after=redirect_after)
    return NotionOAuthStartResponse(
        authorize_url=notion_client.build_authorize_url(_notion_oauth_client_id(), redirect_uri, state),
        state=state,
    )


@router.get("/oauth/callback", name="notion_oauth_callback")
async def notion_oauth_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """OAuth callback from Notion. Tenant context comes from the stored state row."""
    if error:
        raise HTTPException(status_code=400, detail=f"Notion OAuth failed: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing Notion OAuth code or state")

    state_row = await notion_store.consume_oauth_state(db, state)
    if state_row is None:
        raise HTTPException(status_code=400, detail="Invalid or expired Notion OAuth state")

    token_response = await notion_client.exchange_oauth_code(
        _notion_oauth_client_id(),
        _notion_oauth_client_secret(),
        code,
        _notion_redirect_uri(request),
    )
    installation = await notion_store.upsert_oauth_installation(
        db,
        org_id=state_row.org_id,
        user_id=state_row.user_id,
        token_response=token_response,
    )
    return RedirectResponse(_safe_redirect_url(state_row.redirect_after, installation.id, "connected"))


@router.get("/oauth/installations", dependencies=[RequireScope("read")])
async def list_notion_oauth_installations(store: StoreD) -> list[NotionOAuthInstallationInfo]:
    """List Notion OAuth installations for the current org."""
    return await store.list_notion_oauth_installations()


@router.get("/oauth/{installation_id}/pages", dependencies=[RequireScope("read")])
async def list_notion_oauth_pages(
    installation_id: str,
    store: StoreD,
    query: str | None = Query(default=None, max_length=100),
) -> list[NotionPageOption]:
    """List pages visible to an OAuth installation for parent-page setup."""

    async def _operation(token: str):
        return await notion_client.list_parent_pages(token, query=query)

    try:
        pages = await _run_notion_operation_with_refresh(store, installation_id, _operation)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text[:500]) from exc
    return [NotionPageOption(**page) for page in pages]


@router.post("/oauth/{installation_id}/provision", dependencies=[RequireScope("write")])
async def provision_notion_oauth_installation(
    installation_id: str,
    body: NotionProvisionRequest,
    store: StoreD,
    _role: OrgAdmin,
) -> NotionProvisionResponse:
    """Provision the SignalPilot trigger page and Requests database.

    By default the resources are created at workspace level in the installing
    user's private Notion section. A parent_page_id can still be supplied for
    the older advanced setup path.
    """

    async def _operation(token: str):
        return await notion_client.provision_signalpilot_resources(token, body.parent_page_id)

    try:
        provisioned = await _run_notion_operation_with_refresh(store, installation_id, _operation)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text[:500]) from exc

    installation = await store.save_notion_oauth_installation_config(
        installation_id,
        parent_page_id=provisioned["parent_page_id"],
        trigger_page_id=provisioned["trigger_page_id"],
        requests_data_source_id=provisioned["requests_data_source_id"],
        requests_database_page_id=provisioned["requests_database_page_id"],
        enabled=True,
    )
    if installation is None:
        raise HTTPException(status_code=404, detail="Notion installation not found")
    return NotionProvisionResponse(
        installation=installation,
        trigger_page_id=provisioned["trigger_page_id"],
        requests_data_source_id=provisioned["requests_data_source_id"],
        requests_database_page_id=provisioned["requests_database_page_id"],
    )


@router.delete("/oauth/{installation_id}", status_code=204, dependencies=[RequireScope("write")])
async def delete_notion_oauth_installation(
    installation_id: str,
    store: StoreD,
    _role: OrgAdmin,
) -> None:
    """Disable an OAuth installation without deleting historical delivery records."""
    if not await store.disable_notion_oauth_installation(installation_id):
        raise HTTPException(status_code=404, detail="Notion installation not found")


@router.get("", dependencies=[RequireScope("read")])
async def list_notion_integrations(store: StoreD) -> list[NotionIntegrationInfo]:
    """List all Notion integrations."""
    return await store.list_notion_integrations()


@router.post("", status_code=201, dependencies=[RequireScope("write")])
async def create_notion_integration(
    integration: NotionIntegrationCreate,
    store: StoreD,
    _role: OrgAdmin,
) -> NotionIntegrationInfo:
    """Create a new Notion integration."""
    try:
        return await store.create_notion_integration(integration)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.get("/{name}", dependencies=[RequireScope("read")])
async def get_notion_integration(name: str, store: StoreD) -> NotionIntegrationInfo:
    """Get a Notion integration by name."""
    info = await store.get_notion_integration(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Notion integration '{name}' not found")
    return info


@router.put("/{name}", dependencies=[RequireScope("write")])
async def update_notion_integration(
    name: str,
    update: NotionIntegrationUpdate,
    store: StoreD,
    _role: OrgAdmin,
) -> NotionIntegrationInfo:
    """Update a Notion integration."""
    result = await store.update_notion_integration(name, update)
    if not result:
        raise HTTPException(status_code=404, detail=f"Notion integration '{name}' not found")
    return result


@router.delete("/{name}", status_code=204, dependencies=[RequireScope("write")])
async def delete_notion_integration(name: str, store: StoreD, _role: OrgAdmin) -> None:
    """Delete a Notion integration."""
    if not await store.delete_notion_integration(name):
        raise HTTPException(status_code=404, detail=f"Notion integration '{name}' not found")


@router.post("/{name}/test", dependencies=[RequireScope("read")])
async def test_notion_integration(name: str, store: StoreD) -> dict[str, str]:
    """Test a Notion integration's API key connectivity."""
    api_key = await store.get_notion_api_key(name)
    if not api_key:
        raise HTTPException(status_code=404, detail=f"Notion integration '{name}' not found")
    ok, message = await test_connection(api_key)
    if not ok:
        return {"status": "error", "message": message}
    return {"status": "ok", "message": "Connected to Notion API successfully"}


@webhook_router.post("/webhooks/events")
async def receive_notion_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> NotionWebhookResponse:
    """Public Notion webhook endpoint. Auth is Notion HMAC, not SignalPilot auth."""
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

    if verification_token := payload.get("verification_token"):
        logger.warning("NOTION WEBHOOK VERIFICATION TOKEN RECEIVED: %s", verification_token)
        return NotionWebhookResponse(status="verification_received")

    verification_token = _webhook_verification_token()
    if verification_token:
        try:
            notion_webhooks.verify_notion_signature(
                raw_body,
                request.headers.get("x-notion-signature"),
                verification_token,
            )
        except notion_webhooks.InvalidNotionSignature as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
    else:
        logger.warning("Skipping Notion webhook signature verification in local mode")

    event_id = payload.get("id")
    if not event_id:
        return NotionWebhookResponse(status="ignored")

    existing = await notion_store.get_webhook_delivery(db, str(event_id))
    if existing and existing.status in {"queued", "processing", "processed", "ignored"}:
        return NotionWebhookResponse(status="duplicate", event_id=str(event_id))

    attempt_number = payload.get("attempt_number")
    if payload.get("type") != "comment.created":
        await notion_store.record_webhook_delivery(
            db,
            str(event_id),
            status="ignored",
            attempt_number=attempt_number,
            processed=True,
        )
        return NotionWebhookResponse(status="ignored", event_id=str(event_id))

    if notion_webhooks.is_bot_authored(payload):
        await notion_store.record_webhook_delivery(
            db,
            str(event_id),
            status="ignored",
            attempt_number=attempt_number,
            processed=True,
        )
        return NotionWebhookResponse(status="ignored", event_id=str(event_id))

    try:
        routed = await notion_webhooks.route_comment_event(db, payload)
    except notion_webhooks.AmbiguousNotionInstallation as exc:
        await notion_store.record_webhook_delivery(
            db,
            str(event_id),
            status="failed",
            attempt_number=attempt_number,
            error=str(exc),
            processed=True,
        )
        return NotionWebhookResponse(status="ambiguous", event_id=str(event_id))

    if routed is None:
        await notion_store.record_webhook_delivery(
            db,
            str(event_id),
            status="ignored",
            attempt_number=attempt_number,
            processed=True,
        )
        return NotionWebhookResponse(status="ignored", event_id=str(event_id))

    await notion_store.record_webhook_delivery(
        db,
        str(event_id),
        status="queued",
        attempt_number=attempt_number,
        installation_id=routed.installation.id,
        org_id=routed.installation.org_id,
    )
    _schedule_notion_event_processing(str(event_id), routed.installation.id, payload)
    return NotionWebhookResponse(status="queued", event_id=str(event_id))
