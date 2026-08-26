"""Synthetic scratch-notebook execution adapter for standalone data chat."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.auth.notebook_jwt import mint_session_jwt
from gateway.config.k8s import get_k8s_settings
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
from gateway.standalone_chat.config import enterprise_chat_feature_flags
from gateway.standalone_chat.object_storage import chat_object_storage
from gateway.store import notebook_sessions as notebook_session_store
from gateway.store import org_secrets as org_secrets_store
from gateway.store.standalone_chat import set_execution_session


def _join_base_path(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _notebook_auth_headers() -> dict[str, str]:
    """Authenticate direct-mode notebook requests with the shared server token.

    The shared notebook container runs with --token-password-file, so every
    /api request needs the token. Kubernetes-mode pods resolve auth through
    the notebook proxy instead, and the token file is absent there.
    """
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


@dataclass(frozen=True)
class PreparedExecution:
    url: str
    headers: dict[str, str]
    payload: dict[str, Any]


async def ensure_execution_runtime(
    db: AsyncSession,
    *,
    run: GatewayChatRun,
    worker_id: str,
    branch: str,
    connection_name: str,
    commit_sha: str,
) -> NotebookRuntime:
    runtime = await ensure_standalone_chat_notebook_session(
        db,
        org_id=run.org_id,
        user_id=run.user_id,
        run_id=run.id,
        project_id=run.project_id,
        branch=branch,
        connection_name=connection_name,
        commit_sha=commit_sha,
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
) -> PreparedExecution:
    runtime = await ensure_execution_runtime(
        db,
        run=run,
        worker_id=worker_id,
        branch=branch,
        connection_name=connection_name,
        commit_sha=commit_sha,
    )
    conversation = await db.get(GatewayChatConversation, run.conversation_id)
    is_improvement_run = bool(conversation and getattr(conversation, "origin", "user") == "improvement")
    anthropic_api_key = await org_secrets_store.resolve_anthropic_key(db, run.org_id)
    runtime_auth: dict[str, str] | None = None
    if is_improvement_run and (improvement_key := os.getenv("SP_IMPROVEMENT_ANTHROPIC_KEY")):
        # Automated improvement runs bill to a dedicated Claude Code OAuth
        # token (sk-ant-oat...), never to the author's personal credential.
        # OAuth only for now — no API-key path.
        runtime_auth = {"type": "oauth", "token": improvement_key}
    elif anthropic_api_key:
        runtime_auth = {"type": "api_key", "token": anthropic_api_key}
    elif oauth_token := (os.getenv("CLAUDE_CODE_OAUTH_TOKEN") or os.getenv("OAUTH_TOKEN")):
        runtime_auth = {"type": "oauth", "token": oauth_token}
    elif server_api_key := os.getenv("ANTHROPIC_API_KEY"):
        runtime_auth = {"type": "api_key", "token": server_api_key}
    capabilities = [
        "artifact:publish",
        "dbt:read",
        "notebook:analysis",
        "query:read",
        "schema:read",
        "runtime:publish",
    ]
    if is_improvement_run:
        # Unlocks the sandbox VM MCP tools; ordinary chats never carry this.
        capabilities.append("sandbox:execute")
    payload = {
        "run_id": run.id,
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
            execution_identity=f"chat:{run.id}",
            scopes=["read", "query", "execute"],
            ttl=get_k8s_settings().sp_session_jwt_ttl_seconds,
        ),
        "prompt": prompt,
        "messages": messages,
        "warm_context": warm_context,
        "run_origin": "improvement" if is_improvement_run else "user",
        "features": {
            "size_router": enterprise_chat_feature_flags().size_router,
            "size_router_shadow": enterprise_chat_feature_flags().size_router_shadow,
            "notebook_analysis": enterprise_chat_feature_flags().notebook_analysis,
            "runtime_results": enterprise_chat_feature_flags().runtime_results,
            "runtime_artifacts": enterprise_chat_feature_flags().runtime_artifacts,
            "dataset_refs": enterprise_chat_feature_flags().dataset_refs,
        },
        # Standalone runs are reconstructed from gateway state. Never resume
        # a Claude/runtime-local session, including retries of the same run.
        "new_execution": True,
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
        **_notebook_auth_headers(),
    }
    return PreparedExecution(
        url=_join_base_path(runtime.internal_base_url, "/api/standalone-chat/execute"),
        headers=headers,
        payload=payload,
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
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.strip():
                continue
            event = json.loads(line)
            if isinstance(event, dict):
                yield event


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
                headers=_notebook_auth_headers(),
            )
        return response.is_success
    except httpx.HTTPError:
        return False


async def cleanup_finished_execution(db: AsyncSession, *, run_id: str) -> None:
    """Release a synthetic notebook only after its durable run yields the lease."""
    run = await db.get(GatewayChatRun, run_id)
    if (
        run is None
        or run.status not in {"waiting_for_user", "completed", "failed", "cancelled"}
        or not run.execution_session_id
    ):
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
