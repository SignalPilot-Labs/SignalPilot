"""PipelineProof bot endpoints: GitHub webhook + manual PR scan trigger.

Thin routing layer — orchestration lives in gateway/github_bot/runner.py.
The webhook path is auth-exempt (PUBLIC_PATHS) and protected by HMAC
signature verification instead, so it is disabled outright when no webhook
secret is configured; scans run in the background so the webhook responds
inside GitHub's 10s budget.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..config.github_bot import get_github_bot_settings
from ..github_bot.runner import run_pr_scan, schedule_scan
from ..runtime.mode import is_cloud_mode
from ..security.scope_guard import RequireScope
from .deps import StoreD

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

_SCAN_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}


def _verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature_header[len("sha256="):], expected)


@router.post("/github/webhook")
async def github_webhook(request: Request):
    """GitHub webhook receiver — pull_request events trigger a background scan."""
    body = await request.body()
    cfg = get_github_bot_settings()
    # No secret means no way to authenticate the sender, in any deployment mode —
    # the route is closed rather than accepting unsigned deliveries.
    if not cfg.webhook_secret:
        raise HTTPException(status_code=503, detail="webhook secret not configured")
    if not _verify_signature(cfg.webhook_secret, body, request.headers.get("x-hub-signature-256")):
        raise HTTPException(status_code=401, detail="invalid webhook signature")

    event = request.headers.get("x-github-event", "")
    if event == "ping":
        return {"ok": True, "pong": True}
    if event not in ("pull_request", "push"):
        return {"ok": True, "ignored": event}

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON body")

    if event == "push":
        repo = (payload.get("repository") or {}).get("full_name", "")
        ref = payload.get("ref", "")
        if not repo or not ref:
            raise HTTPException(status_code=400, detail="missing repository/ref in payload")
        # Fan out in the background — sync + sandbox compile far exceed the
        # 10s webhook budget. Watched-branch filtering happens per project.
        import asyncio as _asyncio

        from ..dbt_map.triggers import handle_push

        _asyncio.create_task(_log_trigger_errors(handle_push(repo, ref), f"push {repo} {ref}"))
        return {"ok": True, "scheduled": {"repo": repo, "ref": ref}}

    action = payload.get("action", "")
    if action not in _SCAN_ACTIONS:
        return {"ok": True, "ignored_action": action}

    repo = (payload.get("repository") or {}).get("full_name", "")
    pr_number = (payload.get("pull_request") or {}).get("number")
    if not repo or not isinstance(pr_number, int):
        raise HTTPException(status_code=400, detail="missing repository/pull_request in payload")

    # Org from the repo link when present; local default otherwise. A lookup
    # FAILURE (DB down) must not read as "repo not linked" — 503 so GitHub
    # retries the delivery.
    try:
        from gateway.db.engine import get_session_factory
        from gateway.store import github as github_store

        factory = get_session_factory()
        async with factory() as session:
            org_id = await github_store.get_org_for_repo(session, repo_full_name=repo)
    except Exception as exc:
        logger.warning("Webhook org lookup failed for %s: %r", repo, exc)
        raise HTTPException(status_code=503, detail="temporary lookup failure, retry")
    if org_id is None:
        if is_cloud_mode():
            # Unlinked repo in cloud: nothing to verify against — ignore quietly.
            return {"ok": True, "ignored": "repo not linked to any org"}
        org_id = "local"

    schedule_scan(org_id, repo, pr_number)

    # Beside the scan: per-project PR automation (dbt map compile of the head
    # branch, agent-run dispatch hook). Background — never blocks the webhook.
    import asyncio as _asyncio

    from ..dbt_map.triggers import handle_pr_event

    head_branch = ((payload.get("pull_request") or {}).get("head") or {}).get("ref")
    _asyncio.create_task(
        _log_trigger_errors(
            handle_pr_event(repo, pr_number, head_branch), f"pr {repo}#{pr_number}"
        )
    )
    return {"ok": True, "scheduled": {"repo": repo, "pr": pr_number}}


async def _log_trigger_errors(coro, label: str) -> None:
    try:
        result = await coro
        logger.info("webhook automation %s: %s", label, result)
    except Exception:
        logger.exception("webhook automation failed: %s", label)


class ScanRequest(BaseModel):
    repo_full_name: str = Field(..., min_length=3, max_length=200, pattern=r"^[\w.-]+/[\w.-]+$")
    pr_number: int = Field(..., ge=1)
    connection_name: str | None = None


@router.post("/github/bot/scan", dependencies=[RequireScope("admin")])
async def manual_scan(payload: ScanRequest, store: StoreD):
    """Run a PR scan synchronously (admin; used for testing and re-runs)."""
    try:
        return await run_pr_scan(
            org_id=store.org_id or "local",
            repo=payload.repo_full_name,
            pr_number=payload.pr_number,
            connection_name=payload.connection_name,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        # Full detail is in gateway logs; don't echo URLs/hostnames to clients.
        raise HTTPException(status_code=502, detail="scan failed — see gateway logs")
