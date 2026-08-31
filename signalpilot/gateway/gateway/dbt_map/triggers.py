"""Webhook-driven automation for linked repos.

Push to a watched branch  -> pull into the bare repo -> import the tree as the
branch's next S3 revision -> recompile the dbt map (sandbox job).
Pull request events       -> optional dbt map compile of the PR head branch,
plus the (stubbed) agent-run dispatch hook.

Per-project behavior comes from the workspace project's `settings` JSON:
    watched_branches: list[str]      (default: [default_branch])
    auto_compile_on_push: bool       (default: True)
    compile_on_pr: bool              (default: False)
    pr_agent_trigger: bool           (default: False — dispatch is a stub)
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from ..db.models import GatewayWorkspaceProject
from .runner import schedule_compile

logger = logging.getLogger(__name__)


def _watched_branches(settings: dict, fallback: str) -> list[str]:
    configured = settings.get("watched_branches")
    if isinstance(configured, list) and configured:
        return [str(b) for b in configured]
    return [fallback]


async def _load_project(session, org_id: str, project_id: str) -> GatewayWorkspaceProject | None:
    return (
        await session.execute(
            select(GatewayWorkspaceProject).where(
                GatewayWorkspaceProject.org_id == org_id,
                GatewayWorkspaceProject.id == project_id,
            )
        )
    ).scalars().first()


async def _pull_and_import(session, link, branch: str) -> bool:
    """GitHub -> bare repo -> S3 revision for one branch. Returns success."""
    from ..git.sync import fetch_all, pull_branch
    from ..store import github as gh_store
    from ..workspace_store import workspace_object_storage
    from ..workspace_store.github_sync import import_repo_to_revisions

    installation = await gh_store.get_installation(
        session, org_id=link.org_id, installation_id=link.installation_id
    )
    if not installation or installation.status != "active":
        logger.warning("push trigger: no active installation for link %s", link.id)
        return False
    token = await gh_store.get_valid_token(session, installation)
    remote_url = f"https://x-access-token:{token}@github.com/{link.repo_full_name}.git"

    result = await asyncio.to_thread(fetch_all, link.project_id, remote_url)
    if result.get("error"):
        logger.warning("push trigger: fetch failed for %s: %s", link.project_id, result["error"])
        return False
    pull = await asyncio.to_thread(pull_branch, link.project_id, remote_url, branch)
    if pull.get("error"):
        logger.warning("push trigger: pull of %s failed for %s: %s", branch, link.project_id, pull["error"])
        return False

    storage = workspace_object_storage()
    if not storage.enabled:
        return False
    try:
        await import_repo_to_revisions(
            session, storage, org_id=link.org_id, project_id=link.project_id, branch=branch
        )
    except Exception:
        logger.exception("push trigger: workspace import failed for %s@%s", link.project_id, branch)
        return False
    return True


async def handle_push(repo_full_name: str, ref: str) -> dict:
    """Process a `push` webhook: sync + recompile every watching project."""
    from ..db.engine import get_session_factory
    from ..store import github as gh_store

    if not ref.startswith("refs/heads/"):
        return {"ignored": f"non-branch ref {ref}"}
    branch = ref[len("refs/heads/"):]

    factory = get_session_factory()
    triggered: list[str] = []
    async with factory() as session:
        links = await gh_store.get_active_links_for_repo(session, repo_full_name=repo_full_name)
        for link in links:
            project = await _load_project(session, link.org_id, link.project_id)
            if project is None or project.status != "active":
                continue
            settings = project.settings or {}
            fallback = project.default_branch or link.default_branch or "main"
            if branch not in _watched_branches(settings, fallback):
                continue
            if settings.get("auto_compile_on_push") is False:
                continue
            if await _pull_and_import(session, link, branch):
                schedule_compile(link.org_id, link.project_id, branch, trigger="push")
                triggered.append(link.project_id)
    return {"branch": branch, "compiles_triggered": triggered}


async def handle_pr_event(repo_full_name: str, pr_number: int, head_branch: str | None) -> dict:
    """PR-side automation beside the existing bot scan: optional dbt map
    compile of the head branch, plus the agent-run dispatch hook."""
    from ..db.engine import get_session_factory
    from ..store import github as gh_store

    factory = get_session_factory()
    compiled: list[str] = []
    agent_dispatched: list[str] = []
    async with factory() as session:
        links = await gh_store.get_active_links_for_repo(session, repo_full_name=repo_full_name)
        for link in links:
            project = await _load_project(session, link.org_id, link.project_id)
            if project is None or project.status != "active":
                continue
            settings = project.settings or {}
            if settings.get("compile_on_pr") is True and head_branch:
                if await _pull_and_import(session, link, head_branch):
                    schedule_compile(link.org_id, link.project_id, head_branch, trigger="pr")
                    compiled.append(link.project_id)
            if settings.get("pr_agent_trigger") is True:
                dispatch_agent_trigger(
                    org_id=link.org_id,
                    project_id=link.project_id,
                    repo_full_name=repo_full_name,
                    pr_number=pr_number,
                )
                agent_dispatched.append(link.project_id)
    return {"compiles_triggered": compiled, "agent_dispatched": agent_dispatched}


def dispatch_agent_trigger(
    *, org_id: str, project_id: str, repo_full_name: str, pr_number: int
) -> None:
    """Hook point for PR-triggered SignalPilot agent runs.

    Intentionally a stub: it records the intent so the wiring (webhook ->
    per-project config -> dispatch) is exercised end to end before the actual
    agent execution lands.
    """
    logger.info(
        "agent-trigger (stub): org=%s project=%s repo=%s pr=%d",
        org_id, project_id, repo_full_name, pr_number,
    )
