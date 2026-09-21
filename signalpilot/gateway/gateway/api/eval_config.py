"""Eval configuration model and the checks that run before it is persisted.

The configuration links two repositories: the eval repository (eval.json and
its tasks) and the dbt project repository every run evaluates. Both use the
same binding shape (URL plus an optional GitHub installation and repository
id) and the same authorization path. The project repository is checked at
save time so a misconfiguration shows up in the form, not as a clone error
inside a run.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from ..config.evals import get_eval_run_settings
from ..evals.runner import GITHUB_PREFIX, PROJECT_REPO_REQUIRED, RepoRefused, assert_repo_allowed

logger = logging.getLogger(__name__)

_BRANCH_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")


class EvalConfig(BaseModel):
    repo_url: str = Field("", max_length=2048)
    repo_installation_id: str | None = Field(None, max_length=64)
    repo_id: int | None = Field(None, gt=0)
    # The dbt project a run evaluates. Empty means not configured; a run refuses to start.
    project_repo_url: str = Field("", max_length=2048)
    project_repo_installation_id: str | None = Field(None, max_length=64)
    project_repo_id: int | None = Field(None, gt=0)
    # Branch of the project repository. Empty selects the repository default branch.
    project_ref: str = Field("", max_length=200)
    model: str = Field("sonnet", max_length=64)
    max_tasks: int = Field(0, ge=0, le=200)  # 0 = all
    prompt_preamble: str = Field("", max_length=4000)
    # An eval run can use only this connection.
    # Write tasks also fork their branches from this connection.
    # A persisted configuration must specify the connection before a run starts.
    connection: str = Field("", max_length=64)
    # The default disables automatic runs because each run incurs a model cost.
    autorun_on_knowledge_add: bool = False
    # An empty list disables regression notifications.
    notify_emails: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("repo_url", "project_repo_url")
    @classmethod
    def _strip_url(cls, value: str) -> str:
        return value.strip()

    @field_validator("project_ref")
    @classmethod
    def _project_ref_is_a_branch_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        if ".." in value or value.endswith((".lock", "/", ".")) or not _BRANCH_NAME.fullmatch(value):
            raise ValueError("project_ref must be a git branch name")
        return value

    @field_validator("connection")
    @classmethod
    def _connection_name_is_safe(cls, value: str) -> str:
        value = value.strip()
        if value and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
            raise ValueError("connection must contain only letters, numbers, underscores, and hyphens")
        return value

    @field_validator("notify_emails")
    @classmethod
    def _emails_look_like_emails(cls, v: list[str]) -> list[str]:
        for e in v:
            if len(e) > 254 or "@" not in e or " " in e or e.count("@") != 1:
                raise ValueError(f"not an email address: {e!r}")
        return v

    @model_validator(mode="after")
    def _private_repo_bindings_are_complete(self):
        if (self.repo_installation_id is None) != (self.repo_id is None):
            raise ValueError("repo_installation_id and repo_id must be set together")
        if (self.project_repo_installation_id is None) != (self.project_repo_id is None):
            raise ValueError("project_repo_installation_id and project_repo_id must be set together")
        if self.project_ref and not self.project_repo_url.startswith(GITHUB_PREFIX):
            raise ValueError("project_ref requires a GitHub project repository URL")
        return self


async def verify_eval_config(store, cfg: EvalConfig) -> EvalConfig:
    """Check both repository bindings and return the config with canonical URLs."""
    repo_url = await verify_repo_binding(
        store,
        url=cfg.repo_url,
        installation_id=cfg.repo_installation_id,
        repo_id=cfg.repo_id,
        what="eval repository",
    )
    project_repo_url = cfg.project_repo_url
    if project_repo_url:
        _assert_project_repo_usable(project_repo_url)
        project_repo_url = await verify_repo_binding(
            store,
            url=project_repo_url,
            installation_id=cfg.project_repo_installation_id,
            repo_id=cfg.project_repo_id,
            what="dbt project repository",
        )
    return cfg.model_copy(update={"repo_url": repo_url, "project_repo_url": project_repo_url})


def _assert_project_repo_usable(url: str) -> None:
    """Apply the runner's repository gate at save time.

    Cloud mode permits only https://github.com/ URLs. Self-host mode also
    permits a local dbt project directory under projects_dir.
    """
    settings = get_eval_run_settings()
    try:
        assert_repo_allowed(url, settings=settings, what="dbt project repository")
    except RepoRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not url.startswith(GITHUB_PREFIX) and not Path(url).is_dir():
        raise HTTPException(
            status_code=422,
            detail=f"dbt project repository: no directory at {url[:120]!r} under {settings.projects_dir}",
        )


async def verify_repo_binding(
    store,
    *,
    url: str,
    installation_id: str | None,
    repo_id: int | None,
    what: str,
) -> str:
    """Verify that the selected installation can read the bound repository.

    Return the canonical https://github.com/<full_name>.git URL for a bound
    repository. A binding without an installation is returned unchanged.
    """
    if installation_id is None:
        return url
    if not url.startswith(GITHUB_PREFIX):
        raise HTTPException(status_code=422, detail=f"A private {what} must use a GitHub HTTPS URL")
    full_name = url.removeprefix(GITHUB_PREFIX).removesuffix(".git").strip("/")
    if full_name.count("/") != 1:
        raise HTTPException(status_code=422, detail=f"The private {what} URL is invalid")

    from ..github_client import list_installation_repos
    from ..store import github as github_store

    installation = await github_store.get_installation(
        store.session,
        org_id=store.org_id,
        installation_id=installation_id,
    )
    if installation is None or installation.status != "active":
        raise HTTPException(status_code=422, detail="The selected GitHub installation is not connected")
    try:
        token = await github_store.get_valid_token(store.session, installation)
        repos = await list_installation_repos(token)
    except Exception as exc:
        logger.warning("Could not verify %s access for org=%s: %s", what, store.org_id, type(exc).__name__)
        raise HTTPException(status_code=502, detail="GitHub repository access could not be verified") from exc

    selected = next((repo for repo in repos if int(repo.get("id", 0)) == repo_id), None)
    if selected is None or str(selected.get("full_name", "")).casefold() != full_name.casefold():
        raise HTTPException(status_code=422, detail="The selected GitHub installation cannot access this repository")
    return f"https://github.com/{selected['full_name']}.git"


async def require_pinned_connection(store, connection: str | None) -> str:
    """Require a real org-scoped connection before persisting or launching."""
    name = str(connection or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="An eval connection pin is required")
    if not await store.get_connection(name):
        raise HTTPException(
            status_code=422,
            detail="The eval connection pin does not exist in this workspace",
        )
    return name


def require_project_repo(cfg: dict) -> str:
    """Return the configured project repository URL or raise the public precondition error."""
    url = str(cfg.get("project_repo_url", "") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail=PROJECT_REPO_REQUIRED)
    return url
