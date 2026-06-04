"""Shared notebook session orchestration for API and webhook callers."""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from gateway.auth.notebook_jwt import mint_session_jwt
from gateway.config.k8s import get_k8s_settings
from gateway.models.notebook_sessions import NotebookSessionInfo
from gateway.notebook_proxy.constants import POD_PORT
from gateway.orchestrator import NotebookOrchestrator
from gateway.orchestrator.jwt_secret_lifecycle import create_jwt_secret_with_owner_ref
from gateway.store import notebook_sessions as ns
from gateway.store import user_secrets as user_secrets_store

logger = logging.getLogger(__name__)

OrchestratorFactory = Callable[[], Awaitable[NotebookOrchestrator]]
_AI_CREDENTIAL_ENV_NAMES = ("CLAUDE_CODE_OAUTH_TOKEN", "OAUTH_TOKEN", "ANTHROPIC_API_KEY")


@dataclass(frozen=True)
class NotebookRuntime:
    session_id: str
    internal_base_url: str
    public_base_url: str


class NotebookSessionError(RuntimeError):
    """Base exception for notebook session orchestration failures."""


class NotebookQuotaExceededError(NotebookSessionError):
    """Raised when Kubernetes rejects the pod because the org quota is exhausted."""


class NotebookOrgRequiredError(NotebookSessionError):
    """Raised when a caller tries to start a notebook without an org scope."""


def pod_name_for(org_id: str, user_id: str) -> str:
    h = hashlib.sha256(f"{org_id}:{user_id}".encode()).hexdigest()[:12]
    return f"nb-{h}"


async def _get_orchestrator() -> NotebookOrchestrator:
    from gateway.orchestrator.kubernetes import KubernetesOrchestrator

    return KubernetesOrchestrator()


def _is_quota_exceeded_error(exc: Exception) -> bool:
    if getattr(exc, "status", None) != 403:
        return False
    body = getattr(exc, "body", "") or ""
    return "exceeded quota" in body.lower()


def _direct_host_port(direct_url: str) -> str:
    parsed = urlparse(direct_url)
    return f"{parsed.hostname}:{parsed.port or POD_PORT}"


def _http_base_for_pod_address(address: str) -> str:
    if address.startswith(("http://", "https://")):
        return address.rstrip("/")
    if ":" in address and address.rsplit(":", 1)[-1].isdigit():
        return f"http://{address}"
    return f"http://{address}:{POD_PORT}"


def _session_matches(session: NotebookSessionInfo, *, project_id: str | None, branch: str) -> bool:
    return (session.project_id or None) == project_id and session.branch == branch


async def _pod_ai_env(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    extra_env: dict[str, str] | None,
) -> dict[str, str] | None:
    env: dict[str, str] = {
        name: value
        for name in _AI_CREDENTIAL_ENV_NAMES
        if (value := os.getenv(name))
    }

    anthropic_key = await user_secrets_store.get_user_anthropic_key(session, org_id, user_id)
    if anthropic_key:
        env["ANTHROPIC_API_KEY"] = anthropic_key

    if extra_env:
        env.update(extra_env)
    return env or None


def _public_base_url(session_id: str) -> str:
    notebook_public = os.getenv("SIGNALPILOT_NOTEBOOK_PUBLIC_URL")
    if notebook_public:
        base = notebook_public.rstrip("/")
        path = urlparse(base).path.rstrip("/")
        if base.endswith(f"/notebook/{session_id}"):
            return base
        if path.endswith("/notebook"):
            return f"{base}/{session_id}"
        if "/notebook/" in path:
            return base
        return f"{base}/notebook/{session_id}"

    web_url = (
        os.getenv("SP_WEB_URL")
        or os.getenv("SIGNALPILOT_WEB_URL")
        or get_k8s_settings().sp_public_gateway_url
    )
    return f"{web_url.rstrip('/')}/notebook/{session_id}"


async def runtime_for_session(session: AsyncSession, session_info: NotebookSessionInfo) -> NotebookRuntime:
    direct_url = os.getenv("SP_NOTEBOOK_DIRECT_URL", "").rstrip("/")
    if direct_url:
        internal_base_url = direct_url
    else:
        internal = await ns.get_session_internal(
            session,
            session_id=session_info.id,
            org_id=session_info.org_id,
        )
        if internal is None or not internal.pod_ip_internal:
            raise NotebookSessionError(
                f"Notebook session {session_info.id} is running without an internal pod IP"
            )
        internal_base_url = f"{_http_base_for_pod_address(internal.pod_ip_internal)}/notebook/{session_info.id}"

    return NotebookRuntime(
        session_id=session_info.id,
        internal_base_url=internal_base_url,
        public_base_url=_public_base_url(session_info.id),
    )


async def ensure_notebook_session(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    project_id: str | None,
    branch: str,
    extra_env: dict[str, str] | None = None,
    get_orchestrator: OrchestratorFactory | None = None,
) -> NotebookSessionInfo:
    """Create or reuse a running notebook session for one org/user/project/branch."""
    if not org_id:
        raise NotebookOrgRequiredError("org_id required")

    orchestrator_factory = get_orchestrator or _get_orchestrator
    user_id = user_id or "local"
    project_id = project_id or None
    direct_url = os.getenv("SP_NOTEBOOK_DIRECT_URL", "")

    existing = await ns.get_active_session(session, org_id=org_id, user_id=user_id)
    if existing and not _session_matches(existing, project_id=project_id, branch=branch):
        await ns.mark_stopped(session, session_id=existing.id, org_id=existing.org_id)
        existing = None

    if existing and existing.status == "running" and existing.pod_name:
        if direct_url:
            if existing.pod_ip == _direct_host_port(direct_url):
                return existing
            await ns.mark_stopped(session, session_id=existing.id, org_id=existing.org_id)
            existing = None
        else:
            internal = await ns.get_session_internal(session, session_id=existing.id, org_id=org_id)
            if internal and internal.pod_ip_internal:
                orch = await orchestrator_factory()
                if await orch.is_pod_alive(existing.pod_name, org_id=org_id):
                    return existing
            await ns.mark_stopped(session, session_id=existing.id, org_id=existing.org_id)
            existing = None
    elif existing:
        await ns.mark_stopped(session, session_id=existing.id, org_id=existing.org_id)
        existing = None

    await ns.delete_stopped(session, org_id=org_id, user_id=user_id)

    if direct_url:
        host_port = _direct_host_port(direct_url)
        session_info = await ns.create_session(
            session,
            org_id=org_id,
            user_id=user_id,
            project_id=project_id,
            branch=branch,
            pod_name="local-notebook",
        )
        await ns.update_session_status(
            session,
            session_id=session_info.id,
            org_id=org_id,
            status="running",
            pod_ip=host_port,
            pod_ip_internal=host_port,
        )
        session_info.status = "running"
        session_info.pod_ip = host_port
        session_info.notebook_url = f"/notebook/{session_info.id}/"
        return session_info

    pod = pod_name_for(org_id, user_id)
    orch = await orchestrator_factory()

    session_info = await ns.create_session(
        session,
        org_id=org_id,
        user_id=user_id,
        project_id=project_id,
        branch=branch,
        pod_name=pod,
    )

    if project_id:
        try:
            from gateway.git.sync import sync_project_with_github

            sync_result = await sync_project_with_github(project_id, org_id)
            if sync_result.get("synced"):
                logger.info("Pre-session GitHub sync for project %s: %s", project_id, sync_result)
        except Exception as exc:
            logger.warning("Pre-session GitHub sync failed (non-fatal): %s", exc)

    k8s_settings = get_k8s_settings()
    pod_extra_env = await _pod_ai_env(
        session,
        org_id=org_id,
        user_id=user_id,
        extra_env=extra_env,
    )
    session_jwt = mint_session_jwt(
        user_id=user_id,
        org_id=org_id,
        session_id=session_info.id,
        project_id=project_id,
        branch=branch,
        ttl=k8s_settings.sp_session_jwt_ttl_seconds,
    )

    try:
        await orch._ensure_client()  # type: ignore[attr-defined]
        if not orch._core_api:  # type: ignore[attr-defined]
            raise RuntimeError("K8s orchestrator not available")
        core_v1 = orch._core_api  # type: ignore[attr-defined]
        namespace = await orch.ensure_namespace(org_id)

        async def _create_pod_fn():
            return await orch.create_pod(
                pod_name=pod,
                user_id=user_id,
                org_id=org_id,
                project_id=project_id,
                branch=branch,
                image=k8s_settings.sp_notebook_image,
                gateway_url=k8s_settings.sp_public_gateway_url,
                session_jwt_secret_name=f"sp-jwt-{pod}",
                session_id=session_info.id,
                access_token=session_info.access_token,
                extra_env=pod_extra_env,
            )

        await create_jwt_secret_with_owner_ref(
            core_v1,
            namespace=namespace,
            pod_name=pod,
            session_jwt=session_jwt,
            create_pod_fn=_create_pod_fn,
        )
        logger.info("Waiting for notebook pod %s to be running...", pod)
        await orch.wait_for_running(pod, org_id=org_id, timeout=90)
        logger.info("Notebook pod %s is running; waiting for readiness probe", pod)
        pod_info = await orch.wait_for_ready(pod, org_id=org_id, timeout=90)
        logger.info("Notebook pod %s is ready: ip=%s", pod, pod_info.ip)
        await ns.update_session_status(
            session,
            session_id=session_info.id,
            org_id=org_id,
            status="running",
            pod_ip=pod_info.ip,
            pod_ip_internal=pod_info.internal_ip,
        )
        session_info.status = "running"
        session_info.pod_ip = pod_info.ip
        session_info.notebook_url = f"/notebook/{session_info.id}/"
        return session_info
    except ValueError:
        await ns.update_session_status(
            session,
            session_id=session_info.id,
            org_id=org_id,
            status="error",
        )
        raise
    except Exception as exc:
        await ns.update_session_status(
            session,
            session_id=session_info.id,
            org_id=org_id,
            status="error",
        )
        if _is_quota_exceeded_error(exc):
            logger.warning("Org quota exhausted for org %s while starting notebook pod: %s", org_id, exc)
            raise NotebookQuotaExceededError("Org quota exhausted while starting notebook pod") from exc
        logger.error("Failed to create notebook pod %s: %s: %s", pod, type(exc).__name__, exc)
        try:
            await orch.delete_pod(pod, org_id=org_id)
        except Exception:
            pass
        raise NotebookSessionError(f"Failed to start notebook pod: {type(exc).__name__}: {exc}") from exc


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
