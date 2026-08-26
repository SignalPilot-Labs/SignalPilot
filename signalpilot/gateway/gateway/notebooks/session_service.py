"""Notebook session orchestration (Runtime v2).

One session per (org, user). Compute is a disposable sandbox (or the local
direct container); durable files live in the S3 workspace store; this module
owns the session state machine:

    creating ── launch ──► running ◄── resume ── snapshotted
                              │                      ▲
                              └── idle: flush is the sandbox's job (sync
                                  agent barriers), snapshot+stop is ours ┘

Every handle is persisted; a gateway restart reattaches by runtime_handle.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from gateway.auth.notebook_jwt import mint_session_jwt
from gateway.config.k8s import get_k8s_settings
from gateway.config.notebooks import get_notebook_settings
from gateway.models.notebook_sessions import NotebookSessionInfo
from gateway.notebooks.backends import (
    LaunchRequest,
    NotebookBackend,
    NotebookLaunchError,
    get_notebook_backend,
)
from gateway.store import notebook_sessions as ns
from gateway.store import org_secrets as org_secrets_store
from gateway.workspace_store import WorkspaceStore, acquire_lease, release_lease
from gateway.workspace_store.objects import workspace_object_storage
from gateway.workspace_store.store import RevisionNotFound

logger = logging.getLogger(__name__)

_AI_CREDENTIAL_ENV_NAMES = ("CLAUDE_CODE_OAUTH_TOKEN", "OAUTH_TOKEN")
_NOTEBOOK_MODEL_ENV_NAMES = ("SIGNALPILOT_ANALYSIS_AGENT_MODEL", "SIGNALPILOT_WORKER_AGENT_MODEL")
_DEFAULT_CLOUD_WEB_URL = "https://app.signalpilot.ai"


@dataclass(frozen=True)
class NotebookRuntime:
    session_id: str
    internal_base_url: str
    public_base_url: str
    # The session's runtime auth token (the notebook server's password).
    # In-gateway callers dialing internal_base_url directly must send it as
    # Authorization: Bearer, exactly like the notebook proxy does. Never
    # serialize this object into an API response.
    access_token: str | None = None


class NotebookSessionError(RuntimeError):
    """Base exception for notebook session orchestration failures."""


class NotebookQuotaExceededError(NotebookSessionError):
    """The org is at its concurrent-session budget."""


class NotebookOrgRequiredError(NotebookSessionError):
    """A caller tried to start a notebook without an org scope."""


def _session_matches(session: NotebookSessionInfo, *, project_id: str | None, branch: str) -> bool:
    return (session.project_id or None) == project_id and session.branch == branch


async def _session_predates_org_secret_update(
    session: AsyncSession,
    session_info: NotebookSessionInfo,
    *,
    org_id: str,
) -> bool:
    try:
        secret_updated_at = await org_secrets_store.get_anthropic_key_updated_at(session, org_id)
    except Exception:
        logger.warning(
            "Could not check org Anthropic key freshness for notebook session %s",
            session_info.id,
            exc_info=True,
        )
        return False
    return bool(secret_updated_at and session_info.created_at < secret_updated_at)


def _web_url() -> str | None:
    web_url = os.getenv("SP_WEB_URL") or os.getenv("SIGNALPILOT_WEB_URL")
    if web_url:
        return web_url.rstrip("/")
    if os.getenv("SP_DEPLOYMENT_MODE", "").lower() == "cloud":
        return _DEFAULT_CLOUD_WEB_URL
    return None


def _public_gateway_url() -> str:
    return get_k8s_settings().sp_public_gateway_url.rstrip("/")


async def _runtime_env(
    session: AsyncSession,
    *,
    org_id: str,
    extra_env: dict[str, str] | None,
) -> dict[str, str]:
    env: dict[str, str] = {
        name: value
        for name in (*_AI_CREDENTIAL_ENV_NAMES, *_NOTEBOOK_MODEL_ENV_NAMES)
        if (value := os.getenv(name))
    }
    env["SP_GATEWAY_URL"] = _public_gateway_url()
    env["SP_GATEWAY_PUBLIC_URL"] = _public_gateway_url()
    web_url = _web_url()
    if web_url:
        env["SP_WEB_URL"] = web_url
    anthropic_key = await org_secrets_store.resolve_anthropic_key(session, org_id)
    if anthropic_key:
        env["ANTHROPIC_API_KEY"] = anthropic_key
    if extra_env:
        env.update(extra_env)
    return env


async def _hydration_source(
    session: AsyncSession,
    *,
    org_id: str,
    project_id: str | None,
    branch: str,
    revision: int | None = None,
) -> tuple[str | None, int | None]:
    """Presigned snapshot URL + revision for boot hydration. Projects with no
    revisions (fresh, or scratch sessions) hydrate nothing."""
    if not project_id:
        return None, None
    store = WorkspaceStore(workspace_object_storage())
    if not store.storage.enabled:
        return None, None
    try:
        resolved, key = await store.build_snapshot(
            session, org_id=org_id, project_id=project_id, branch=branch, revision=revision
        )
    except RevisionNotFound:
        return None, None
    url = await store.storage.presign_get(key, expires_seconds=3600)
    return url, resolved


async def _mark_session_status_best_effort(
    session: AsyncSession,
    *,
    session_id: str,
    org_id: str,
    status: str,
) -> None:
    try:
        await ns.update_session_runtime(session, session_id=session_id, org_id=org_id, status=status)
    except Exception:
        logger.warning(
            "Could not mark notebook session %s as %s", session_id, status, exc_info=True
        )
        try:
            await session.rollback()
        except Exception:
            logger.debug("Rollback after notebook session status update failure failed", exc_info=True)


def _public_base_url(session_id: str) -> str:
    web_url = os.getenv("SP_WEB_URL") or os.getenv("SIGNALPILOT_WEB_URL") or _public_gateway_url()
    return f"{web_url.rstrip('/')}/notebook/{session_id}"


def upstream_base_for(internal: ns.NotebookSessionInternal) -> str:
    """The base URL the proxy (and in-gateway callers) dial for a session.

    Direct sessions run without --base-url, so the path is the bare container
    URL; sandbox sessions run with --base-url /notebook/{sid} behind their
    public route URL.
    """
    if not internal.upstream_url:
        raise NotebookSessionError(f"Session {internal.session_id} has no upstream URL")
    base = internal.upstream_url.rstrip("/")
    if internal.backend == "direct":
        return base
    return f"{base}/notebook/{internal.session_id}"


async def runtime_for_session(
    session: AsyncSession, session_info: NotebookSessionInfo
) -> NotebookRuntime:
    internal = await ns.get_session_internal(
        session, session_id=session_info.id, org_id=session_info.org_id
    )
    if internal is None:
        raise NotebookSessionError(f"Notebook session {session_info.id} not found")
    return NotebookRuntime(
        session_id=session_info.id,
        internal_base_url=upstream_base_for(internal),
        public_base_url=_public_base_url(session_info.id),
        access_token=internal.access_token,
    )


async def _try_resume(
    session: AsyncSession,
    backend: NotebookBackend,
    existing: NotebookSessionInfo,
    *,
    org_id: str,
) -> NotebookSessionInfo | None:
    internal = await ns.get_session_internal(session, session_id=existing.id, org_id=org_id)
    if internal is None or not internal.runtime_handle:
        return None
    try:
        upstream = await backend.resume(internal.runtime_handle)
    except Exception:
        logger.info(
            "Resume of session %s failed; falling back to a cold start", existing.id, exc_info=True
        )
        await backend.terminate(internal.runtime_handle)
        return None
    await ns.update_session_runtime(
        session, session_id=existing.id, org_id=org_id, status="running", upstream_url=upstream
    )
    refreshed = await ns.get_session_by_id(session, session_id=existing.id, org_id=org_id)
    return refreshed


async def ensure_notebook_session(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    project_id: str | None,
    branch: str,
    credential_user_id: str | None = None,
    extra_env: dict[str, str] | None = None,
    frozen_revision: int | None = None,
    read_only: bool = False,
    token_project_id: str | None = None,
    token_branch: str | None = None,
    token_connection_name: str | None = None,
    token_commit_sha: str | None = None,
    token_capabilities: list[str] | None = None,
    token_execution_identity: str | None = None,
    token_scopes: list[str] | None = None,
    backend: NotebookBackend | None = None,
) -> NotebookSessionInfo:
    """Create, reuse, or resume the notebook session for one
    (org, user, project, branch)."""
    if not org_id:
        raise NotebookOrgRequiredError("org_id required")

    user_id = user_id or "local"
    project_id = project_id or None
    settings = get_notebook_settings()
    backend = backend or get_notebook_backend(settings)

    existing = await ns.get_active_session(session, org_id=org_id, user_id=user_id)
    if existing and not _session_matches(existing, project_id=project_id, branch=branch):
        await terminate_session(session, session_info=existing, backend=backend)
        existing = None
    if existing and await _session_predates_org_secret_update(session, existing, org_id=org_id):
        logger.info(
            "Recreating notebook session %s: org Anthropic key changed after it was created",
            existing.id,
        )
        await terminate_session(session, session_info=existing, backend=backend)
        existing = None

    if existing and existing.status == "running":
        internal = await ns.get_session_internal(session, session_id=existing.id, org_id=org_id)
        if internal and internal.runtime_handle and await backend.is_alive(internal.runtime_handle):
            return existing
        await terminate_session(session, session_info=existing, backend=backend)
        existing = None
    elif existing and existing.status == "snapshotted":
        resumed = await _try_resume(session, backend, existing, org_id=org_id)
        if resumed is not None:
            return resumed
        await ns.mark_stopped(session, session_id=existing.id, org_id=org_id)
        existing = None
    elif existing:
        await terminate_session(session, session_info=existing, backend=backend)
        existing = None

    await ns.delete_stopped(session, org_id=org_id, user_id=user_id)

    if backend.name == "vercel":
        running = await ns.count_running_for_org(session, org_id=org_id)
        if running >= settings.max_running_per_org:
            raise NotebookQuotaExceededError(
                f"Org has {running} running notebook sessions (limit {settings.max_running_per_org})"
            )

    session_info = await ns.create_session(
        session,
        org_id=org_id,
        user_id=user_id,
        project_id=project_id,
        branch=branch,
        backend=backend.name,
    )
    internal = await ns.get_session_internal(session, session_id=session_info.id, org_id=org_id)
    notebook_token = internal.access_token if internal else None
    if not notebook_token:
        await _mark_session_status_best_effort(
            session, session_id=session_info.id, org_id=org_id, status="error"
        )
        raise NotebookSessionError("Refusing to start a notebook without an auth token")

    # Writer sessions take the single-writer branch lease before compute
    # exists; the in-sandbox sync agent renews it with every batch.
    if project_id and not read_only:
        await acquire_lease(
            session,
            org_id=org_id,
            project_id=project_id,
            branch=branch,
            holder=session_info.id,
            session_id=session_info.id,
        )

    snapshot_url, base_revision = await _hydration_source(
        session, org_id=org_id, project_id=project_id, branch=branch, revision=frozen_revision
    )

    session_jwt = mint_session_jwt(
        user_id=credential_user_id or user_id,
        org_id=org_id,
        session_id=session_info.id,
        project_id=token_project_id if token_project_id is not None else project_id,
        branch=token_branch or branch,
        connection_name=token_connection_name,
        commit_sha=token_commit_sha,
        capabilities=token_capabilities,
        execution_identity=token_execution_identity,
        scopes=token_scopes,
        ttl=get_k8s_settings().sp_session_jwt_ttl_seconds,
    )
    env = await _runtime_env(session, org_id=org_id, extra_env=extra_env)

    try:
        launch = await backend.launch(
            LaunchRequest(
                org_id=org_id,
                user_id=user_id,
                session_id=session_info.id,
                project_id=project_id,
                branch=branch,
                session_jwt=session_jwt,
                notebook_token=notebook_token,
                env=env,
                snapshot_url=snapshot_url,
                base_revision=base_revision,
                read_only=read_only,
            )
        )
    except Exception as exc:
        await _mark_session_status_best_effort(
            session, session_id=session_info.id, org_id=org_id, status="error"
        )
        if project_id and not read_only:
            try:
                await release_lease(
                    session, project_id=project_id, branch=branch, holder=session_info.id
                )
            except Exception:
                logger.debug("Lease release after failed launch failed", exc_info=True)
        if isinstance(exc, (NotebookLaunchError, NotebookSessionError)):
            raise NotebookSessionError(str(exc)) from exc
        logger.error("Failed to launch notebook session %s: %s", session_info.id, exc)
        raise NotebookSessionError(f"Failed to start notebook: {type(exc).__name__}") from exc

    await ns.update_session_runtime(
        session,
        session_id=session_info.id,
        org_id=org_id,
        status="running",
        runtime_handle=launch.runtime_handle,
        upstream_url=launch.upstream_url,
    )
    session_info.status = "running"
    session_info.notebook_url = f"/notebook/{session_info.id}/"
    return session_info


async def terminate_session(
    session: AsyncSession,
    *,
    session_info: NotebookSessionInfo,
    backend: NotebookBackend | None = None,
) -> None:
    """Release compute and the branch lease, then mark the row stopped."""
    backend = backend or get_notebook_backend()
    internal = await ns.get_session_internal(
        session, session_id=session_info.id, org_id=session_info.org_id
    )
    if internal and internal.runtime_handle:
        try:
            await backend.terminate(internal.runtime_handle)
        except Exception:
            logger.warning(
                "Terminate of runtime %s failed (provider limit is the backstop)",
                internal.runtime_handle,
                exc_info=True,
            )
    if session_info.project_id:
        try:
            await release_lease(
                session,
                project_id=session_info.project_id,
                branch=session_info.branch,
                holder=session_info.id,
            )
        except Exception:
            logger.debug("Lease release on terminate failed", exc_info=True)
    await ns.mark_stopped(session, session_id=session_info.id, org_id=session_info.org_id)


async def snapshot_idle_session(
    session: AsyncSession,
    *,
    internal: ns.NotebookSessionInternal,
    backend: NotebookBackend | None = None,
) -> None:
    """Idle path: snapshot, release compute, keep the row resumable."""
    backend = backend or get_notebook_backend()
    if not internal.runtime_handle:
        await ns.mark_stopped(session, session_id=internal.session_id, org_id=internal.org_id)
        return
    snapshot_id = await backend.snapshot_and_stop(internal.runtime_handle)
    if snapshot_id is None and backend.name != "direct":
        # Nothing resumable came back — treat as stopped; next request cold-
        # starts from the S3 revision, which is never worse than a fresh boot.
        await backend.terminate(internal.runtime_handle)
        await ns.mark_stopped(session, session_id=internal.session_id, org_id=internal.org_id)
        return
    if backend.name == "direct":
        return
    await ns.update_session_runtime(
        session,
        session_id=internal.session_id,
        org_id=internal.org_id,
        status="snapshotted",
        snapshot_id=snapshot_id,
        clear_upstream=True,
    )
    if internal.project_id:
        try:
            await release_lease(
                session,
                project_id=internal.project_id,
                branch=internal.branch,
                holder=internal.session_id,
            )
        except Exception:
            logger.debug("Lease release on snapshot failed", exc_info=True)


# ── Specialized session flavors ──────────────────────────────────────────────


async def ensure_notion_notebook_session(
    session: AsyncSession,
    org_id: str,
    user_id: str | None,
) -> NotebookRuntime:
    session_info = await ensure_notebook_session(
        session,
        org_id=org_id,
        user_id=user_id or "notion-webhook",
        project_id=None,
        branch="main",
    )
    return await runtime_for_session(session, session_info)


async def ensure_analysis_notebook_session(
    session: AsyncSession,
    *,
    org_id: str,
    source: str,
    request_id: str,
    project_id: str,
    branch: str,
    credential_user_id: str | None = None,
    runtime_session_id: str | None = None,
    analysis_user_id: str | None = None,
) -> NotebookRuntime:
    analysis_user_id = analysis_user_id or f"analysis:{source}:{request_id}"
    session_info = await ensure_notebook_session(
        session,
        org_id=org_id,
        user_id=analysis_user_id,
        project_id=project_id,
        branch=branch,
        credential_user_id=credential_user_id,
        extra_env={
            "SP_ANALYSIS_SOURCE": source,
            "SP_ANALYSIS_REQUEST_ID": request_id,
        },
    )
    if runtime_session_id and session_info.id != runtime_session_id:
        logger.info(
            "Replaced unavailable analysis runtime session request_id=%s previous=%s selected=%s",
            request_id,
            runtime_session_id,
            session_info.id,
        )
    return await runtime_for_session(session, session_info)


async def ensure_standalone_chat_notebook_session(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    run_id: str,
    project_id: str,
    branch: str,
    connection_name: str,
    commit_sha: str,
    frozen_revision: int | None = None,
) -> NotebookRuntime:
    """Start an isolated, frozen-workspace runtime for one durable chat run.

    The workspace is pinned to `frozen_revision` (default: the branch head at
    session start) and mounted read-only; commit_sha remains in the JWT for
    run attribution.
    """
    execution_identity = f"chat:{run_id}"
    session_info = await ensure_notebook_session(
        session,
        org_id=org_id,
        user_id=execution_identity,
        project_id=project_id,
        branch=branch,
        credential_user_id=user_id,
        frozen_revision=frozen_revision,
        read_only=True,
        extra_env={
            "SP_CHAT_RUN_ID": run_id,
            "SP_CHAT_PROJECT_ID": project_id,
            "SP_CHAT_BRANCH": branch,
            "SP_CHAT_CONNECTION_NAME": connection_name,
            "SP_CHAT_COMMIT_SHA": commit_sha,
            "SP_PROJECT_COMMIT_SHA": commit_sha,
        },
        token_project_id=project_id,
        token_branch=branch,
        token_connection_name=connection_name,
        token_commit_sha=commit_sha,
        token_capabilities=[
            "artifact:publish",
            "dbt:read",
            "notebook:analysis",
            "query:read",
            "schema:read",
            "runtime:publish",
        ],
        token_execution_identity=execution_identity,
        token_scopes=["read", "query", "execute"],
    )
    return await runtime_for_session(session, session_info)
