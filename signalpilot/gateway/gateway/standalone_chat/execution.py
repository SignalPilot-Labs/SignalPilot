"""Synthetic scratch-notebook execution adapter for standalone data chat."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncGenerator
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.auth.notebook_jwt import mint_session_jwt
from gateway.config.k8s import get_k8s_settings
from gateway.db.models import GatewayChatRun
from gateway.notebooks.session_service import (
    NotebookRuntime,
    ensure_standalone_chat_notebook_session,
    runtime_for_session,
)
from gateway.store import notebook_sessions as notebook_session_store
from gateway.store.standalone_chat import set_execution_session
from gateway.store.user_secrets import get_user_anthropic_key


def _join_base_path(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


async def ensure_execution_runtime(
    db: AsyncSession,
    *,
    run: GatewayChatRun,
    worker_id: str,
    branch: str,
    connection_name: str,
) -> NotebookRuntime:
    runtime = await ensure_standalone_chat_notebook_session(
        db,
        org_id=run.org_id,
        user_id=run.user_id,
        run_id=run.id,
        project_id=run.project_id,
        branch=branch,
        connection_name=connection_name,
    )
    if not await set_execution_session(
        db,
        run_id=run.id,
        worker_id=worker_id,
        execution_session_id=runtime.session_id,
    ):
        raise RuntimeError("Run lease was lost before notebook execution")
    return runtime


async def stream_execution(
    db: AsyncSession,
    *,
    run: GatewayChatRun,
    worker_id: str,
    branch: str,
    connection_name: str,
    prompt: str,
    messages: list[dict[str, str]],
    warm_context: dict[str, Any],
) -> AsyncGenerator[dict[str, Any], None]:
    runtime = await ensure_execution_runtime(
        db,
        run=run,
        worker_id=worker_id,
        branch=branch,
        connection_name=connection_name,
    )
    anthropic_api_key = await get_user_anthropic_key(
        db,
        run.org_id,
        run.user_id,
    )
    runtime_auth: dict[str, str] | None = None
    if anthropic_api_key:
        runtime_auth = {"type": "api_key", "token": anthropic_api_key}
    elif oauth_token := (
        os.getenv("CLAUDE_CODE_OAUTH_TOKEN") or os.getenv("OAUTH_TOKEN")
    ):
        runtime_auth = {"type": "oauth", "token": oauth_token}
    elif server_api_key := os.getenv("ANTHROPIC_API_KEY"):
        runtime_auth = {"type": "api_key", "token": server_api_key}
    payload = {
        "run_id": run.id,
        "project_id": run.project_id,
        "branch": branch,
        "connection_name": connection_name,
        "gateway_session_token": mint_session_jwt(
            user_id=run.user_id,
            org_id=run.org_id,
            session_id=runtime.session_id,
            project_id=run.project_id,
            branch=branch,
            connection_name=connection_name,
            capabilities=[
                "artifact:publish",
                "dbt:read",
                "query:read",
                "schema:read",
                "scratch:python",
            ],
            execution_identity=f"chat:{run.id}",
            scopes=["read", "query", "execute"],
            ttl=get_k8s_settings().sp_session_jwt_ttl_seconds,
        ),
        "prompt": prompt,
        "messages": messages,
        "warm_context": warm_context,
        "new_execution": run.execution_attempt == 1,
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
    }
    timeout = httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0)
    async with (
        httpx.AsyncClient(timeout=timeout) as client,
        client.stream(
            "POST",
            _join_base_path(runtime.internal_base_url, "/api/standalone-chat/execute"),
            headers=headers,
            json=payload,
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
                )
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
    if not os.getenv("SP_NOTEBOOK_DIRECT_URL") and session_info.pod_name:
        try:
            from gateway.notebooks.session_service import _get_orchestrator

            orchestrator = await _get_orchestrator()
            await orchestrator.delete_pod(session_info.pod_name, org_id=run.org_id)
        except Exception:
            # The normal stale-session reaper remains a fallback.
            pass
    await notebook_session_store.mark_stopped(
        db,
        session_id=session_info.id,
        org_id=run.org_id,
    )
