"""Synthetic scratch-notebook execution adapter for standalone data chat."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.auth.notebook_jwt import mint_session_jwt
from gateway.config.gateway import get_gateway_settings
from gateway.config.notebooks import chat_force_oauth_token
from gateway.db.models import (
    GatewayChatConversation,
    GatewayChatObjectDeletion,
    GatewayChatRun,
    GatewayQueryProposal,
    GatewayRuntimeDataset,
)
from gateway.notebooks.session_service import (
    NotebookRuntime,
    ensure_standalone_chat_notebook_session,
    runtime_for_session,
)
from gateway.standalone_chat.agent_sessions import agent_session_transfer
from gateway.standalone_chat.config import enterprise_chat_feature_flags
from gateway.standalone_chat.object_storage import chat_object_storage
from gateway.store import notebook_sessions as notebook_session_store
from gateway.store import org_secrets as org_secrets_store
from gateway.store.standalone_chat import set_execution_session

logger = logging.getLogger(__name__)


class NotebookExecutionHTTPError(RuntimeError):
    """An HTTP failure whose message is the notebook runtime's raw body."""

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.diagnostic_context = {
            "error_type": type(self).__name__,
            "operation": "execute_notebook_analysis",
            "http_status": status_code,
        }


def _join_base_path(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _notebook_auth_headers(session_token: str | None = None) -> dict[str, str]:
    """Authenticate direct notebook requests, mirroring the notebook proxy.

    Sandbox-backed sessions (Runtime v2) carry a per-session token on the
    session row; prefer it. Local direct mode falls back to the shared
    --token-password-file the compose notebook container runs with.
    """
    if session_token:
        return {"Authorization": f"Bearer {session_token}"}
    token_file = os.getenv("SP_NOTEBOOK_TOKEN_FILE", "")
    if not token_file:
        return {}
    try:
        with open(token_file, encoding="utf-8") as handle:
            token = handle.read().strip()
    except OSError:
        return {}
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _bearer_fingerprint(headers: dict[str, str]) -> str:
    """Return a non-reversible request correlation value for auth diagnostics."""
    authorization = headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        return "missing"
    token = authorization.removeprefix("Bearer ")
    digest = hashlib.sha256(token.encode()).hexdigest()[:12]
    return f"sha256:{digest}:len{len(token)}"


@dataclass(frozen=True)
class PreparedExecution:
    url: str
    headers: dict[str, str]
    payload: dict[str, Any]
    # Gateway notebook session backing this execution. The worker forwards it
    # on notebook_started events so the browser can attach the live notebook
    # view through the notebook proxy.
    session_id: str | None = None


async def ensure_execution_runtime(
    db: AsyncSession,
    *,
    run: GatewayChatRun,
    worker_id: str,
    branch: str,
    connection_name: str,
    commit_sha: str,
    on_cold_boot: Callable[[str], Awaitable[None]] | None = None,
) -> NotebookRuntime:
    runtime = await ensure_standalone_chat_notebook_session(
        db,
        org_id=run.org_id,
        user_id=run.user_id,
        conversation_id=run.conversation_id,
        project_id=run.project_id,
        branch=branch,
        connection_name=connection_name,
        commit_sha=commit_sha,
        on_cold_boot=on_cold_boot,
    )
    if not await set_execution_session(
        db,
        run_id=run.id,
        worker_id=worker_id,
        execution_session_id=runtime.session_id,
    ):
        raise RuntimeError("Run lease was lost before notebook execution")
    return runtime


async def prepare_execution(
    db: AsyncSession,
    *,
    run: GatewayChatRun,
    worker_id: str,
    branch: str,
    connection_name: str,
    commit_sha: str,
    prompt: str,
    messages: list[dict[str, str]],
    warm_context: dict[str, Any],
    on_cold_boot: Callable[[str], Awaitable[None]] | None = None,
) -> PreparedExecution:
    conversation = await db.get(GatewayChatConversation, run.conversation_id)
    is_improvement_run = bool(conversation and getattr(conversation, "origin", "user") == "improvement")
    force_oauth = chat_force_oauth_token() and not is_improvement_run
    runtime_auth: dict[str, str] | None = None
    _local_oauth = os.getenv("CLAUDE_CODE_OAUTH_TOKEN") or os.getenv("OAUTH_TOKEN")
    if force_oauth:
        if not _local_oauth:
            raise RuntimeError("SP_CHAT_FORCE_OAUTH_TOKEN is enabled but no Claude OAuth token is configured")
        runtime_auth = {"type": "oauth", "token": _local_oauth}
    elif os.getenv("SP_RUNTIME_PREFER_OAUTH_TOKEN") and _local_oauth and not is_improvement_run:
        # Local/staging testing override: bill agent runs to the OAuth token in
        # the environment instead of the org's stored API key. Off in
        # production (the flag lives only in the local container env), so the
        # normal org-key-first resolution below is unchanged there.
        runtime_auth = {"type": "oauth", "token": _local_oauth}
    elif is_improvement_run and (improvement_key := os.getenv("SP_IMPROVEMENT_ANTHROPIC_KEY")):
        # Automated improvement runs bill to a dedicated Claude Code OAuth
        # token (sk-ant-oat...), never to the author's personal credential.
        # OAuth only for now — no API-key path.
        runtime_auth = {"type": "oauth", "token": improvement_key}
    elif anthropic_api_key := await org_secrets_store.resolve_anthropic_key(db, run.org_id):
        runtime_auth = {"type": "api_key", "token": anthropic_api_key}
    elif oauth_token := (os.getenv("CLAUDE_CODE_OAUTH_TOKEN") or os.getenv("OAUTH_TOKEN")):
        runtime_auth = {"type": "oauth", "token": oauth_token}
    elif server_api_key := os.getenv("ANTHROPIC_API_KEY"):
        runtime_auth = {"type": "api_key", "token": server_api_key}
    runtime = await ensure_execution_runtime(
        db,
        run=run,
        worker_id=worker_id,
        branch=branch,
        connection_name=connection_name,
        commit_sha=commit_sha,
        on_cold_boot=on_cold_boot,
    )
    capabilities = [
        "artifact:publish",
        "dbt:read",
        "notebook:analysis",
        "query:read",
        "schema:read",
        "runtime:publish",
    ]
    # The standalone agent runs the same SignalPilot workflow as a regular MCP
    # client. Tool implementations still enforce their own frozen-project,
    # connection, SQL-governance, and dev-database boundaries.
    capabilities.extend(["sandbox:execute", "dbt:execute"])
    payload = {
        "run_id": run.id,
        "conversation_id": run.conversation_id,
        "project_id": run.project_id,
        "branch": branch,
        "connection_name": connection_name,
        "commit_sha": commit_sha,
        "gateway_session_token": mint_session_jwt(
            user_id=run.user_id,
            org_id=run.org_id,
            session_id=runtime.session_id,
            project_id=run.project_id,
            branch=branch,
            connection_name=connection_name,
            commit_sha=commit_sha,
            capabilities=capabilities,
            # MUST stay chat:{run_id}: the notebook /execute endpoint validates
            # the JWT's execution_identity against exactly f"chat:{run_id}"
            # (it only has run_id in scope). The dbt executor keys off this too,
            # so it is per-run; the idle reaper still frees it after the warm
            # window. (The notebook SESSION warm-reuse is keyed separately by
            # conversation in session_service and is unaffected.)
            execution_identity=f"chat:{run.id}",
            scopes=["read", "query", "execute", "write", "admin"],
            ttl=get_gateway_settings().sp_session_jwt_ttl_seconds,
        ),
        "prompt": prompt,
        "messages": messages,
        "warm_context": warm_context,
        "run_origin": "improvement" if is_improvement_run else "user",
        # Optional model override. When SP_CHAT_AGENT_MODEL is set (local/staging)
        # the notebook agent uses it; unset -> the notebook keeps its own default.
        **({"model": _chat_model} if (_chat_model := os.getenv("SP_CHAT_AGENT_MODEL")) else {}),
        "features": {
            "sandbox_runtime": enterprise_chat_feature_flags().sandbox_runtime,
            "size_router": enterprise_chat_feature_flags().size_router,
            "size_router_shadow": enterprise_chat_feature_flags().size_router_shadow,
            "notebook_analysis": enterprise_chat_feature_flags().notebook_analysis,
            "runtime_results": enterprise_chat_feature_flags().runtime_results,
            "runtime_artifacts": enterprise_chat_feature_flags().runtime_artifacts,
            "dataset_refs": enterprise_chat_feature_flags().dataset_refs,
        },
        # Native Claude Agent SDK continuity. The sandbox restores this archive
        # before a cold resume and saves it after every run. Database history
        # remains the fallback when no valid SDK session exists.
        "agent_session": await agent_session_transfer(
            org_id=run.org_id,
            conversation_id=run.conversation_id,
        ),
    }
    if runtime_auth:
        # Direct-mode notebooks are shared and outlive individual requests.
        # Pass the author's credential only to this execution instead of
        # mutating the notebook process environment.
        payload["runtime_auth"] = runtime_auth
    headers = {
        "Content-Type": "application/json",
        "X-Gateway-Project-Id": run.project_id,
        "X-Gateway-Branch-Id": branch,
        "X-Gateway-Connection-Name": connection_name,
        "X-Gateway-Commit-Sha": commit_sha,
        **_notebook_auth_headers(runtime.access_token),
    }
    return PreparedExecution(
        url=_join_base_path(runtime.internal_base_url, "/api/standalone-chat/execute"),
        headers=headers,
        payload=payload,
        session_id=runtime.session_id,
    )


async def stream_execution(execution: PreparedExecution) -> AsyncGenerator[dict[str, Any], None]:
    timeout = httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0)
    async with (
        httpx.AsyncClient(timeout=timeout) as client,
        client.stream(
            "POST",
            execution.url,
            headers=execution.headers,
            json=execution.payload,
        ) as response,
    ):
        if response.is_error:
            # Error responses are small JSON/plain-text diagnostics from the
            # notebook runtime. Read them before the streaming context closes;
            # otherwise every 4xx collapses to an opaque HTTPStatusError and
            # the real authorization/workspace failure is lost.
            error_body = (await response.aread()).decode(errors="replace")
            logger.warning(
                "Notebook execute failed status=%s url=%s bearer=%s body_bytes=%s",
                response.status_code,
                execution.url,
                _bearer_fingerprint(execution.headers),
                len(error_body.encode("utf-8")),
            )
            reason = error_body if error_body else response.reason_phrase
            raise NotebookExecutionHTTPError(
                reason,
                status_code=response.status_code,
            )
        async for line in response.aiter_lines():
            if not line.strip():
                continue
            event = json.loads(line)
            if isinstance(event, dict):
                yield event


async def steer_execution(
    execution: PreparedExecution,
    *,
    run_id: str,
    steering_id: str,
    message: str,
) -> bool:
    """Offer a durable queued message to the live notebook agent."""
    url = execution.url.rsplit("/execute", 1)[0] + f"/steer/{run_id}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            url,
            headers=execution.headers,
            json={"steering_id": steering_id, "message": message},
        )
    if response.status_code == 409:
        return False
    response.raise_for_status()
    return True


async def cancel_execution_session(db: AsyncSession, run: GatewayChatRun) -> bool:
    if not run.execution_session_id:
        return False
    session_info = await notebook_session_store.get_session_by_id(
        db,
        session_id=run.execution_session_id,
        org_id=run.org_id,
    )
    if session_info is None:
        return False
    runtime = await runtime_for_session(db, session_info)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                _join_base_path(
                    runtime.internal_base_url,
                    f"/api/standalone-chat/cancel/{run.id}",
                ),
                headers=_notebook_auth_headers(runtime.access_token),
            )
        return response.is_success
    except httpx.HTTPError:
        return False


async def cleanup_finished_execution(db: AsyncSession, *, run_id: str) -> None:
    """Release the notebook session after a run finishes.

    Interactive chat sessions stay WARM: they are conversation-keyed and reused
    by the next message, and the idle lifecycle loop snapshots and reaps them.
    Only one-shot improvement runs terminate their session at run end."""
    run = await db.get(GatewayChatRun, run_id)
    if (
        run is None
        or run.status not in {"waiting_for_user", "completed", "failed", "cancelled"}
        or not run.execution_session_id
    ):
        return
    conversation = await db.get(GatewayChatConversation, run.conversation_id)
    is_improvement = bool(conversation and getattr(conversation, "origin", "user") == "improvement")
    if not is_improvement:
        # Keep the interactive chat session warm for the next message. The idle
        # lifecycle loop (main._notebook_lifecycle_loop) snapshots it after
        # SP_NOTEBOOK_IDLE_SNAPSHOT_SECONDS and reaps it later.
        return
    session_info = await notebook_session_store.get_session_by_id(
        db,
        session_id=run.execution_session_id,
        org_id=run.org_id,
    )
    if session_info is None:
        return
    try:
        from gateway.notebooks.session_service import terminate_session

        await terminate_session(db, session_info=session_info)
    except Exception:
        # The normal lifecycle reaper remains a fallback.
        await notebook_session_store.mark_stopped(
            db,
            session_id=session_info.id,
            org_id=run.org_id,
        )


async def cleanup_expired_approval_sandboxes(db: AsyncSession) -> int:
    """Destroy approval-waiting sandboxes after the configured warm window."""
    try:
        warm_seconds = max(0, int(os.getenv("SP_CHAT_APPROVAL_WARM_SECONDS", "900")))
    except ValueError:
        warm_seconds = 900
    cutoff = datetime.now(UTC) - timedelta(seconds=warm_seconds)
    run_ids = list(
        (
            await db.execute(
                select(GatewayChatRun.id)
                .join(GatewayQueryProposal, GatewayQueryProposal.run_id == GatewayChatRun.id)
                .where(
                    GatewayChatRun.status == "waiting_for_query_approval",
                    GatewayChatRun.execution_session_id.is_not(None),
                    GatewayQueryProposal.status == "waiting_for_approval",
                    GatewayQueryProposal.created_at <= cutoff,
                )
                .distinct()
            )
        ).scalars()
    )
    cleaned = 0
    for run_id in run_ids:
        run = await db.get(GatewayChatRun, run_id)
        if run is None or not run.execution_session_id:
            continue
        session_info = await notebook_session_store.get_session_by_id(
            db,
            session_id=run.execution_session_id,
            org_id=run.org_id,
        )
        if session_info is None:
            continue
        try:
            from gateway.notebooks.session_service import terminate_session

            await terminate_session(db, session_info=session_info)
        except Exception:
            continue
        run.execution_session_id = None
        await db.commit()
        cleaned += 1
    return cleaned


async def cleanup_expired_runtime_objects(db: AsyncSession) -> int:
    """Delete expired DatasetRefs and idempotent conversation object prefixes."""
    storage = chat_object_storage()
    if not storage.enabled:
        return 0
    now = datetime.now(UTC)
    cleaned = 0
    expired = list(
        (
            await db.execute(select(GatewayRuntimeDataset).where(GatewayRuntimeDataset.expires_at <= now).limit(100))
        ).scalars()
    )
    for dataset in expired:
        try:
            await storage.delete(dataset.object_key)
        except Exception:
            continue
        await db.delete(dataset)
        cleaned += 1
    pending = list(
        (
            await db.execute(
                select(GatewayChatObjectDeletion)
                .where(GatewayChatObjectDeletion.status == "pending")
                .order_by(GatewayChatObjectDeletion.created_at)
                .limit(20)
            )
        ).scalars()
    )
    for request in pending:
        request.attempt_count += 1
        try:
            await storage.delete_prefix(request.object_prefix)
        except Exception:
            continue
        request.status = "completed"
        request.completed_at = now
        cleaned += 1
    if cleaned or expired or pending:
        await db.commit()
    return cleaned
