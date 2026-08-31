"""dbt map compile jobs.

One job per (project, branch, workspace revision). The unique constraint on
gateway_dbt_manifests is the cross-process claim: whichever scheduler inserts
the row owns the compile; everyone else skips. Execution happens on a Vercel
sandbox (never the gateway container):

    snapshot presign -> sandbox boots notebook image (dbt preinstalled)
    -> curl|tar hydrate -> stub profiles.yml -> dbt deps + dbt parse
    -> read target/manifest.json back -> distill graph -> gzip both to S3
    -> row status success/failed

`dbt parse` needs a resolvable profile but never connects to a warehouse, so
the stub profile is a local duckdb target — no credentials ever reach the
sandbox.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import time
import uuid

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from ..config.notebooks import get_notebook_settings
from ..db.models import GatewayDbtManifest, GatewayWorkspaceProject
from ..runtime.mode import is_cloud_mode
from ..sandbox_runtime import SandboxSpec, get_sandbox_runtime
from ..workspace_store import workspace_object_storage
from ..workspace_store.dbt_detect import resolve_dbt_project_dir_detailed
from ..workspace_store.model import dbt_graph_key, dbt_manifest_key
from ..workspace_store.store import RevisionNotFound, WorkspaceStore

logger = logging.getLogger(__name__)

_COMPILE_TIMEOUT_S = 600
_SANDBOX_TIME_LIMIT_S = 900
_LEASE_SECONDS = 1200.0
_SANDBOX_TAG = {"sp-purpose": "dbt-map"}

# One in-flight compile per (project, branch); bounded total concurrency.
_active: dict[tuple[str, str], asyncio.Task] = {}
_semaphore = asyncio.Semaphore(4)

# Failure-mode classification (same shapes gateway/dbt/validator.py matches).
_FAILURE_HINTS = (
    ("Could not find profile", "profile_missing"),
    ("not find profile", "profile_missing"),
    ("could not find package", "package_missing"),
    ("Missing package", "package_missing"),
    ("Parsing Error", "parse_error"),
    ("Compilation Error", "parse_error"),
    ("DependencyNotFound", "parse_error"),
    ("InvalidConfig", "parse_error"),
)

# Written with a heredoc inside the sandbox: reads the project's `profile:`
# name from dbt_project.yml and writes a duckdb stub profiles.yml for it.
_STUB_PROFILE_SCRIPT = """
import yaml, pathlib
proj = yaml.safe_load(pathlib.Path("dbt_project.yml").read_text())
profile = proj.get("profile") or proj.get("name") or "default"
stub = {profile: {"target": "sp", "outputs": {"sp": {
    "type": "duckdb", "path": "/tmp/sp-parse.duckdb", "threads": 1}}}}
out = pathlib.Path("/tmp/sp-profiles"); out.mkdir(parents=True, exist_ok=True)
(out / "profiles.yml").write_text(yaml.safe_dump(stub))
print(f"stub profile written for {profile!r}")
"""


def classify_failure(output: str) -> str | None:
    for needle, label in _FAILURE_HINTS:
        if needle.lower() in output.lower():
            return label
    return None


def _distill_node(node: dict) -> dict:
    """One manifest node with only the fields the lineage UI reads."""
    config = node.get("config") or {}
    slim: dict = {
        "name": node.get("name"),
        "resource_type": node.get("resource_type"),
        "path": node.get("path"),
        "original_file_path": node.get("original_file_path"),
        "fqn": node.get("fqn") or [],
        "schema": node.get("schema"),
        "database": node.get("database"),
        "description": (node.get("description") or "")[:500],
        "tags": node.get("tags") or [],
        "config": {"materialized": config.get("materialized")},
        "columns": {
            name: {"name": name, "description": (col.get("description") or "")[:200]}
            for name, col in (node.get("columns") or {}).items()
        },
    }
    if node.get("test_metadata") is not None:
        slim["test_metadata"] = node["test_metadata"]
    return slim


def distill_graph(manifest: dict) -> dict:
    """Reduce a dbt manifest to what lineage UIs need (~15% of raw size).

    The output is a strict subset of the manifest shape, so the existing
    web parse-manifest.ts consumes it unchanged: `nodes`/`sources` records
    (tests included — the UI derives per-model test chips from them) plus
    parent_map/child_map and light metadata.
    """
    metadata = manifest.get("metadata") or {}
    return {
        "metadata": {
            "dbt_version": metadata.get("dbt_version"),
            "project_name": metadata.get("project_name"),
            "generated_at": metadata.get("generated_at"),
        },
        "nodes": {uid: _distill_node(n) for uid, n in (manifest.get("nodes") or {}).items()},
        "sources": {uid: _distill_node(n) for uid, n in (manifest.get("sources") or {}).items()},
        "parent_map": manifest.get("parent_map", {}),
        "child_map": manifest.get("child_map", {}),
    }


def schedule_compile(org_id: str, project_id: str, branch: str, *, trigger: str = "manual") -> None:
    """Fire-and-forget a compile for the branch head. Coalesces per
    (project, branch): a newer request supersedes a still-running older one."""
    key = (project_id, branch)
    existing = _active.get(key)
    if existing and not existing.done():
        existing.cancel()

    async def _run() -> None:
        async with _semaphore:
            try:
                await run_compile(org_id, project_id, branch, trigger=trigger)
            except asyncio.CancelledError:
                logger.info("dbt-map compile superseded for %s@%s", project_id, branch)
                raise
            except Exception:
                logger.exception("dbt-map compile crashed for %s@%s", project_id, branch)

    task = asyncio.create_task(_run())
    _active[key] = task
    task.add_done_callback(lambda t: _active.pop(key, None) if _active.get(key) is t else None)


async def run_compile(
    org_id: str, project_id: str, branch: str, *, trigger: str = "manual"
) -> GatewayDbtManifest | None:
    """Compile the branch head revision. Returns the row, or None when there
    is nothing to do (no revisions, already compiled, or lost the claim)."""
    from ..db.engine import get_session_factory

    storage = workspace_object_storage()
    if not storage.enabled:
        logger.warning("dbt-map: workspace storage not configured; skipping compile")
        return None
    store = WorkspaceStore(storage)
    factory = get_session_factory()

    async with factory() as session:
        head = await store.head_revision(
            session, org_id=org_id, project_id=project_id, branch=branch
        )
        if head is None:
            logger.info("dbt-map: no revisions for %s@%s; nothing to compile", project_id, branch)
            return None

        row = await _claim(session, org_id, project_id, branch, head, trigger)
        if row is None:
            return None

        try:
            manifest_bytes, dbt_version, error = await _compile_in_sandbox(
                session, store, org_id=org_id, project_id=project_id, branch=branch, revision=head
            )
            if manifest_bytes is None:
                await _finish(session, row.id, status="failed", error=error or "dbt parse failed")
                return await _get_row(session, row.id)

            manifest = json.loads(manifest_bytes)
            graph = distill_graph(manifest)
            m_key = dbt_manifest_key(org_id, project_id, branch, head)
            g_key = dbt_graph_key(org_id, project_id, branch, head)
            manifest_gz = await asyncio.to_thread(gzip.compress, manifest_bytes)
            graph_gz = await asyncio.to_thread(
                gzip.compress, json.dumps(graph, separators=(",", ":")).encode()
            )
            await storage.put_bytes(m_key, manifest_gz, content_type="application/gzip")
            await storage.put_bytes(g_key, graph_gz, content_type="application/gzip")

            await _finish(
                session,
                row.id,
                status="success",
                manifest_key=m_key,
                graph_key=g_key,
                manifest_bytes=len(manifest_bytes),
                node_count=len(graph["nodes"]),
                dbt_version=dbt_version or graph["metadata"].get("dbt_version"),
            )
            logger.info(
                "dbt-map: compiled %s@%s rev %s (%d nodes, %d bytes)",
                project_id, branch, head, len(graph["nodes"]), len(manifest_bytes),
            )
            return await _get_row(session, row.id)
        except asyncio.CancelledError:
            await _finish(session, row.id, status="failed", error="superseded by a newer compile")
            raise
        except Exception as e:
            logger.exception("dbt-map compile failed for %s@%s", project_id, branch)
            await _finish(session, row.id, status="failed", error=str(e)[:2000])
            return await _get_row(session, row.id)


async def _claim(
    session, org_id: str, project_id: str, branch: str, revision: int, trigger: str
) -> GatewayDbtManifest | None:
    """Insert the (project, branch, revision) row, or take over a dead one."""
    now = time.time()
    row = GatewayDbtManifest(
        id=str(uuid.uuid4()),
        org_id=org_id,
        project_id=project_id,
        branch=branch,
        revision=revision,
        status="running",
        trigger=trigger,
        lease_expires_at=now + _LEASE_SECONDS,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    try:
        await session.commit()
        return row
    except IntegrityError:
        await session.rollback()

    existing = (
        await session.execute(
            select(GatewayDbtManifest).where(
                GatewayDbtManifest.project_id == project_id,
                GatewayDbtManifest.branch == branch,
                GatewayDbtManifest.revision == revision,
            )
        )
    ).scalars().first()
    if existing is None:
        return None
    if existing.status == "success":
        return None
    if existing.status == "running" and (existing.lease_expires_at or 0) > now:
        return None
    # failed, or running with a dead lease: take it over.
    result = await session.execute(
        update(GatewayDbtManifest)
        .where(
            GatewayDbtManifest.id == existing.id,
            GatewayDbtManifest.status.in_(["failed", "running", "queued"]),
        )
        .values(
            status="running",
            trigger=trigger,
            error=None,
            lease_expires_at=now + _LEASE_SECONDS,
            updated_at=now,
        )
    )
    await session.commit()
    if result.rowcount == 0:
        return None
    return await _get_row(session, existing.id)


async def _get_row(session, row_id: str) -> GatewayDbtManifest | None:
    return (
        await session.execute(select(GatewayDbtManifest).where(GatewayDbtManifest.id == row_id))
    ).scalars().first()


async def _finish(session, row_id: str, *, status: str, **values) -> None:
    await session.execute(
        update(GatewayDbtManifest)
        .where(GatewayDbtManifest.id == row_id)
        .values(status=status, lease_expires_at=None, updated_at=time.time(), **values)
    )
    await session.commit()


async def _compile_in_sandbox(
    session,
    store: WorkspaceStore,
    *,
    org_id: str,
    project_id: str,
    branch: str,
    revision: int,
) -> tuple[bytes | None, str | None, str | None]:
    """Run dbt parse on a sandbox; return (manifest_bytes, dbt_version, error)."""
    revision, snap_key = await store.build_snapshot(
        session, org_id=org_id, project_id=project_id, branch=branch, revision=revision
    )
    snapshot_url = await store.storage.presign_get(snap_key, expires_seconds=3600)

    project = (
        await session.execute(
            select(GatewayWorkspaceProject).where(
                GatewayWorkspaceProject.org_id == org_id,
                GatewayWorkspaceProject.id == project_id,
            )
        )
    ).scalars().first()
    settings_json = (project.settings if project else None) or {}
    try:
        ws_manifest = await store.load_manifest(
            session, org_id=org_id, project_id=project_id, branch=branch, revision=revision
        )
    except RevisionNotFound:
        return None, None, "workspace revision disappeared"
    dbt_dir, source, _ = resolve_dbt_project_dir_detailed(settings_json, ws_manifest)
    if source == "none":
        return None, None, "no dbt_project.yml found in this project"

    nb = get_notebook_settings()
    image: str | None = None
    bootstrap = ""
    try:
        image = nb.require_vercel_image(cloud=is_cloud_mode())
    except ValueError:
        # No pinned image (e.g. local dev): stock VM + runtime install.
        bootstrap = "pip install --quiet 'dbt-core>=1.7' dbt-duckdb && "

    runtime = get_sandbox_runtime()
    spec = SandboxSpec(
        time_limit_seconds=_SANDBOX_TIME_LIMIT_S,
        image=image,
        tags={**_SANDBOX_TAG, "sp-org": org_id[:64], "sp-project": project_id[:64]},
        env={},
    )
    sandbox_id = await runtime.create(spec)
    try:
        workdir = f"/workspace/{dbt_dir}" if dbt_dir else "/workspace"
        command = (
            "set -e; "
            # The notebook image ships dbt in its venv, not on the login PATH.
            'export PATH="/opt/sp-notebook/.venv/bin:$PATH"; '
            'sudo mkdir -p /workspace && sudo chown "$(id -u):$(id -g)" /workspace; '
            'curl -fsSL "$SP_SNAPSHOT_URL" | tar xz -C /workspace; '
            f"cd {_shq(workdir)}; "
            f"{bootstrap}"
            f"python - <<'SP_EOF'\n{_STUB_PROFILE_SCRIPT}\nSP_EOF\n"
            "dbt deps --no-use-colors --profiles-dir /tmp/sp-profiles || true; "
            "dbt parse --no-use-colors --profiles-dir /tmp/sp-profiles"
        )
        result = await runtime.exec(
            sandbox_id,
            command,
            env={"SP_SNAPSHOT_URL": snapshot_url},
            timeout_seconds=_COMPILE_TIMEOUT_S,
        )
        manifest_bytes = await runtime.read_file(sandbox_id, f"{workdir}/target/manifest.json")
        if manifest_bytes is None:
            output = f"{result.stdout}\n{result.stderr}"
            label = classify_failure(output) or "manifest_missing"
            tail = output.strip()[-1500:]
            return None, None, f"{label}: dbt parse produced no manifest\n{tail}"
        # dbt exits non-zero on parse errors but can still leave a stale
        # manifest behind; trust the exit code.
        if not result.ok:
            output = f"{result.stdout}\n{result.stderr}"
            label = classify_failure(output) or "parse_error"
            return None, None, f"{label}:\n{output.strip()[-1500:]}"
        return manifest_bytes, None, None
    finally:
        try:
            await runtime.destroy(sandbox_id)
        except Exception:
            logger.warning("dbt-map: failed to destroy sandbox %s", sandbox_id)


def _shq(value: str) -> str:
    import shlex

    return shlex.quote(value)


async def reap_stale_compiles() -> int:
    """Fail running/queued rows whose lease expired (gateway died mid-run)."""
    from ..db.engine import get_session_factory

    now = time.time()
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            update(GatewayDbtManifest)
            .where(
                GatewayDbtManifest.status.in_(["running", "queued"]),
                GatewayDbtManifest.lease_expires_at.is_not(None),
                GatewayDbtManifest.lease_expires_at < now,
            )
            .values(
                status="failed",
                error="compile interrupted (gateway restart or timeout)",
                lease_expires_at=None,
                updated_at=now,
            )
        )
        await session.commit()
        return result.rowcount or 0
