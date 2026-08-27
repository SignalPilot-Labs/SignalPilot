"""Per-chat dbt EXECUTOR sandbox — the credential side of the split-sandbox model.

The chat agent's own sandbox never holds warehouse credentials (stub-profile
parse/compile only). Warehouse-touching dbt commands run HERE: a second Vercel
sandbox, created and driven exclusively by the gateway, holding a generated
profiles.yml under /creds. The agent's only interface is the `dbt_execute` MCP
tool, whose argument surface is a hard allowlist — there is no exec/read/write
tool that accepts this sandbox's identity, so the agent has no path to the
credentials.

Materializations land in a per-chat scratch schema (sp_chat_<run8>), keeping
model builds out of production namespaces. Source reads use the connection's
stored credential unchanged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse, urlunparse

import yaml

from ..config.notebooks import get_notebook_settings
from ..config.sandbox_runtime import get_sandbox_runtime_settings
from ..sandbox_runtime import SandboxRuntimeError, SandboxSpec, get_sandbox_runtime
from ..workspace_store import workspace_object_storage
from ..workspace_store.dbt_detect import resolve_dbt_project_dir_detailed
from ..workspace_store.store import WorkspaceStore

logger = logging.getLogger(__name__)

DBT_EXECUTE_CAPABILITY = "dbt:execute"

# The shared dev database the agent materializes refreshes into (e.g.
# "Analytics_dev"). Prod stays read-only; refreshes land here, in the project's
# normal schemas. Unset => refresh_mart is disabled and the executor falls back
# to the per-chat scratch schema.
_DEV_DATABASE_ENV = "SP_CHAT_DEV_DATABASE"
_DEV_DEFAULT_SCHEMA = "dbo"


def dev_database() -> str | None:
    value = (os.getenv(_DEV_DATABASE_ENV) or "").strip()
    return value or None

_ALLOWED_COMMANDS = {"run", "test", "build", "seed", "snapshot", "compile", "docs"}
# Node-selector syntax only. A leading dash would let a value masquerade as a
# flag, so it is disallowed even though it lands in its own argv slot.
_SELECTOR_RE = re.compile(r"^[\w.+:,*@/][\w .+:,*@/-]*$")
_MAX_OUTPUT_CHARS = 20_000
_MAX_SYNC_TAR_BYTES = 25_000_000
_EXEC_TIMEOUT = 900.0

_PROFILES_DIR = "/creds"
_WORKSPACE = "/workspace"

# One executor per chat execution identity (conversation-scoped), kept warm and
# reused across messages. `_executor_seen` tracks last-use so the idle reaper can
# release executors whose conversation has gone quiet.
_executors: dict[str, str] = {}
_executor_seen: dict[str, float] = {}
_executor_lock = asyncio.Lock()

# How long an executor sandbox stays warm after its last use before the reaper
# releases it. Matches the notebook-session warm window by default.
_EXECUTOR_WARM_ENV = "SP_CHAT_EXECUTOR_WARM_SECONDS"


def _executor_warm_seconds() -> int:
    try:
        return max(60, int(os.getenv(_EXECUTOR_WARM_ENV, "3600")))
    except ValueError:
        return 3600


class DbtExecutorError(RuntimeError):
    pass


def scratch_schema_for(identity: str) -> str:
    """chat:<run_id> -> sp_chat_<first 8 hex of run id>."""
    run_part = identity.split(":", 1)[-1].replace("-", "")[:8] or "run"
    return f"sp_chat_{run_part}"


# ── Profile emitters (credentials never leave this module) ───────────────────


@dataclass(frozen=True)
class EmittedProfile:
    profile_yaml: str
    adapter_package: str  # pip package providing the adapter


def _url_parts(dsn: str):
    u = urlparse(dsn)
    return {
        "host": u.hostname or "",
        "port": u.port,
        "user": unquote(u.username or ""),
        "password": unquote(u.password or ""),
        "database": (u.path or "/").lstrip("/"),
        "query": {k: v[0] for k, v in parse_qs(u.query).items()},
    }


def _emit_postgres(profile_name: str, dsn: str, schema: str) -> EmittedProfile:
    p = _url_parts(dsn)
    out = {
        profile_name: {
            "target": "sp",
            "outputs": {
                "sp": {
                    "type": "postgres",
                    "host": p["host"],
                    "port": p["port"] or 5432,
                    "user": p["user"],
                    "password": p["password"],
                    "dbname": p["database"],
                    "schema": schema,
                    "threads": 4,
                    "sslmode": p["query"].get("sslmode", "prefer"),
                }
            },
        }
    }
    return EmittedProfile(yaml.safe_dump(out), "dbt-postgres")


def _emit_redshift(profile_name: str, dsn: str, schema: str) -> EmittedProfile:
    p = _url_parts(dsn)
    out = {
        profile_name: {
            "target": "sp",
            "outputs": {
                "sp": {
                    "type": "redshift",
                    "host": p["host"],
                    "port": p["port"] or 5439,
                    "user": p["user"],
                    "password": p["password"],
                    "dbname": p["database"],
                    "schema": schema,
                    "threads": 4,
                }
            },
        }
    }
    return EmittedProfile(yaml.safe_dump(out), "dbt-redshift")


def _emit_snowflake(profile_name: str, dsn: str, schema: str) -> EmittedProfile:
    # snowflake://user:pass@account/database/schema?warehouse=...&role=...
    p = _url_parts(dsn)
    path_bits = [b for b in (urlparse(dsn).path or "").split("/") if b]
    database = path_bits[0] if path_bits else p["database"]
    out = {
        profile_name: {
            "target": "sp",
            "outputs": {
                "sp": {
                    "type": "snowflake",
                    "account": p["host"],
                    "user": p["user"],
                    "password": p["password"],
                    "database": database,
                    "schema": schema,
                    "warehouse": p["query"].get("warehouse", ""),
                    "role": p["query"].get("role", ""),
                    "threads": 4,
                }
            },
        }
    }
    return EmittedProfile(yaml.safe_dump(out), "dbt-snowflake")


def _emit_mssql(profile_name: str, dsn: str, schema: str) -> EmittedProfile:
    p = _url_parts(dsn)
    out = {
        profile_name: {
            "target": "sp",
            "outputs": {
                "sp": {
                    "type": "sqlserver",
                    "driver": "ODBC Driver 18 for SQL Server",
                    "server": p["host"],
                    "port": p["port"] or 1433,
                    "user": p["user"],
                    "password": p["password"],
                    "database": p["database"],
                    "schema": schema,
                    "trust_cert": True,
                    "threads": 4,
                }
            },
        }
    }
    return EmittedProfile(yaml.safe_dump(out), "dbt-sqlserver")


_EMITTERS = {
    "postgres": _emit_postgres,
    "redshift": _emit_redshift,
    "snowflake": _emit_snowflake,
    "mssql": _emit_mssql,
}


def _with_database(dsn: str, database: str) -> str:
    """Return dsn with its database path replaced — used to point a multi-db
    connection at the dev materialization target without mutating the stored
    connection string."""
    return urlunparse(urlparse(dsn)._replace(path=f"/{database}"))


def emit_profile(
    db_type: str,
    profile_name: str,
    dsn: str,
    schema: str,
    database_override: str | None = None,
) -> EmittedProfile:
    emitter = _EMITTERS.get(db_type)
    if emitter is None:
        raise DbtExecutorError(
            f"dbt_execute does not support '{db_type}' connections yet "
            f"(supported: {', '.join(sorted(_EMITTERS))}). "
            "Use your own sandbox for dbt parse/compile."
        )
    if database_override:
        dsn = _with_database(dsn, database_override)
    return emitter(profile_name, dsn, schema)


# ── Executor lifecycle ───────────────────────────────────────────────────────


async def _hydrate_project(runtime, sandbox_id: str, snapshot_url: str) -> None:
    result = await runtime.exec(
        sandbox_id,
        # The notebook image runs as root and ships no `sudo`; create the dirs
        # directly and fall back to sudo only if a future image runs non-root.
        "set -e; "
        "mkdir -p /workspace /creds 2>/dev/null || sudo mkdir -p /workspace /creds; "
        "chmod 700 /creds 2>/dev/null || true; "
        'curl -fsSL "$SP_SNAPSHOT_URL" | tar xz -C /workspace',
        env={"SP_SNAPSHOT_URL": snapshot_url},
        timeout_seconds=300,
    )
    if not result.ok:
        raise DbtExecutorError(f"executor hydration failed: {result.stderr[-400:]}")


async def ensure_executor(
    db,
    *,
    identity: str,
    org_id: str,
    project_id: str,
    branch: str,
    connection_name: str,
    store,
    target_database: str | None = None,
    target_schema: str | None = None,
) -> tuple[str, str, str]:
    """Create (or reuse) the executor sandbox. Returns
    (sandbox_id, dbt_project_dir, materialization_schema). Credentials are
    written inside this function and never returned.

    Default mode materializes into the per-chat scratch schema. When
    ``target_database`` is set (the shared dev database), the emitted profile
    targets that database with a normal default schema so the project's own
    schema config (staging/intermediate/marts) applies — this is the
    refresh-into-Analytics_dev path. Dev and scratch executors are cached under
    distinct keys so they never share one profiles.yml."""
    schema = (target_schema or _DEV_DEFAULT_SCHEMA) if target_database else scratch_schema_for(identity)
    cache_key = f"{identity}::dev" if target_database else identity
    async with _executor_lock:
        existing = _executors.get(cache_key)
        if existing:
            _executor_seen[cache_key] = time.monotonic()
            # Project dir/schema are deterministic; recompute cheaply.
            storage = workspace_object_storage()
            ws = WorkspaceStore(storage)
            manifest = await ws.load_manifest(db, org_id=org_id, project_id=project_id, branch=branch)
            project = await store.get_workspace_project(project_id)
            dbt_dir, _, _ = resolve_dbt_project_dir_detailed(
                (project.settings if project else None) or {}, manifest
            )
            return existing, dbt_dir or "", schema

        storage = workspace_object_storage()
        if not storage.enabled:
            raise DbtExecutorError("workspace storage is not configured")
        ws = WorkspaceStore(storage)
        revision, snap_key = await ws.build_snapshot(
            db, org_id=org_id, project_id=project_id, branch=branch
        )
        snapshot_url = await storage.presign_get(snap_key, expires_seconds=3600)
        manifest = await ws.load_manifest(
            db, org_id=org_id, project_id=project_id, branch=branch, revision=revision
        )
        project = await store.get_workspace_project(project_id)
        dbt_dir, source, _ = resolve_dbt_project_dir_detailed(
            (project.settings if project else None) or {}, manifest
        )
        if source == "none":
            raise DbtExecutorError("no dbt_project.yml found in this project")

        dsn = await store.get_connection_string(connection_name)
        if not dsn:
            raise DbtExecutorError(f"connection '{connection_name}' is not available")
        info = await store.get_connection(connection_name)
        db_type = str(getattr(info, "db_type", "") or "").split(".")[-1]

        # Profile name must match dbt_project.yml's `profile:`; read it from the
        # manifest-backed file via the workspace store.
        profile_name = await _read_profile_name(
            db, ws, org_id=org_id, project_id=project_id, branch=branch,
            revision=revision, dbt_dir=dbt_dir or "",
        )
        emitted = emit_profile(
            db_type, profile_name, dsn, schema, database_override=target_database
        )

        runtime = get_sandbox_runtime()
        settings = get_sandbox_runtime_settings()
        nb = get_notebook_settings()
        image = nb.vercel_image or None
        sandbox_id = await runtime.create(
            SandboxSpec(
                time_limit_seconds=settings.time_limit_seconds,
                image=image,
                tags={"sp_execution_identity": f"chat-exec:{identity}", "sp_purpose": "chat-dbt-executor"},
                env={},
            )
        )
        try:
            await _hydrate_project(runtime, sandbox_id, snapshot_url)
            await runtime.write_file(
                sandbox_id, f"{_PROFILES_DIR}/profiles.yml", emitted.profile_yaml.encode()
            )
            # The pinned notebook image ships dbt-core/postgres/snowflake/duckdb;
            # install anything else the connection needs, once per executor.
            await runtime.exec(
                sandbox_id,
                'export PATH="/opt/sp-notebook/.venv/bin:$PATH"; '
                f"pip show {shlex.quote(emitted.adapter_package)} >/dev/null 2>&1 "
                f"|| pip install --quiet {shlex.quote(emitted.adapter_package)}",
                timeout_seconds=420,
            )
            # Install dbt package deps (packages.yml) once per executor — the
            # snapshot carries source files but not the resolved dbt_packages/,
            # so `dbt run/build` would fail with "run dbt deps" without this.
            proj = f"{_WORKSPACE}/{dbt_dir}" if dbt_dir else _WORKSPACE
            await runtime.exec(
                sandbox_id,
                'export PATH="/opt/sp-notebook/.venv/bin:$PATH"; '
                f"dbt deps --no-use-colors --project-dir {shlex.quote(proj)} || true",
                timeout_seconds=300,
            )
        except Exception:
            await runtime.destroy(sandbox_id)
            raise
        _executors[cache_key] = sandbox_id
        _executor_seen[cache_key] = time.monotonic()
        logger.info(
            "dbt executor ready for %s (db_type=%s, database=%s, schema=%s)",
            cache_key, db_type, target_database or "<connection default>", schema,
        )
        return sandbox_id, dbt_dir or "", schema


async def _read_profile_name(
    db, ws: WorkspaceStore, *, org_id: str, project_id: str, branch: str,
    revision: int, dbt_dir: str,
) -> str:
    path = f"{dbt_dir}/dbt_project.yml" if dbt_dir else "dbt_project.yml"
    found = await ws.read_file(
        db, org_id=org_id, project_id=project_id, branch=branch, path=path, revision=revision
    )
    if found is None:
        raise DbtExecutorError(f"{path} not found in workspace revision {revision}")
    try:
        parsed = yaml.safe_load(found[1].decode("utf-8")) or {}
    except Exception as exc:
        raise DbtExecutorError(f"could not parse {path}: {exc}")
    return str(parsed.get("profile") or parsed.get("name") or "default")


async def release_executor(identity: str) -> None:
    async with _executor_lock:
        sandbox_ids = []
        for key in (identity, f"{identity}::dev"):
            sandbox_ids.append(_executors.pop(key, None))
            _executor_seen.pop(key, None)
    runtime = get_sandbox_runtime()
    for sandbox_id in sandbox_ids:
        if sandbox_id:
            try:
                await runtime.destroy(sandbox_id)
            except SandboxRuntimeError:
                pass


async def cleanup_idle_executors() -> int:
    """Release executor sandboxes whose conversation has gone quiet past the warm
    window. Executors are conversation-scoped and kept warm across messages, so
    they are not torn down at run end; this reaper is what eventually frees them
    (and the credential-holding sandbox they carry)."""
    ttl = _executor_warm_seconds()
    now = time.monotonic()
    async with _executor_lock:
        stale = [key for key, seen in _executor_seen.items() if now - seen > ttl]
        sandbox_ids = []
        for key in stale:
            sandbox_ids.append(_executors.pop(key, None))
            _executor_seen.pop(key, None)
    runtime = get_sandbox_runtime()
    released = 0
    for sandbox_id in sandbox_ids:
        if not sandbox_id:
            continue
        try:
            await runtime.destroy(sandbox_id)
            released += 1
        except SandboxRuntimeError:
            pass
    return released


# ── Project sync: agent sandbox -> executor ─────────────────────────────────


async def sync_from_agent_sandbox(agent_sandbox_id: str, executor_sandbox_id: str) -> str:
    """Copy the agent's edited project tree into the executor.

    Excludes build artifacts and anything credential-shaped. Returns a short
    human-readable summary. The tarball travels through the gateway, never
    peer-to-peer, so the executor stays unreachable from the agent."""
    runtime = get_sandbox_runtime()
    pack = await runtime.exec(
        agent_sandbox_id,
        "tar czf /tmp/sp-sync.tgz -C /workspace "
        "--exclude='target' --exclude='dbt_packages' --exclude='.git' "
        "--exclude='profiles.yml' --exclude='.env' --exclude='*.pem' . "
        "&& stat -c %s /tmp/sp-sync.tgz",
        timeout_seconds=120,
    )
    if not pack.ok:
        raise DbtExecutorError(f"could not pack agent workspace: {pack.stderr[-300:]}")
    try:
        size = int(pack.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        size = -1
    if size > _MAX_SYNC_TAR_BYTES:
        raise DbtExecutorError(f"workspace too large to sync ({size} bytes)")
    data = await runtime.read_file(agent_sandbox_id, "/tmp/sp-sync.tgz")
    if data is None:
        raise DbtExecutorError("agent workspace tarball disappeared")
    await runtime.write_file(executor_sandbox_id, "/tmp/sp-sync.tgz", data)
    unpack = await runtime.exec(
        executor_sandbox_id,
        "tar xzf /tmp/sp-sync.tgz -C /workspace && rm -f /tmp/sp-sync.tgz",
        timeout_seconds=120,
    )
    if not unpack.ok:
        raise DbtExecutorError(f"could not unpack into executor: {unpack.stderr[-300:]}")
    return f"synced {len(data)} bytes"


# ── Command execution ────────────────────────────────────────────────────────


def build_dbt_argv(
    command: str,
    *,
    select: str = "",
    exclude: str = "",
    full_refresh: bool = False,
    threads: int = 0,
    dbt_dir: str,
) -> list[str]:
    """Structured args only — no free-form flags, no shell strings."""
    cmd = command.strip().lower()
    parts = cmd.split()
    if not parts or parts[0] not in _ALLOWED_COMMANDS:
        raise DbtExecutorError(
            f"command must be one of: {', '.join(sorted(_ALLOWED_COMMANDS))}"
        )
    if parts[0] == "docs" and parts[1:] != ["generate"]:
        raise DbtExecutorError("only 'docs generate' is allowed")
    if parts[0] != "docs" and len(parts) != 1:
        raise DbtExecutorError("command must be a single dbt subcommand; use select/exclude args")

    argv = ["dbt", *parts, "--no-use-colors", "--profiles-dir", _PROFILES_DIR, "--target", "sp"]
    project_dir = f"{_WORKSPACE}/{dbt_dir}" if dbt_dir else _WORKSPACE
    argv += ["--project-dir", project_dir]
    for label, value in (("--select", select), ("--exclude", exclude)):
        if value:
            if not _SELECTOR_RE.match(value):
                raise DbtExecutorError(f"invalid characters in {label} value")
            argv += [label, value]
    if full_refresh:
        argv.append("--full-refresh")
    if threads:
        argv += ["--threads", str(max(1, min(8, int(threads))))]
    return argv


async def run_dbt_command(sandbox_id: str, argv: list[str], dbt_dir: str) -> str:
    runtime = get_sandbox_runtime()
    shell = 'export PATH="/opt/sp-notebook/.venv/bin:$PATH"; ' + " ".join(
        shlex.quote(a) for a in argv
    )
    result = await runtime.exec(sandbox_id, shell, timeout_seconds=_EXEC_TIMEOUT)

    sections = [f"exit_code: {result.returncode}"]
    output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
    if len(output) > _MAX_OUTPUT_CHARS:
        output = output[-_MAX_OUTPUT_CHARS:]
    sections.append(f"output:\n{output.strip()}")

    project_dir = f"{_WORKSPACE}/{dbt_dir}" if dbt_dir else _WORKSPACE
    rr = await runtime.read_file(sandbox_id, f"{project_dir}/target/run_results.json")
    if rr:
        try:
            parsed = json.loads(rr)
            statuses: dict[str, int] = {}
            failures = []
            for r in parsed.get("results", []):
                status = str(r.get("status"))
                statuses[status] = statuses.get(status, 0) + 1
                if status in ("error", "fail") and len(failures) < 10:
                    failures.append(f"{r.get('unique_id')}: {str(r.get('message'))[:200]}")
            sections.append("run_results: " + ", ".join(f"{k}={v}" for k, v in sorted(statuses.items())))
            if failures:
                sections.append("failures:\n" + "\n".join(failures))
        except Exception:
            pass
    return "\n".join(sections)
