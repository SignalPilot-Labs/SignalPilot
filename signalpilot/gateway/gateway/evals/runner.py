"""Orchestrate production evaluation runs.

A run executes evaluation tasks concurrently against the customer's dbt project.
Read tasks use the shared build branch through the pinned MCP connection.
Each write task uses a disposable warehouse branch.
Task cleanup always removes the disposable branch.

PostgreSQL stores run state. S3 stores transcripts, setup logs, and captures.
Only temporary repository checkouts use the gateway-local disk.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import shutil
import tarfile
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config.evals import EvalRunSettings, get_eval_run_settings
from ..db.engine import get_session_factory
from ..store import Store
from ..store import evals as evals_store
from .backends import ContainerRun, get_execution_backend
from .branches import (
    BranchProvider,
    branch_name_for,
    enforce_branch_quota,
)
from .manifest import EvalSet, EvalTask, ManifestError, load_eval_set, read_claude_md
from .object_store import EvalObjectStore, get_object_store
from .provision import (
    ProvisioningError,
    create_task_connection,
    delete_task_connection,
    resolve_branch_provider,
)

logger = logging.getLogger(__name__)

_CONTAINER_HOME = "/tmp"  # nosec B108 - This path is a mounted container directory.


# Prepended to every WRITE task's prompt. The governed MCP path deliberately
# refuses DDL/DML, so an agent asked to rebuild a mart will read the model,
# try to build it, and stop at "I hit a wall" — which is what happened the
# first time this ran for real. The disposable branch is the thing that makes
# writing safe, so the agent has to be told the branch exists and how to
# reach it; otherwise "agent-writable branch" is only true on paper.
WRITE_ACCESS_NOTE = """\
[WRITE TASK — you have a private, disposable copy of the warehouse]

This task runs against your own throwaway branch. Nothing you do here can
touch the shared warehouse, and the branch is destroyed when the task ends.

The governed MCP tools stay read-only, so use them to INSPECT. To WRITE
(CREATE/DROP/INSERT), use the branch credential in the environment variable
SP_WAREHOUSE_DSN with psql, which is installed:

    psql "$SP_WAREHOUSE_DSN" -v ON_ERROR_STOP=1 -c "CREATE TABLE ... AS SELECT ..."

Verify your work the same way. If a tool tells you writes are blocked, that
is the read-only MCP path — switch to psql with $SP_WAREHOUSE_DSN rather
than concluding the task is impossible."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def new_run_id() -> str:
    return f"run-{datetime.now(UTC):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"


# DB access for the background task.
# The run executes outside any request, so every write opens its own short
# session (the schema-watch idiom). Chatty but correct across replicas.


class RunDB:
    def __init__(self, org_id: str, run_id: str) -> None:
        self.org_id = org_id
        self.run_id = run_id
        self._factory = get_session_factory()

    async def update_run(self, **fields: Any) -> None:
        async with self._factory() as session:
            await evals_store.update_run(session, org_id=self.org_id, run_id=self.run_id, **fields)

    async def update_task(self, task_id: str, **fields: Any) -> None:
        async with self._factory() as session:
            await evals_store.update_task(session, org_id=self.org_id, run_id=self.run_id, task_id=task_id, **fields)

    async def seed_tasks(self, tasks: list[dict]) -> None:
        async with self._factory() as session:
            await evals_store.seed_tasks(session, org_id=self.org_id, run_id=self.run_id, tasks=tasks)

    async def get_run(self) -> dict | None:
        async with self._factory() as session:
            return await evals_store.get_run(session, org_id=self.org_id, run_id=self.run_id)

    async def renew_lease(self, ttl_s: float) -> None:
        async with self._factory() as session:
            await evals_store.renew_lease(session, org_id=self.org_id, run_id=self.run_id, ttl_s=ttl_s)

    async def cancel_open_tasks(self, finished_at: str) -> None:
        async with self._factory() as session:
            await evals_store.cancel_open_tasks(
                session,
                org_id=self.org_id,
                run_id=self.run_id,
                finished_at=finished_at,
            )

    async def store(self):
        """A short-lived Store for org-scoped operations (connections, KB)."""
        session = self._factory()
        return session, Store(session, org_id=self.org_id, user_id="eval-runner")


# Progress (multi-task).


class ProgressBoard:
    """In-run progress fan-in: tasks report phase changes, the board writes
    one JSON blob on the run row. Serialized by a lock so concurrent tasks
    never interleave partial writes."""

    def __init__(self, db: RunDB, total: int) -> None:
        self._db = db
        self._lock = asyncio.Lock()
        self._active: dict[str, dict[str, Any]] = {}
        self._done = 0
        self._total = total
        self._started_at = _now()

    async def task_phase(self, task: EvalTask, phase: str, sandbox: dict | None = None) -> None:
        async with self._lock:
            entry = self._active.setdefault(
                task.id,
                {"task_id": task.id, "title": task.title, "started_at": _now()},
            )
            entry["phase"] = phase
            if sandbox is not None:
                entry["sandbox"] = sandbox
            await self._flush()

    async def task_done(self, task: EvalTask) -> None:
        async with self._lock:
            self._active.pop(task.id, None)
            self._done += 1
            await self._flush()

    async def finished(self) -> None:
        async with self._lock:
            self._active.clear()
            await self._flush(phase="finished")

    async def _flush(self, phase: str = "running") -> None:
        await self._db.update_run(
            progress={
                "phase": phase if not self._active else "running",
                "done": self._done,
                "total": self._total,
                "active": sorted(self._active.values(), key=lambda e: e["task_id"]),
                "started_at": self._started_at,
                "updated_at": _now(),
            }
        )


def derive_progress(run: dict) -> dict:
    """The shape the dashboard polls."""
    progress = dict(run.get("progress") or {})
    started = progress.get("started_at") or run.get("created_at")
    elapsed = None
    if started:
        try:
            elapsed = max(0, int((datetime.now(UTC) - datetime.fromisoformat(started)).total_seconds()))
        except ValueError:
            elapsed = None
    return {
        "run_id": run["id"],
        "status": run.get("status"),
        "phase": progress.get("phase") or (
            "finished"
            if run.get("status") in ("completed", "failed", "cancelled")
            else "preparing"
        ),
        "done": progress.get("done", 0),
        "total": progress.get("total", 0),
        "active": progress.get("active", []),
        "started_at": started,
        "elapsed_s": elapsed,
        "updated_at": progress.get("updated_at"),
        "error": run.get("error"),
    }


# Sandbox attribution (dashboard).


async def sandbox_index(org_id: str, limit: int = 25) -> dict[str, dict]:
    """sandbox name -> {run_id, task_id, task_title}."""
    factory = get_session_factory()
    async with factory() as session:
        return await evals_store.tasks_with_live_sandboxes(session, org_id=org_id, limit_runs=limit)


async def run_exists(org_id: str, run_id: str) -> bool:
    factory = get_session_factory()
    async with factory() as session:
        return await evals_store.run_exists(session, org_id=org_id, run_id=run_id)


# Eval repo fetch.


_GIT_GLOBAL_CONFIG: str | None = None


def _git_global_config() -> str:
    """Return a GIT_CONFIG_GLOBAL file that sets safe.directory to an asterisk.

    A local repository bind mount can have a different user identifier.
    Git accepts safe.directory only from global or system configuration.
    This file permits the local transport to read the bind mount.
    """
    global _GIT_GLOBAL_CONFIG
    if _GIT_GLOBAL_CONFIG is None:
        fd, path = tempfile.mkstemp(prefix="sp-eval-gitconfig-")
        with open(fd, "w", encoding="utf-8") as f:
            f.write("[safe]\n\tdirectory = *\n")
        _GIT_GLOBAL_CONFIG = path
    return _GIT_GLOBAL_CONFIG


async def _git(args: list[str], cwd: str | None = None, timeout: int = 120) -> tuple[int, str]:
    import os

    env = {**os.environ, "GIT_CONFIG_GLOBAL": _git_global_config()}
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        return 124, "git timed out"
    return proc.returncode or 0, out.decode(errors="replace")


class RepoRefused(RuntimeError):
    """The configured repo is not one this org may acquire. User-facing."""


_GITHUB_PREFIX = "https://github.com/"


def _assert_repo_allowed(repo_url: str, *, settings: EvalRunSettings, what: str) -> None:
    """Gate every repo the gateway will fetch on behalf of a run.

    The operator configuration and the evaluation manifest provide repository URLs.
    An unvalidated URL can read gateway files or access an unauthorized host.
    Cloud mode permits only a GitHub HTTPS URL linked to the organization installation.
    Self-hosted mode also permits local paths inside projects_dir.
    """
    from ..runtime.mode import is_cloud_mode

    url = (repo_url or "").strip()
    if not url:
        raise RepoRefused(f"{what}: no repository configured")
    if url.startswith(_GITHUB_PREFIX):
        return
    if is_cloud_mode():
        raise RepoRefused(f"{what}: only https://github.com/ repositories are allowed — refused {url[:120]!r}")
    if url.startswith(("http://", "https://", "git@", "ssh://", "git://", "file://")):
        raise RepoRefused(
            f"{what}: only https://github.com/ repositories or local paths under "
            f"{settings.projects_dir} are allowed — refused {url[:120]!r}"
        )
    root = Path(settings.projects_dir).resolve()
    try:
        resolved = Path(url).resolve()
    except OSError as exc:
        raise RepoRefused(f"{what}: unreadable path {url[:120]!r} ({exc})") from exc
    if not (resolved == root or root in resolved.parents):
        raise RepoRefused(f"{what}: local paths must live under {settings.projects_dir} — refused {url[:120]!r}")


async def _authed_clone_url(org_id: str, repo_url: str) -> str:
    """Swap in a short-lived installation token for a private GitHub repo.

    The resolver rejects a repository that belongs to another organization.
    The credentialed URL remains in the gateway. Containers receive a tarball.
    """
    if not repo_url.startswith(_GITHUB_PREFIX):
        return repo_url
    full_name = repo_url.removeprefix(_GITHUB_PREFIX).removesuffix(".git").strip("/")
    from ..store import github as gh_store

    factory = get_session_factory()
    async with factory() as session:
        token = await gh_store.get_org_token_for_repo(session, org_id=org_id, repo_full_name=full_name)
    if token:
        return f"https://x-access-token:{token}@github.com/{full_name}.git"
    # Public repositories can clone without GitHub App authorization.
    logger.info("No GitHub App authorization for repository %s. Cloning anonymously.", full_name)
    return repo_url


async def fetch_eval_repo(org_id: str, repo_url: str, dest: Path, settings: EvalRunSettings) -> str:
    """Clone (or resolve) the eval set into dest. Returns the git ref."""
    _assert_repo_allowed(repo_url, settings=settings, what="eval repo")
    if repo_url.startswith(("http://", "https://", "git@")):
        url = await _authed_clone_url(org_id, repo_url)
        code, out = await _git(["clone", "--depth", "1", url, str(dest)])
        if code != 0:
            # Do not include `url` in output because it can contain a token.
            raise RuntimeError(f"could not clone eval repo {repo_url}: {out[-400:]}")
        code, out = await _git(["rev-parse", "HEAD"], cwd=str(dest))
        return out.strip()[:40] if code == 0 else ""
    src = Path(repo_url)
    projects_root = Path(settings.projects_dir).resolve()
    resolved = src.resolve()
    if resolved != projects_root and projects_root not in resolved.parents:
        raise ValueError(f"local eval paths must live under {settings.projects_dir}")
    if not src.is_dir():
        raise FileNotFoundError(f"eval repo not found: {repo_url}")
    shutil.copytree(src, dest, dirs_exist_ok=True)
    digest = hashlib.sha256()
    for p in sorted(src.rglob("*")):
        if p.is_file():
            digest.update(p.relative_to(src).as_posix().encode())
            digest.update(p.read_bytes())
    return f"local-{digest.hexdigest()[:16]}"


# Refresh the GET /api/evals/tasks repository cache at most every five minutes.
_REPO_CACHE_SECONDS = 300


async def get_eval_set(org_id: str, cfg: dict, settings: EvalRunSettings) -> EvalSet:
    repo_url = str(cfg.get("repo_url", "") or "")
    if not repo_url:
        raise FileNotFoundError("no eval repo configured")
    cache_root = Path(tempfile.gettempdir()) / "sp-eval-cache"
    slug = hashlib.sha256(f"{org_id}\x00{repo_url}".encode()).hexdigest()[:16]
    dest = cache_root / slug
    meta = dest / ".sp-cache-meta"
    fresh = False
    ref = ""
    is_git = repo_url.startswith(("http://", "https://", "git@"))
    if not is_git:
        # Local paths can change without a new reference. Do not cache their manifests.
        meta.unlink(missing_ok=True)
    if meta.is_file():
        try:
            cached = json.loads(meta.read_text())
            fresh = cached.get("url") == repo_url and time.time() - cached.get("at", 0) < _REPO_CACHE_SECONDS
            ref = str(cached.get("ref", ""))
        except ValueError:
            fresh = False
    if not fresh:
        shutil.rmtree(dest, ignore_errors=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        ref = await fetch_eval_repo(org_id, repo_url, dest, settings)
        meta.write_text(json.dumps({"url": repo_url, "at": time.time(), "ref": ref}))
    eval_set = load_eval_set(dest)
    eval_set.ref = ref
    return eval_set


# Build fingerprint.


async def compute_build_fingerprint(dsn: str) -> str:
    """Return a SHA-256 digest of the build schema and row counts.

    Row counts do not detect column type changes, renames, or table replacements.
    The digest includes each column name, type, nullability, ordinal, and exact row count.
    A declared manifest fingerprint must match this digest.
    """
    import asyncpg

    conn = await asyncpg.connect(dsn=dsn, timeout=30)
    try:
        tables = await conn.fetch(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_type = 'BASE TABLE' AND table_schema NOT IN "
            "('pg_catalog', 'information_schema') ORDER BY 1, 2"
        )
        digest = hashlib.sha256()
        digest.update(b"sp-eval-fingerprint-v2\n")
        for t in tables:
            schema, name = t["table_schema"], t["table_name"]
            cols = await conn.fetch(
                "SELECT column_name, data_type, is_nullable, ordinal_position "
                "FROM information_schema.columns WHERE table_schema = $1 AND table_name = $2 "
                "ORDER BY ordinal_position",
                schema,
                name,
            )
            count = await conn.fetchval(f'SELECT count(*) FROM "{schema}"."{name}"')
            digest.update(f"{schema}.{name}:{count}\n".encode())
            for c in cols:
                digest.update(
                    f"  {c['ordinal_position']}:{c['column_name']}:{c['data_type']}:{c['is_nullable']}\n".encode()
                )
        return f"fp-{digest.hexdigest()[:32]}"
    finally:
        await conn.close()


# Containers.

# The container writes the base64-encoded MCP configuration from the environment.
# It approves project MCP servers before it runs one Claude command.
# A presigned URL sends the dbt project tarball through the secret channel.
# The pod does not receive a Git credential.
_RUNNER_SCRIPT = (
    '{ [ -n "$SP_PROJECT_TARBALL_URL" ] && curl -fsSL "$SP_PROJECT_TARBALL_URL" '
    "| tar xz -C /work; true; } && "
    "mkdir -p /work/.claude && cd /work && "
    'echo "$SP_MCP_JSON_B64" | base64 -d > /work/.mcp.json && '
    "printf '{\"enableAllProjectMcpServers\": true}' > /work/.claude/settings.local.json && "
    # Project context, when the eval set ships a CLAUDE.md. Written after the
    # tarball unpack so the eval set's instructions win over the project's.
    '{ [ -n "$SP_CLAUDE_MD_B64" ] && echo "$SP_CLAUDE_MD_B64" | base64 -d > /work/CLAUDE.md; true; } && '
    'claude -p "$SP_PROMPT" --mcp-config /work/.mcp.json --strict-mcp-config '
    '--output-format stream-json --verbose --model "$SP_MODEL" --dangerously-skip-permissions'
)


def _task_spec(
    settings: EvalRunSettings,
    *,
    prompt: str,
    model: str,
    mcp_json: str,
    labels: dict[str, str],
    claude_md: str = "",
    project_tarball_url: str = "",
    warehouse_dsn: str = "",
) -> ContainerRun:
    """One agent container for one task."""
    # Add operator variables before gateway-controlled variables.
    # SP_MCP_JSON_B64 contains the run key and connection pin.
    # An operator variable must not override this value.
    secret_env = dict(settings.project_env)
    secret_env["SP_MCP_JSON_B64"] = base64.b64encode(mcp_json.encode()).decode()
    if settings.claude_token:
        secret_env["CLAUDE_CODE_OAUTH_TOKEN"] = settings.claude_token
    if settings.anthropic_key:
        secret_env["ANTHROPIC_API_KEY"] = settings.anthropic_key
    if project_tarball_url:
        secret_env["SP_PROJECT_TARBALL_URL"] = project_tarball_url
    if warehouse_dsn:
        # A write task receives the DSN for its disposable branch.
        # A read task accesses the warehouse only through MCP.
        secret_env["SP_WAREHOUSE_DSN"] = warehouse_dsn

    env = {"SP_PROMPT": prompt, "SP_MODEL": model}
    if claude_md.strip():
        env["SP_CLAUDE_MD_B64"] = base64.b64encode(claude_md.encode()).decode()

    return ContainerRun(
        image=settings.runner_image,
        command=["sh", "-lc", _RUNNER_SCRIPT],
        env=env,
        secret_env=secret_env,
        labels=labels,
        memory_bytes=2 * 1024 * 1024 * 1024,
        nano_cpus=2_000_000_000,
        timeout_seconds=settings.timeout_seconds,
    )


def _script_spec(
    settings: EvalRunSettings,
    *,
    eval_set: EvalSet,
    repo_dir: Path,
    repo_url: str,
    script_rel: str,
    task: EvalTask,
    phase: str,
    run_id: str,
    warehouse_dsn: str,
) -> ContainerRun:
    """One setup/teardown script container, run against the task's branch."""
    image = settings.setup_image or settings.runner_image
    runner_cmd = f'sh "/repo/{script_rel}" "{task.id}"'
    if script_rel.endswith(".py"):
        runner_cmd = f'python3 "/repo/{script_rel}" "{task.id}"'

    binds: list[str] = []
    if repo_url.startswith(("http://", "https://", "git@")):
        cmd = f'git clone --depth 1 "$SP_EVAL_REPO_URL" /repo && cd /repo && {runner_cmd}'
    else:
        if not settings.projects_host_dir:
            raise RuntimeError("SP_EVAL_PROJECTS_HOST_DIR is not set — required to mount local eval repos")
        rel = str(Path(repo_url).resolve()).replace(str(Path(settings.projects_dir).resolve()), "", 1).lstrip("/\\")
        host_repo = f"{settings.projects_host_dir.rstrip('/')}/{rel}".replace("\\", "/")
        binds.append(f"{host_repo}:/repo:ro")
        cmd = f"cd /repo && {runner_cmd}"

    secret_env: dict[str, str] = {}
    env_file = str(eval_set.setup.get("env_file", "") or "")
    if env_file:
        # The manifest controls env_file and the setup code that receives its values.
        # Use the confined reader to prevent access to files outside the repository.
        try:
            from .manifest import read_confined

            for line in read_confined(repo_dir, env_file).splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    secret_env[k] = v
        except (ManifestError, OSError) as exc:
            raise RuntimeError(f"setup.env_file {env_file!r} is not readable: {exc}") from exc
    secret_env["SP_WAREHOUSE_DSN"] = warehouse_dsn

    return ContainerRun(
        image=image,
        command=["sh", "-lc", cmd],
        env={"SP_EVAL_TASK": task.id, "SP_EVAL_PHASE": phase, "SP_EVAL_REPO_URL": repo_url, "HOME": _CONTAINER_HOME},
        secret_env=secret_env,
        labels={"run": run_id, "task": task.id, "phase": phase},
        memory_bytes=4 * 1024 * 1024 * 1024,
        nano_cpus=4_000_000_000,
        timeout_seconds=int(eval_set.setup.get("timeout_seconds", settings.setup_timeout_seconds)),
        binds=binds,
    )


def _extract_result_text(logs: str) -> str:
    """Pull the final `result` from a claude stream-json transcript."""
    for line in reversed(logs.strip().splitlines()):
        line = line.strip().rstrip("\r")
        if line.startswith("{") and '"result"' in line:
            try:
                obj = json.loads(line)
                if obj.get("type") == "result" and isinstance(obj.get("result"), str):
                    return obj["result"]
            except ValueError:
                continue
    return logs[-3000:]


# Project tarball (spec §3.2).


async def _ship_project_tarball(
    org_id: str,
    run_id: str,
    project_repo: str,
    obj: EvalObjectStore,
) -> tuple[str, str, list[dict]]:
    """Clone the dbt project gateway-side, strip .git, upload as tgz, presign.

    Return the presigned URL, project reference, and model list.
    The pod receives the time-limited presigned URL instead of a Git credential.
    Enumerate models before the function deletes the checkout.
    """
    from .coverage import enumerate_models

    # Apply the repository access check to the project repository from the manifest.
    _assert_repo_allowed(project_repo, settings=get_eval_run_settings(), what="dbt project repo")

    with tempfile.TemporaryDirectory(prefix="sp-eval-proj-") as tmp:
        dest = Path(tmp) / "proj"
        url = await _authed_clone_url(org_id, project_repo)
        code, out = await _git(["clone", "--depth", "1", url, str(dest)], timeout=300)
        if code != 0:
            raise RuntimeError(f"could not clone dbt project {project_repo}: {out[-400:]}")
        code, ref_out = await _git(["rev-parse", "HEAD"], cwd=str(dest))
        project_ref = ref_out.strip()[:40] if code == 0 else ""
        models = enumerate_models(dest)
        # Remove Git history because the agent requires only the project files.
        shutil.rmtree(dest / ".git", ignore_errors=True)
        tar_path = Path(tmp) / "project.tgz"
        with tarfile.open(tar_path, "w:gz") as tar:
            for p in sorted(dest.rglob("*")):
                tar.add(p, arcname=str(p.relative_to(dest)))
        key = obj.project_tarball_key(org_id, run_id)
        await obj.upload_file(key, str(tar_path), "application/gzip")
    # Short-lived: long enough for every task to start, not for the URL to be
    # a durable handle on the customer's source.
    url = await obj.presign_get(key, expires_s=3600)
    return url, project_ref, models


async def _drop_project_tarball(org_id: str, run_id: str, obj: EvalObjectStore) -> None:
    """Delete the transport tarball once every task has fetched it.

    The tarball contains the customer's complete dbt project.
    Delete it before retention and export can include the source files.
    """
    try:
        await obj.delete_prefix(obj.project_tarball_key(org_id, run_id))
    except Exception:
        logger.exception("could not delete project tarball for run %s", run_id)


# Run lifecycle.


# A run refreshes its lease during this interval.
# Recovery and the reaper classify an expired lease as an inactive run.
LEASE_TTL_S = 180.0
_LEASE_REFRESH_S = 45.0
# Per-task credentials outlive the task only by the slack a slow container
# needs to finish its last MCP call.
TASK_KEY_TTL_S = 3 * 3600


async def execute_run(
    org_id: str,
    run_id: str,
    api_key: str | None = None,
    api_key_id: str | None = None,
) -> None:
    """Background task: fetch, fan out tasks, grade, finalize.

    api_key/api_key_id are the run-level credential minted by the caller; each
    task additionally gets its own bound, expiring key (see _task_credential).
    """
    db = RunDB(org_id, run_id)
    stop_lease = asyncio.Event()

    async def lease_loop() -> None:
        while not stop_lease.is_set():
            try:
                await db.renew_lease(LEASE_TTL_S)
            except Exception:
                logger.warning("could not renew lease for run %s", run_id)
            try:
                await asyncio.wait_for(stop_lease.wait(), timeout=_LEASE_REFRESH_S)
            except TimeoutError:
                continue

    await db.renew_lease(LEASE_TTL_S)
    lease_task = asyncio.create_task(lease_loop())
    try:
        await _execute_run_inner(org_id, run_id, api_key)
    except asyncio.CancelledError:
        logger.info("eval run %s was cancelled", run_id)
        try:
            await mark_run_cancelled(org_id, run_id)
        except Exception:
            logger.exception("could not mark run %s cancelled", run_id)
    except Exception as exc:  # last-resort: the run row must never stay "running"
        logger.exception("eval run %s crashed", run_id)
        try:
            await db.update_run(status="failed", error=str(exc)[:500], finished_at=_now())
        except Exception:
            logger.exception("could not mark run %s failed", run_id)
    finally:
        stop_lease.set()
        lease_task.cancel()
        try:
            await lease_task
        except (asyncio.CancelledError, Exception):
            pass
        await revoke_run_keys(org_id, run_id, api_key_id)
        try:
            await db.update_run(lease_expires_at=None)
        except Exception:
            logger.warning("could not clear lease for run %s", run_id)


async def mark_run_cancelled(org_id: str, run_id: str) -> None:
    """Finish the persisted state for a run that no longer executes."""
    db = RunDB(org_id, run_id)
    finished_at = _now()
    await db.cancel_open_tasks(finished_at)
    run = await db.get_run()
    tasks = list((run or {}).get("tasks") or [])
    summary = {
        "total": len(tasks),
        "correct": sum(1 for task in tasks if task.get("verdict") == "CORRECT"),
        "partial": sum(1 for task in tasks if task.get("verdict") == "PARTIAL"),
        "off": sum(1 for task in tasks if task.get("verdict") == "OFF"),
        "unknown": sum(1 for task in tasks if task.get("verdict") == "UNKNOWN"),
        "ungraded": sum(1 for task in tasks if task.get("verdict") == "UNGRADED"),
        "error": sum(1 for task in tasks if task.get("verdict") == "ERROR"),
        "setup_failed": sum(1 for task in tasks if task.get("verdict") == "SETUP_FAILED"),
        "cancelled": sum(1 for task in tasks if task.get("verdict") == "CANCELLED"),
    }
    progress = dict((run or {}).get("progress") or {})
    progress.update(
        {
            "phase": "cancelled",
            "done": len(tasks),
            "total": len(tasks),
            "active": [],
            "updated_at": finished_at,
        }
    )
    await db.update_run(
        status="cancelled",
        summary=summary,
        progress=progress,
        error=None,
        finished_at=finished_at,
        lease_expires_at=None,
    )


async def revoke_run_keys(org_id: str, run_id: str, api_key_id: str | None = None) -> None:
    """Delete the run key and each task key.

    Run cleanup and recovery both call this function.
    """
    from sqlalchemy import delete as sa_delete

    from ..db.models import GatewayApiKey

    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                sa_delete(GatewayApiKey).where(GatewayApiKey.org_id == org_id, GatewayApiKey.eval_run_id == run_id)
            )
            if api_key_id:
                await session.execute(
                    sa_delete(GatewayApiKey).where(GatewayApiKey.org_id == org_id, GatewayApiKey.id == api_key_id)
                )
            await session.commit()
    except Exception:
        logger.exception("Failed to revoke eval keys for run %s", run_id)


async def _task_credential(ctx: TaskContext, task: EvalTask, connection: str) -> tuple[str, str]:
    """Create the key for a task container.

    The server binds the key to the run, task, connection, and document overlay.
    The key expires and grants access only to the assigned task resources.
    """
    from datetime import timedelta

    factory = get_session_factory()
    async with factory() as session:
        # The run executes without a human request principal.
        # Attribute the key to the evaluation harness.
        store = Store(session, org_id=ctx.org_id, user_id="eval-runner")
        record, raw = await store.create_api_key(
            f"eval-{ctx.run_id}-{task.id}"[:100],
            ["read", "query"],
            expires_at=(datetime.now(UTC) + timedelta(seconds=TASK_KEY_TTL_S)).isoformat(),
            eval_binding={
                "run_id": ctx.run_id,
                "task_id": task.id,
                "connection": connection,
                "doc_ids": list(ctx.doc_ids or []),
            },
        )
        await session.commit()
    return record.id, raw


async def _revoke_key(org_id: str, key_id: str) -> None:
    try:
        factory = get_session_factory()
        async with factory() as session:
            store = Store(session, org_id=org_id)
            await store.delete_api_key(key_id)
            await session.commit()
    except Exception:
        logger.exception("Failed to revoke eval task key %s", key_id)


async def _execute_run_inner(org_id: str, run_id: str, api_key: str | None) -> None:
    settings = get_eval_run_settings()
    db = RunDB(org_id, run_id)
    run = await db.get_run()
    if not run:
        return None

    async def fail(msg: str) -> None:
        await db.update_run(status="failed", error=msg, finished_at=_now())

    session, store = await db.store()
    try:
        cfg = await store.get_eval_config()
        kb_docs = await store.list_knowledge_docs(status="active", limit=500)
        kb_doc_ids = [d.id for d in kb_docs]
    finally:
        await session.close()

    if not settings.s3_bucket:
        return await fail("SP_EVAL_S3_BUCKET is not set — the harness has nowhere durable for evidence")
    obj = get_object_store()

    # 1. Eval set
    repo_dir = Path(tempfile.mkdtemp(prefix=f"sp-eval-{run_id}-"))
    try:
        try:
            shutil.rmtree(repo_dir, ignore_errors=True)
            eval_ref = await fetch_eval_repo(org_id, run["repo_url"], repo_dir, settings)
            eval_set = load_eval_set(repo_dir)
            eval_set.ref = eval_ref
        except (ManifestError, RuntimeError, ValueError, FileNotFoundError) as exc:
            return await fail(str(exc)[:500])

        tasks = eval_set.tasks
        task_filter = run.get("task_filter")
        if task_filter:
            wanted = set(task_filter)
            tasks = [t for t in tasks if t.id in wanted]
        max_tasks = int(cfg.get("max_tasks", 0) or 0)
        if max_tasks > 0:
            tasks = tasks[:max_tasks]
        if not tasks:
            return await fail("no tasks selected — check the manifest and the task filter")

        needs_branches = any(t.task_class == "write" for t in tasks)

        # 2. Branch provider + build fingerprint
        provider: BranchProvider | None = None
        parent_dsn = ""
        parent_size: int | None = None
        session, store = await db.store()
        try:
            try:
                provider = await resolve_branch_provider(store, cfg, settings)
            except ProvisioningError as exc:
                if needs_branches:
                    return await fail(str(exc))
                provider = None
        finally:
            await session.close()

        fingerprint = ""
        if provider is not None:
            try:
                parent_dsn = await provider.parent_dsn()
                fingerprint = await compute_build_fingerprint(parent_dsn)
                parent_size = await provider.database_size_bytes(parent_dsn.rsplit("/", 1)[-1].split("?")[0])
            except Exception as exc:
                if needs_branches:
                    return await fail(f"could not reach the build branch: {str(exc)[:300]}")

        if eval_set.build_fingerprint and fingerprint and eval_set.build_fingerprint != fingerprint:
            return await fail(
                f"warehouse does not match the eval set's build fingerprint "
                f"(expected {eval_set.build_fingerprint}, found {fingerprint}) — "
                "rebuild the warehouse or update the eval set. Running anyway would "
                "grade against golds computed for a different build."
            )

        # 3. dbt project tarball
        project_tarball_url = ""
        project_ref = ""
        project_models: list[dict] = []
        if eval_set.project_repo:
            try:
                project_tarball_url, project_ref, project_models = await _ship_project_tarball(
                    org_id, run_id, eval_set.project_repo, obj
                )
            except RuntimeError as exc:
                return await fail(str(exc)[:500])

        # 4. Persist run coordinates + seed task rows
        await db.update_run(
            status="running",
            eval_set_name=eval_set.name,
            eval_set_ref=eval_set.ref,
            project_repo=eval_set.project_repo,
            project_ref=project_ref,
            build_fingerprint=fingerprint,
            kb_doc_ids=kb_doc_ids,
        )
        await db.seed_tasks(
            [
                {
                    "task_id": t.id,
                    "title": t.title,
                    "kind": t.kind,
                    "task_class": t.task_class,
                    "gt": t.gt,
                    "checks": t.checks,
                    "grade": t.grade,
                    "covers": t.covers,
                    "builds": t.builds,
                    "capture_spec": t.capture,
                }
                for t in tasks
            ]
        )

        claude_md = read_claude_md(repo_dir)
        preamble = str(cfg.get("prompt_preamble", "") or "")
        board = ProgressBoard(db, total=len(tasks))
        backend = get_execution_backend(settings, org_id=org_id)
        artifact_budget = ArtifactBudget(settings.artifact_bytes_per_run)

        ctx = TaskContext(
            org_id=org_id,
            run_id=run_id,
            settings=settings,
            cfg=cfg,
            db=db,
            obj=obj,
            board=board,
            backend=backend,
            eval_set=eval_set,
            repo_dir=repo_dir,
            claude_md=claude_md,
            preamble=preamble,
            api_key=api_key,
            doc_ids=list(run.get("doc_ids") or []),
            provider=provider,
            parent_size=parent_size,
            project_tarball_url=project_tarball_url,
            project_models=project_models,
            artifact_budget=artifact_budget,
            fork_lock=asyncio.Lock(),
        )

        # Run tasks concurrently. This limit controls capacity and model cost.
        semaphore = asyncio.Semaphore(max(1, settings.max_parallel_tasks))

        async def bounded(task: EvalTask) -> None:
            async with semaphore:
                await _run_task(ctx, task)

        try:
            await asyncio.gather(*(bounded(t) for t in tasks))
        finally:
            await backend.aclose()
            if provider is not None:
                await provider.aclose()
            # The tarball contains the customer's complete dbt project.
            # Delete it after pod delivery so retention and export cannot include it.
            if project_tarball_url:
                await _drop_project_tarball(org_id, run_id, obj)

        # 6. Finalize
        ctx.executed_task_ids = {t.id for t in tasks}
        await board.finished()
        await _finalize_run(ctx)
    finally:
        shutil.rmtree(repo_dir, ignore_errors=True)


class ArtifactBudget:
    """Per-run artifact byte budget (spec §3.4c), shared across tasks."""

    def __init__(self, total: int) -> None:
        self._remaining = total
        self._lock = asyncio.Lock()
        self.spent = 0

    async def take(self, n: int) -> bool:
        async with self._lock:
            if n > self._remaining:
                return False
            self._remaining -= n
            self.spent += n
            return True

    @property
    def remaining(self) -> int:
        return self._remaining


class TaskContext:
    """Everything a task needs, bundled so _run_task stays readable."""

    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


def _mcp_json(ctx: TaskContext, task: EvalTask, task_key: str) -> str:
    """MCP config for one task.

    Send only the key to the task.
    The server stores the pin, document overlay, run attribution, and task attribution.
    Request headers cannot define these boundaries because the agent controls them.
    """
    headers = {}
    if task_key:
        headers["X-API-Key"] = task_key
    return json.dumps(
        {
            "mcpServers": {
                "signalpilot": {
                    "type": "http",
                    "url": ctx.settings.mcp_url,
                    "headers": headers,
                }
            }
        }
    )


async def _pg_query(dsn: str):
    """A QueryFn over asyncpg for model_rebuilt grading."""
    import asyncpg

    conn = await asyncpg.connect(dsn=dsn, timeout=30)

    async def query(sql: str) -> list[tuple]:
        rows = await conn.fetch(sql)
        return [tuple(r) for r in rows]

    return conn, query


async def _run_agent(ctx: TaskContext, task: EvalTask, connection: str, warehouse_dsn: str) -> tuple[int, str, str]:
    """Launch the agent container; returns (exit_code, transcript, answer).

    Create a bound credential that expires for this task.
    Revoke the credential when the container exits.
    """
    key_id, raw_key = await _task_credential(ctx, task, connection)
    try:
        prompt = f"{ctx.preamble}\n\n{task.prompt}" if ctx.preamble else task.prompt
        if warehouse_dsn:
            prompt = f"{WRITE_ACCESS_NOTE}\n\n{prompt}"
        spec = _task_spec(
            ctx.settings,
            prompt=prompt,
            model=ctx.cfg.get("model", "sonnet"),
            mcp_json=_mcp_json(ctx, task, raw_key),
            labels={"run": ctx.run_id, "task": task.id, "phase": "agent"},
            claude_md=ctx.claude_md,
            project_tarball_url=ctx.project_tarball_url,
            warehouse_dsn=warehouse_dsn,
        )

        async def on_start(info: dict) -> None:
            await ctx.db.update_task(task.id, sandbox=info)
            await ctx.board.task_phase(task, "agent", sandbox=info)

        spec.on_start = lambda info: asyncio.ensure_future(on_start(info))
        from .sandboxes import redact

        exit_code, raw_logs = await ctx.backend.run(spec)
        secrets = tuple(spec.secret_env.values())
        answer = redact(_extract_result_text(raw_logs), extra_secrets=secrets)
        return exit_code, redact(raw_logs, extra_secrets=secrets), answer
    finally:
        await _revoke_key(ctx.org_id, key_id)


async def _run_script(
    ctx: TaskContext, task: EvalTask, script_rel: str, phase: str, warehouse_dsn: str
) -> tuple[bool, str]:
    spec = _script_spec(
        ctx.settings,
        eval_set=ctx.eval_set,
        repo_dir=ctx.repo_dir,
        repo_url=ctx.cfg.get("repo_url", ""),
        script_rel=script_rel,
        task=task,
        phase=phase,
        run_id=ctx.run_id,
        warehouse_dsn=warehouse_dsn,
    )
    from .sandboxes import redact

    exit_code, raw_logs = await ctx.backend.run(spec)
    logs = redact(raw_logs, extra_secrets=tuple(spec.secret_env.values()))
    key = ctx.obj.setup_log_key(ctx.org_id, ctx.run_id, task.id, phase)
    await ctx.obj.put_text(key, logs)
    return exit_code == 0, logs


async def _run_task(ctx: TaskContext, task: EvalTask) -> None:
    db: RunDB = ctx.db
    started = time.monotonic()
    await db.update_task(task.id, status="running", started_at=_now())
    await ctx.board.task_phase(task, "provisioning" if task.task_class == "write" else "agent")

    transcript = ""
    verdict, check_results, answer, error = "ERROR", [], "", None

    cancelled = False
    try:
        if task.task_class == "write":
            verdict, check_results, answer, transcript, error = await _run_write_task(ctx, task)
        else:
            connection = str(ctx.cfg.get("connection", "") or "")
            exit_code, transcript, answer = await _run_agent(ctx, task, connection, "")
            if exit_code != 0 and not answer.strip():
                verdict, check_results = "ERROR", []
                error = f"agent container exited {exit_code}"
            else:
                verdict, check_results = _grade_answer(task, answer)
    except asyncio.CancelledError:
        cancelled = True
        verdict = "CANCELLED"
        answer = "Run cancelled by user."
        raise
    except Exception as exc:
        logger.exception("task %s failed", task.id)
        from .sandboxes import redact

        error = redact(str(exc))[:500]
        answer = answer or error
    finally:
        if transcript:
            try:
                await ctx.obj.put_text(ctx.obj.transcript_key(ctx.org_id, ctx.run_id, task.id), transcript)
            except Exception:
                logger.exception("could not store transcript for %s", task.id)
        await db.update_task(
            task.id,
            status="cancelled" if cancelled else "done",
            verdict=verdict,
            check_results=check_results,
            answer=(answer or "")[:2000],
            duration_s=round(time.monotonic() - started, 1),
            finished_at=_now(),
            error=error,
            sandbox=None,
        )
        await ctx.board.task_done(task)


def _grade_answer(task: EvalTask, answer: str) -> tuple[str, list[dict]]:
    from .grading import grade_checks

    return grade_checks(task.checks, answer)


async def _run_write_task(ctx: TaskContext, task: EvalTask) -> tuple[str, list[dict], str, str, str | None]:
    """The write-task lifecycle (spec §3.4):

    fork -> connection -> setup -> agent -> grade -> capture -> teardown
    with connection+branch deleted in the finally, always.
    """
    from .grading import grade_model_rebuilt

    provider: BranchProvider = ctx.provider
    if provider is None:
        return "ERROR", [], "", "", "no branch provider for write tasks"

    settings: EvalRunSettings = ctx.settings
    branch_name = branch_name_for(ctx.run_id, task.id)

    # Quota and fork under one lock: checking then forking concurrently lets
    # N tasks all observe "under the ceiling" and then all fork past it.
    async with ctx.fork_lock:
        await enforce_branch_quota(provider, settings.max_eval_branches)
        info = await provider.fork(branch_name)
    await ctx.db.update_task(task.id, branch_name=branch_name)

    transcript, answer, error = "", "", None
    verdict: str = "ERROR"
    check_results: list[dict] = []
    setup_ran = False
    conn_name = branch_name[:64]
    try:
        session, store = await ctx.db.store()
        try:
            await create_task_connection(store, name=conn_name, dsn=info.dsn)
        finally:
            await session.close()

        if task.setup:
            await ctx.board.task_phase(task, "setup")
            setup_ran = True
            ok, logs = await _run_script(ctx, task, task.setup, "setup", info.dsn)
            if not ok:
                return "SETUP_FAILED", [], "task setup script failed — see the setup log", "", None

        exit_code, transcript, answer = await _run_agent(ctx, task, conn_name, info.dsn)
        if exit_code != 0 and not answer.strip():
            return "ERROR", [], "", transcript, f"agent container exited {exit_code}"

        # Storage-delta quota, before capture: a runaway build fails the task.
        if ctx.parent_size is not None:
            size = await provider.database_size_bytes(branch_name)
            if size is not None and size - ctx.parent_size > settings.branch_storage_delta_bytes:
                return (
                    "ERROR",
                    [],
                    answer,
                    transcript,
                    f"branch grew {size - ctx.parent_size} bytes — over the "
                    f"{settings.branch_storage_delta_bytes}-byte delta quota",
                )

        await ctx.board.task_phase(task, "grading")
        if task.grade.get("kind") == "model_rebuilt":
            conn, query = await _pg_query(info.dsn)
            try:
                verdict, check_results = await grade_model_rebuilt(task.grade, query)
            finally:
                await conn.close()
        else:
            verdict, check_results = _grade_answer(task, answer)

        # Capture before teardown; a capture bug must never leak a branch, so
        # everything here is caught and reported, never raised.
        if task.capture:
            await ctx.board.task_phase(task, "capture")
            try:
                grain = [str(g) for g in (task.grade.get("expect") or {}).get("grain") or []]
                from .capture import capture_tables

                summary, files = await capture_tables(
                    info.dsn,
                    task.capture,
                    grain=grain,
                    byte_budget=ctx.artifact_budget.remaining,
                    full_max_bytes=settings.capture_full_max_bytes,
                )
                stored = []
                for fname, data in files:
                    if await ctx.artifact_budget.take(len(data)):
                        key = ctx.obj.artifact_key(ctx.org_id, ctx.run_id, task.id, fname)
                        await ctx.obj.put_bytes(key, data)
                        stored.append(fname)
                    else:
                        summary.setdefault("truncated", []).append(fname)
                summary["stored"] = stored
                await ctx.db.update_task(task.id, capture_result=summary)
                await ctx.db.update_run(artifact_bytes=ctx.artifact_budget.spent)
            except Exception as exc:
                from .sandboxes import redact

                capture_error = redact(str(exc), extra_secrets=[info.dsn])[:300]
                logger.error("capture failed for %s: %s", task.id, capture_error)
                await ctx.db.update_task(
                    task.id,
                    capture_result={"error": capture_error},
                )

        return verdict, check_results, answer, transcript, error
    except Exception as exc:
        from .sandboxes import redact

        raise RuntimeError(redact(str(exc), extra_secrets=[info.dsn])) from None
    finally:
        # Always run task cleanup after setup starts.
        # Cleanup can release warehouse resources that branch deletion does not release.
        if task.teardown and setup_ran:
            try:
                await ctx.board.task_phase(task, "teardown")
                await _run_script(ctx, task, task.teardown, "teardown", info.dsn)
            except Exception:
                logger.exception("teardown script failed for %s", task.id)
        # The branch is deleted the moment the task finishes (spec C2). The
        # reaper handles anything this finally cannot reach.
        session, store = await ctx.db.store()
        try:
            await delete_task_connection(store, conn_name)
        finally:
            await session.close()
        try:
            await provider.delete(branch_name)
        except Exception:
            logger.exception("could not delete branch %s — reaper will retry", branch_name)


async def _finalize_run(ctx: TaskContext) -> None:
    db: RunDB = ctx.db
    factory = get_session_factory()
    async with factory() as session:
        tasks = await evals_store.get_tasks(session, org_id=ctx.org_id, run_id=ctx.run_id)

    summary = {
        "total": len(tasks),
        "correct": sum(1 for t in tasks if t["verdict"] == "CORRECT"),
        "partial": sum(1 for t in tasks if t["verdict"] == "PARTIAL"),
        "off": sum(1 for t in tasks if t["verdict"] == "OFF"),
        "unknown": sum(1 for t in tasks if t["verdict"] == "UNKNOWN"),
        "ungraded": sum(1 for t in tasks if t["verdict"] == "UNGRADED"),
        "error": sum(1 for t in tasks if t["verdict"] == "ERROR"),
        "setup_failed": sum(1 for t in tasks if t["verdict"] == "SETUP_FAILED"),
    }

    # Observed coverage from the audit trail + declared covers (spec §3.1).
    coverage = None
    try:
        from .coverage import compute_coverage

        coverage = await compute_coverage(
            ctx.org_id,
            ctx.run_id,
            ctx.eval_set,
            ctx.project_models,
            executed_task_ids=getattr(ctx, "executed_task_ids", None),
        )
    except Exception:
        logger.exception("coverage computation failed for %s", ctx.run_id)

    status = "completed" if summary["error"] + summary["setup_failed"] < summary["total"] else "failed"
    await db.update_run(status=status, summary=summary, coverage=coverage, finished_at=_now())

    run = await db.get_run()
    if run is None:
        return

    graded = summary["total"] - summary["ungraded"]
    accuracy = (summary["correct"] / graded * 100.0) if graded else 0.0
    async with factory() as session:
        try:
            await evals_store.append_accuracy(
                session,
                org_id=ctx.org_id,
                entry={
                    "run_id": ctx.run_id,
                    "created_at": run["created_at"],
                    "trigger": run.get("trigger", "manual"),
                    "eval_set_name": run.get("eval_set_name", ""),
                    "eval_set_ref": run.get("eval_set_ref", ""),
                    "build_fingerprint": run.get("build_fingerprint", ""),
                    "tasks_total": summary["total"],
                    "tasks_passed": summary["correct"],
                    "accuracy_pct": round(accuracy, 2),
                    "coverage_pct": (coverage or {}).get("marts_pct"),
                    "kb_doc_ids": run.get("kb_doc_ids") or [],
                },
            )
        except Exception:
            logger.exception("accuracy history append failed for %s", ctx.run_id)

    try:
        from .notifications import check_regression_and_notify

        await check_regression_and_notify(ctx.org_id, run, tasks, accuracy)
    except Exception:
        logger.exception("regression check failed for %s", ctx.run_id)

    try:
        from .retention import enforce_retention

        await enforce_retention(ctx.org_id)
    except Exception:
        logger.exception("retention enforcement failed for %s", ctx.run_id)
