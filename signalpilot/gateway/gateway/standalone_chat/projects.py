"""Central standalone-chat project authorization, readiness, and starter prompts."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import (
    GatewayChatConversation,
    GatewayChatStarterCache,
    GatewayChatUserPreference,
    GatewayConnection,
    GatewayCredential,
    GatewayDbtManifest,
    GatewayWorkspaceProject,
)
from gateway.git.repos import _run_git, branch_head_sha, repo_path
from gateway.store import org_secrets as org_secrets_store
from gateway.workspace_store.dbt_detect import resolve_dbt_project_dir


@dataclass(frozen=True)
class ProjectReadiness:
    ready: bool
    code: str
    message: str
    branch: str | None
    connection_name: str | None
    metadata_checksum: str | None


async def authorize_chat_project(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    project_id: str,
) -> GatewayWorkspaceProject | None:
    """Central seam for current org-level project access.

    `user_id` is intentionally part of the contract even though the current
    project model is organization-scoped. A future membership lookup replaces
    this implementation without changing chat APIs or stored ownership.
    """
    del user_id
    result = await db.execute(
        select(GatewayWorkspaceProject).where(
            GatewayWorkspaceProject.id == project_id,
            GatewayWorkspaceProject.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


def _project_tree(project_id: str, branch: str) -> tuple[list[str], str | None]:
    try:
        path = repo_path(project_id)
        head = branch_head_sha(project_id, branch)
        if not head:
            return [], None
        rc, output, _ = _run_git(
            "ls-tree",
            "-r",
            "--name-only",
            branch,
            cwd=path,
        )
        if rc != 0:
            return [], None
        return [line.strip() for line in output.splitlines() if line.strip()], head
    except Exception:
        return [], None


def _metadata_checksum(
    project: GatewayWorkspaceProject,
    files: list[str],
    head: str | None,
    branch: str,
) -> str:
    payload = {
        "branch": branch,
        "connection": project.connection_name,
        "files": sorted(
            file
            for file in files
            if file == "dbt_project.yml"
            or file.startswith(("models/", "metrics/", "semantic_models/", "seeds/", "snapshots/"))
        ),
        "head": head,
        "settings_metadata": (project.settings or {}).get("dbt_metadata_checksum"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _has_dbt_metadata(project: GatewayWorkspaceProject, files: list[str]) -> bool:
    settings = project.settings or {}
    if settings.get("dbt_metadata_checksum") or settings.get("manifest"):
        return True
    # The dbt project rarely sits at the repo root — most real repos nest it in
    # a subfolder (e.g. `dumpsters_dbt/`). Resolve the project directory the same
    # way dbt_map/runner and the dbt executor do (explicit setting, else the
    # shallowest detected `<dir>/dbt_project.yml`) instead of assuming the root,
    # otherwise readiness reports `metadata_unavailable` for a perfectly valid
    # nested project.
    project_dir = resolve_dbt_project_dir(settings, files)
    if project_dir is None:
        return False
    prefix = f"{project_dir}/" if project_dir else ""
    has_project_file = f"{prefix}dbt_project.yml" in files
    resource_prefixes = tuple(
        f"{prefix}{sub}/" for sub in ("models", "metrics", "semantic_models", "snapshots")
    )
    has_resource = any(
        file.startswith(resource_prefixes)
        and file.endswith((".sql", ".yml", ".yaml", ".json"))
        for file in files
    )
    return has_project_file and has_resource


async def _has_successful_compile(db: AsyncSession, project_id: str, branch: str) -> bool:
    """A completed dbt-map compile is proof that dbt metadata exists — it is the
    strongest signal we have and independent of how the repo is laid out. The
    static tree check can miss projects (generated models, sparse mirrors); a
    green manifest on this branch cannot lie."""
    manifest = (
        await db.execute(
            select(GatewayDbtManifest.id).where(
                GatewayDbtManifest.project_id == project_id,
                GatewayDbtManifest.branch == branch,
                GatewayDbtManifest.status == "success",
            )
        )
    ).first()
    return manifest is not None


async def evaluate_project_readiness(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    project: GatewayWorkspaceProject,
    branch_override: str | None = None,
) -> ProjectReadiness:
    if project.status != "active":
        return ProjectReadiness(False, "project_inactive", "This project is not active.", None, None, None)

    branch = (branch_override or project.default_branch or "main").strip() or "main"
    files, head = _project_tree(project.id, branch)
    if not head:
        return ProjectReadiness(
            False,
            "branch_unavailable",
            "The production branch is not available yet.",
            None,
            project.connection_name,
            None,
        )
    if not _has_dbt_metadata(project, files) and not await _has_successful_compile(
        db, project.id, branch
    ):
        return ProjectReadiness(
            False,
            "metadata_unavailable",
            "dbt metadata is not available for this project.",
            branch,
            project.connection_name,
            None,
        )

    connection_name = (project.connection_name or "").strip()
    if not connection_name:
        return ProjectReadiness(
            False,
            "connection_missing",
            "A production data connection has not been configured.",
            branch,
            None,
            None,
        )
    connection = (
        await db.execute(
            select(GatewayConnection).where(
                GatewayConnection.org_id == org_id,
                GatewayConnection.name == connection_name,
            )
        )
    ).scalar_one_or_none()
    credential = (
        await db.execute(
            select(GatewayCredential.id).where(
                GatewayCredential.org_id == org_id,
                GatewayCredential.connection_name == connection_name,
            )
        )
    ).scalar_one_or_none()
    unusable_statuses = {"disconnected", "error", "failed", "unhealthy"}
    if (
        connection is None
        or credential is None
        or str(connection.status or "").lower() in unusable_statuses
    ):
        return ProjectReadiness(
            False,
            "connection_unusable",
            "The production data connection is not usable.",
            branch,
            connection_name,
            None,
        )

    has_runtime_credentials = bool(
        os.getenv("CLAUDE_CODE_OAUTH_TOKEN")
        or os.getenv("OAUTH_TOKEN")
        or os.getenv("ANTHROPIC_API_KEY")
        # The improvement-run billing key also satisfies the runtime
        # requirement; execution.py picks the right credential per run.
        or os.getenv("SP_IMPROVEMENT_ANTHROPIC_KEY")
        or await org_secrets_store.resolve_anthropic_key(db, org_id)
    )
    if not has_runtime_credentials:
        return ProjectReadiness(
            False,
            "ai_credentials_missing",
            "AI runtime credentials have not been configured.",
            branch,
            connection_name,
            None,
        )

    return ProjectReadiness(
        True,
        "ready",
        "Ready",
        branch,
        connection_name,
        _metadata_checksum(project, files, head, branch),
    )


def _git_show(project_id: str, branch: str, filename: str) -> str:
    try:
        path = repo_path(project_id)
        rc, output, _ = _run_git("show", f"{branch}:{filename}", cwd=path)
        return output if rc == 0 else ""
    except Exception:
        return ""


def _metadata_terms(project: GatewayWorkspaceProject, branch: str) -> tuple[list[str], list[str], list[str]]:
    files, _ = _project_tree(project.id, branch)
    model_names = [
        Path(filename).stem.replace("_", " ")
        for filename in files
        if filename.startswith("models/") and filename.endswith(".sql")
    ]
    metric_names: list[str] = []
    source_names: list[str] = []
    yaml_files = [
        filename
        for filename in files
        if filename.startswith(("models/", "metrics/", "semantic_models/"))
        and filename.endswith((".yml", ".yaml"))
    ][:40]
    for filename in yaml_files:
        raw = _git_show(project.id, branch, filename)
        if not raw:
            continue
        try:
            data = yaml.safe_load(raw) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        for metric in data.get("metrics") or []:
            if isinstance(metric, dict) and metric.get("name"):
                metric_names.append(str(metric["name"]).replace("_", " "))
        for source in data.get("sources") or []:
            if isinstance(source, dict) and source.get("name"):
                source_names.append(str(source["name"]).replace("_", " "))

    settings = project.settings or {}
    for value in settings.get("model_names") or []:
        model_names.append(str(value).replace("_", " "))
    for value in settings.get("metric_names") or []:
        metric_names.append(str(value).replace("_", " "))
    for value in settings.get("source_names") or []:
        source_names.append(str(value).replace("_", " "))

    def unique(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            cleaned = re.sub(r"\s+", " ", value).strip()
            if cleaned and cleaned.lower() not in seen:
                seen.add(cleaned.lower())
                result.append(cleaned)
        return result

    return unique(model_names), unique(metric_names), unique(source_names)


def generate_starter_questions(project: GatewayWorkspaceProject, branch: str) -> list[str]:
    models, metrics, sources = _metadata_terms(project, branch)
    project_name = project.display_name or project.name
    anchor_model = models[0] if models else "core business performance"
    second_model = models[1] if len(models) > 1 else anchor_model
    anchor_metric = metrics[0] if metrics else "the main business metrics"
    anchor_source = sources[0] if sources else "the available production data"
    return [
        f"What changed most recently in {anchor_metric}?",
        f"Summarize the key trends in {anchor_model}.",
        f"Are there any unusual patterns in {second_model} that need attention?",
        f"Give me an executive overview of {project_name} using {anchor_source}.",
    ]


def project_metadata_context(project: GatewayWorkspaceProject, branch: str) -> dict[str, object]:
    """Return bounded, non-secret dbt metadata for the standalone agent."""
    models, metrics, sources = _metadata_terms(project, branch)
    files, head = _project_tree(project.id, branch)
    dbt_files = [
        filename
        for filename in files
        if filename == "dbt_project.yml"
        or (
            filename.startswith(("models/", "metrics/", "semantic_models/", "snapshots/"))
            and filename.endswith((".sql", ".yml", ".yaml", ".json"))
        )
    ][:250]
    return {
        "checksum": _metadata_checksum(project, files, head, branch),
        "models": models[:200],
        "metrics": metrics[:100],
        "sources": sources[:100],
        "resource_files": dbt_files,
    }


async def cached_starter_questions(
    db: AsyncSession,
    *,
    org_id: str,
    project: GatewayWorkspaceProject,
    readiness: ProjectReadiness,
) -> list[str]:
    if not readiness.ready or not readiness.metadata_checksum or not readiness.branch:
        return []
    existing = (
        await db.execute(
            select(GatewayChatStarterCache).where(
                GatewayChatStarterCache.org_id == org_id,
                GatewayChatStarterCache.project_id == project.id,
                GatewayChatStarterCache.metadata_checksum == readiness.metadata_checksum,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return [str(value) for value in existing.questions_json][:4]

    questions = generate_starter_questions(project, readiness.branch)
    db.add(
        GatewayChatStarterCache(
            org_id=org_id,
            project_id=project.id,
            metadata_checksum=readiness.metadata_checksum,
            questions_json=questions,
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raced = (
            await db.execute(
                select(GatewayChatStarterCache).where(
                    GatewayChatStarterCache.org_id == org_id,
                    GatewayChatStarterCache.project_id == project.id,
                    GatewayChatStarterCache.metadata_checksum
                    == readiness.metadata_checksum,
                )
            )
        ).scalar_one()
        return [str(value) for value in raced.questions_json][:4]
    return questions


async def resolve_default_project(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    ready_project_ids: set[str],
    projects: list[GatewayWorkspaceProject],
) -> str | None:
    preference = (
        await db.execute(
            select(GatewayChatUserPreference).where(
                GatewayChatUserPreference.org_id == org_id,
                GatewayChatUserPreference.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if preference and preference.default_chat_project_id in ready_project_ids:
        return preference.default_chat_project_id

    if len(ready_project_ids) == 1:
        return next(iter(ready_project_ids))

    recent = (
        await db.execute(
            select(GatewayChatConversation.project_id)
            .where(
                GatewayChatConversation.org_id == org_id,
                GatewayChatConversation.user_id == user_id,
                GatewayChatConversation.surface == "standalone",
                GatewayChatConversation.project_id.in_(ready_project_ids),
            )
            .order_by(GatewayChatConversation.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if recent:
        return recent

    by_name = sorted(
        (project for project in projects if project.id in ready_project_ids),
        key=lambda item: (item.display_name or item.name).lower(),
    )
    return by_name[0].id if by_name else None
