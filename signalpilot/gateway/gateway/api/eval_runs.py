"""Eval-run endpoints: config, trigger, status, accuracy record, export.

State lives in Postgres (gateway.store.evals); transcripts, setup logs and
captures live in S3 (gateway.evals.object_store).
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import time
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from ..config import get_governance_settings
from ..config.evals import get_eval_run_settings
from ..evals import runner, sandboxes
from ..evals.object_store import EvidenceStoreDisabled, get_object_store
from ..security.scope_guard import RequireScope
from .deps import StoreD

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


async def _require_allowed_org(store: StoreD) -> None:
    """Restrict evals to the orgs named in SP_EVAL_ALLOWED_ORGS.

    The active org is what carries the eval state, so a user switching into a
    non-allowlisted org loses access.
    """
    if not get_eval_run_settings().org_allowed(store.org_id):
        raise HTTPException(status_code=403, detail="Evals are not enabled for this workspace.")


RequireAllowedOrg = Depends(_require_allowed_org)

# The routes use three access tiers because each tier has different risks.
# Assign each new route to one of these lists.
# tests/test_eval_org_allowlist.py verifies that each route has an access tier.
#
# READ permits access to configuration metadata, task lists, run status, and progress.
# EVIDENCE permits access to transcripts, captures, artifacts, and exports.
# This evidence can contain warehouse data and agent output.
# EXECUTE permits operations that incur costs, change configuration, or select a repository.
#
# Org membership is the tenancy boundary; platform staff membership is not
# consulted. SP_ADMIN_USER_IDS is unset in cloud, so a staff gate here refuses
# every caller and the page renders its setup card for orgs the allowlist would
# in fact admit. RequireAllowedOrg is the gate that carries the access decision.
EVAL_GUARDS = [RequireScope("read"), RequireAllowedOrg]
EVAL_EVIDENCE_GUARDS = [RequireScope("query"), RequireAllowedOrg]
EVAL_EXECUTE_GUARDS = [RequireScope("admin"), RequireAllowedOrg]

# In-process registry so a second trigger doesn't stack runs unboundedly.
_active_tasks: dict[str, asyncio.Task] = {}
_MAX_CONCURRENT_RUNS = 2

# The gateway assembles the export in memory. This limit bounds memory use.
EXPORT_MAX_BYTES = 256 * 1024 * 1024


class EvalConfig(BaseModel):
    repo_url: str = Field("", max_length=2048)
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


class EvalRunRequest(BaseModel):
    """A run grades the eval set; doc_ids overlay *proposed* entries on top.

    Empty doc_ids is the baseline: the knowledge base exactly as it stands.
    """

    doc_ids: list[str] = Field(default_factory=list, max_length=20)
    task_ids: list[str] | None = Field(None, max_length=200)


@router.get("/evals/availability", dependencies=[RequireScope("read")])
async def get_eval_availability(store: StoreD):
    """Return whether the caller can use evaluations.

    This route does not report access for other callers. It must agree with
    EVAL_GUARDS: a probe stricter than the routes tells a caller it is shut out
    of a feature those routes would have admitted it to.
    """
    if not get_eval_run_settings().org_allowed(store.org_id):
        return {"enabled": False, "reason": "not_enabled_for_org"}
    return {"enabled": True, "reason": "ok"}


@router.get("/evals/config", dependencies=EVAL_GUARDS)
async def get_eval_config(store: StoreD):
    settings = get_eval_run_settings()
    cfg = await store.get_eval_config()
    return {
        "enabled": settings.enabled,
        "runner_image": settings.runner_image,
        **EvalConfig(**cfg).model_dump(),
    }


@router.put("/evals/config", dependencies=EVAL_EXECUTE_GUARDS)
async def put_eval_config(store: StoreD, cfg: EvalConfig):
    pin = await _require_pinned_connection(store, cfg.connection)
    cfg = cfg.model_copy(update={"connection": pin})
    return await store.save_eval_config(cfg.model_dump(mode="json"))


async def _require_pinned_connection(store: StoreD, connection: str | None) -> str:
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


@router.get("/evals/tasks", dependencies=EVAL_GUARDS)
async def list_eval_tasks(store: StoreD):
    """The configured eval set (metadata + tasks), for the /evals page."""
    cfg = await store.get_eval_config()
    settings = get_eval_run_settings()
    try:
        eval_set = await runner.get_eval_set(store.org_id, cfg, settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "name": eval_set.name,
        "description": eval_set.description,
        "ref": eval_set.ref,
        "project_repo": eval_set.project_repo,
        "build_fingerprint": eval_set.build_fingerprint,
        "setup": eval_set.setup,
        "tasks": [
            {
                "id": t.id,
                "class": t.task_class,
                "kind": t.kind,
                "gt": t.gt,
                "title": t.title,
                "why": t.why,
                "prompt": t.prompt,
                "doc": t.doc,
                "checks": t.checks,
                "grade": t.grade,
                "covers": t.covers,
                "builds": t.builds,
                "capture": t.capture,
                "setup": t.setup,
                "teardown": t.teardown,
            }
            for t in eval_set.tasks
        ],
    }


@router.post("/evals/runs", status_code=201, dependencies=EVAL_EXECUTE_GUARDS)
async def start_eval_run(store: StoreD, req: EvalRunRequest):
    settings = get_eval_run_settings()
    if not settings.enabled:
        raise HTTPException(status_code=404, detail="Eval runs are not enabled (SP_EVAL_RUNNER_IMAGE unset)")
    if not settings.s3_bucket:
        raise HTTPException(status_code=422, detail="Eval evidence bucket is not configured (SP_EVAL_S3_BUCKET)")
    cfg = await store.get_eval_config()
    if not cfg.get("repo_url"):
        raise HTTPException(status_code=400, detail="No eval repo configured — set one on the Evals page")

    await _require_pinned_connection(store, cfg.get("connection"))

    # Resolve the proposed docs now so bad IDs fail fast and the UI gets titles.
    titles: list[str] = []
    for doc_id in req.doc_ids:
        doc = await store.get_knowledge_doc(doc_id, include_body=False)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"Knowledge doc not found: {doc_id}")
        titles.append(doc.title)

    _active_tasks_prune()
    if len(_active_tasks) >= _MAX_CONCURRENT_RUNS:
        raise HTTPException(status_code=409, detail="Too many eval runs in flight — wait for one to finish")

    return await _launch_run(
        store,
        doc_ids=req.doc_ids,
        doc_titles=titles,
        task_ids=req.task_ids,
        trigger="manual",
    )


async def _launch_run(
    store: StoreD,
    *,
    doc_ids: list[str],
    doc_titles: list[str],
    task_ids: list[str] | None,
    trigger: str,
) -> dict:
    """Create the run row, create its scoped key, and start the background task.

    The HTTP route and automatic run use this function for consistent key handling.
    Callers perform the concurrency check.
    """
    import hashlib
    from datetime import UTC, datetime

    from ..store import evals as evals_store

    cfg = await store.get_eval_config()
    connection = await _require_pinned_connection(store, cfg.get("connection"))
    run_id = runner.new_run_id()
    # This hash contains each configuration value that an operator can change.
    # Regression attribution requires the same hash before it identifies a knowledge change as the cause.
    config_hash = hashlib.sha256(
        "\x00".join(
            [
                str(cfg.get("model", "")),
                str(cfg.get("prompt_preamble", "")),
                str(cfg.get("connection", "")),
                str(cfg.get("max_tasks", 0)),
            ]
        ).encode()
    ).hexdigest()[:32]
    run = await evals_store.create_run(
        store.session,
        org_id=store.org_id,
        run_id=run_id,
        created_at=datetime.now(UTC).isoformat(),
        trigger=trigger,
        doc_ids=doc_ids,
        doc_titles=doc_titles,
        task_filter=task_ids,
        repo_url=cfg.get("repo_url", ""),
        model=cfg.get("model", "sonnet"),
    )

    # MCP authentication requires a stored key when a stored key exists.
    # Create a scoped key for this run. The runner revokes it when the run finishes.
    # Commit the key before the evaluation container connects.
    # The key expires and is bound to the run.
    # Recovery uses eval_run_id to revoke a key after an interrupted process.
    from datetime import UTC, datetime, timedelta

    key_record, raw_key = await store.create_api_key(
        f"eval-{run_id}",
        ["read", "query"],
        expires_at=(datetime.now(UTC) + timedelta(seconds=runner.TASK_KEY_TTL_S)).isoformat(),
        eval_binding={
            "run_id": run_id,
            "connection": connection,
            "doc_ids": doc_ids,
        },
    )
    await evals_store.update_run(
        store.session,
        org_id=store.org_id,
        run_id=run_id,
        api_key_id=key_record.id,
        config_hash=config_hash,
    )
    await store.session.commit()

    task = asyncio.create_task(
        runner.execute_run(store.org_id, run_id, api_key=raw_key, api_key_id=key_record.id)
    )
    _active_tasks[run_id] = task
    logger.info("Eval run %s started (docs=%s, trigger=%s)", run_id, doc_ids, trigger)
    run["tasks"] = []
    return run


def _active_tasks_prune() -> None:
    for run_id in [rid for rid, t in _active_tasks.items() if t.done()]:
        _active_tasks.pop(run_id, None)


# Per-org timestamp of the last autorun, for coalescing.
_last_autorun: dict[str, float] = {}
_AUTORUN_DEBOUNCE_SECONDS = 120.0


async def maybe_autorun_after_knowledge_change(store, doc) -> None:
    """Start a baseline eval run when the knowledge base receives an entry.

    The function starts a run only for an active entry.
    It suppresses errors because an evaluation failure must not fail the knowledge write.
    """
    try:
        status = getattr(doc, "status", None)
        if getattr(status, "value", status) != "active":
            return

        settings = get_eval_run_settings()
        if not settings.enabled or not settings.org_allowed(store.org_id):
            return
        if not store.user_id or store.user_id not in get_governance_settings().admin_user_ids:
            return

        cfg = await store.get_eval_config()
        if not cfg.get("autorun_on_knowledge_add") or not cfg.get("repo_url"):
            return

        _active_tasks_prune()
        if len(_active_tasks) >= _MAX_CONCURRENT_RUNS:
            logger.info("Autorun skipped for org %s: runs already in flight", store.org_id)
            return

        now = time.time()
        last = _last_autorun.get(store.org_id, 0.0)
        if now - last < _AUTORUN_DEBOUNCE_SECONDS:
            logger.info(
                "Autorun skipped for org %s: within %.0fs debounce",
                store.org_id,
                _AUTORUN_DEBOUNCE_SECONDS,
            )
            return
        _last_autorun[store.org_id] = now

        run = await _launch_run(
            store, doc_ids=[], doc_titles=[], task_ids=None, trigger="kb_add"
        )
        logger.info(
            "Autorun %s started for org %s after knowledge entry %s became active",
            run["id"],
            store.org_id,
            getattr(doc, "id", "?"),
        )
    except Exception:
        logger.exception("Autorun after knowledge change failed for org %s", store.org_id)


@router.get("/evals/runs", dependencies=EVAL_GUARDS)
async def list_eval_runs(store: StoreD):
    return {"runs": await store.list_eval_runs()}


@router.get("/evals/runs/{run_id}", dependencies=EVAL_GUARDS)
async def get_eval_run(store: StoreD, run_id: str):
    run = await store.get_eval_run(_safe_id(run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get(
    "/evals/runs/{run_id}/tasks/{task_id}/setup/{phase}/log",
    response_class=PlainTextResponse,
    dependencies=EVAL_EVIDENCE_GUARDS,
)
async def get_eval_setup_log(store: StoreD, run_id: str, task_id: str, phase: str):
    obj = _object_store_or_422()
    key = obj.setup_log_key(store.org_id, _safe_id(run_id), task_id, phase)
    text = await obj.get_text(key)
    if text is None:
        raise HTTPException(status_code=404, detail="Setup log not found")
    return text


@router.get(
    "/evals/runs/{run_id}/tasks/{task_id}/transcript",
    response_class=PlainTextResponse,
    dependencies=EVAL_EVIDENCE_GUARDS,
)
async def get_eval_transcript(store: StoreD, run_id: str, task_id: str):
    obj = _object_store_or_422()
    text = await obj.get_text(obj.transcript_key(store.org_id, _safe_id(run_id), task_id))
    if text is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return text


@router.get("/evals/runs/{run_id}/artifacts", dependencies=EVAL_EVIDENCE_GUARDS)
async def list_eval_artifacts(store: StoreD, run_id: str):
    obj = _object_store_or_422()
    prefix = obj.artifacts_prefix(store.org_id, _safe_id(run_id))
    objects = await obj.list_keys(prefix)
    return {
        "artifacts": [
            {"path": o["key"].removeprefix(prefix), "bytes": o["size"]} for o in objects
        ]
    }


@router.get("/evals/runs/{run_id}/artifacts/{task_id}/{filename}", dependencies=EVAL_EVIDENCE_GUARDS)
async def download_eval_artifact(store: StoreD, run_id: str, task_id: str, filename: str):
    obj = _object_store_or_422()
    data = await obj.get_bytes(obj.artifact_key(store.org_id, _safe_id(run_id), task_id, filename))
    if data is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/evals/runs/{run_id}/export", dependencies=EVAL_EVIDENCE_GUARDS)
async def export_eval_run(store: StoreD, run_id: str):
    """Create an archive that retains run data beyond the retention window."""
    run_id = _safe_id(run_id)
    run = await store.get_eval_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    obj = _object_store_or_422()

    buf = io.BytesIO()
    total = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("run.json", json.dumps(run, indent=2, default=str))
        prefix = obj.run_prefix(store.org_id, run_id) + "/"
        tarball = obj.project_tarball_key(store.org_id, run_id)
        for entry in await obj.list_keys(prefix):
            # The transport tarball contains the customer's complete dbt project.
            # Exclude it from the archive because it only transports files to the pods.
            if entry["key"] == tarball:
                continue
            total += entry["size"]
            if total > EXPORT_MAX_BYTES:
                zf.writestr(
                    "TRUNCATED.txt",
                    f"export stopped at {EXPORT_MAX_BYTES} bytes; fetch the remaining "
                    "artifacts individually from the artifacts endpoint",
                )
                break
            data = await obj.get_bytes(entry["key"])
            if data is not None:
                zf.writestr(entry["key"].removeprefix(prefix), data)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{run_id}.zip"'},
    )


@router.get("/evals/accuracy", dependencies=EVAL_GUARDS)
async def get_eval_accuracy(store: StoreD, limit: int = Query(200, ge=1, le=1000)):
    """Return the permanent accuracy record and the detected regressions."""
    return {
        "history": await store.list_eval_accuracy(limit=limit),
        "regressions": await store.list_eval_regressions(),
    }


def _object_store_or_422():
    try:
        return get_object_store()
    except EvidenceStoreDisabled as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _safe_id(run_id: str) -> str:
    import re

    if not re.fullmatch(r"run-[0-9]{8}-[0-9]{6}-[a-f0-9]{6}", run_id):
        raise HTTPException(status_code=400, detail="Invalid run id")
    return run_id


# Sandbox panel for the containers that execute a run.
#
# The routes provide read-only access within one organization.
# The view layer does not return pod or container specifications.
# The view layer also redacts free text to prevent credential disclosure.

MAX_LOG_STREAMS: int = 8
_LOG_HEARTBEAT_SECONDS: float = 10.0
_log_stream_semaphore = asyncio.Semaphore(MAX_LOG_STREAMS)


def _safe_sandbox_name(name: str) -> str:
    if not sandboxes.is_valid_sandbox_name(name):
        raise HTTPException(status_code=400, detail="Invalid sandbox name")
    return name


@router.get("/evals/sandboxes", dependencies=EVAL_GUARDS)
async def list_eval_sandboxes(store: StoreD):
    """Eval containers alive right now for the caller's org."""
    view = sandboxes.get_sandbox_view(store.org_id)
    try:
        return await view.inventory()
    finally:
        await view.aclose()


@router.get("/evals/sandboxes/{name}/events", dependencies=EVAL_GUARDS)
async def get_eval_sandbox_events(store: StoreD, name: str):
    """Recent Kubernetes events for a sandbox pod: what makes a stuck pod
    diagnosable (unschedulable, image pull failure, sandbox runtime error)."""
    view = sandboxes.get_sandbox_view(store.org_id)
    try:
        return await view.events(_safe_sandbox_name(name))
    finally:
        await view.aclose()


@router.get("/evals/sandboxes/{name}/logs/stream", dependencies=EVAL_GUARDS)
async def stream_eval_sandbox_logs(
    store: StoreD, name: str, tail: int = Query(200, ge=1, le=2000)
) -> StreamingResponse:
    """SSE tail of a live sandbox.

    Terminates on its own when the sandbox exits, when the byte cap or the
    wall-clock deadline is hit, or when the viewer disconnects.
    """
    safe_name = _safe_sandbox_name(name)
    if _log_stream_semaphore.locked():
        raise HTTPException(
            status_code=429,
            detail="Too many sandbox log streams open. Close one and retry.",
            headers={"Retry-After": "15"},
        )
    view = sandboxes.get_sandbox_view(store.org_id)

    async def generate():
        await _log_stream_semaphore.acquire()
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)

        async def pump() -> None:
            try:
                async for kind, payload in view.stream_logs(safe_name, tail_lines=tail):
                    await queue.put((kind, payload))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Eval sandbox log stream for %s failed: %s", safe_name, exc)
                await queue.put(("error", f"log stream failed: {type(exc).__name__}"))
                await queue.put(("end", "stream-error"))
            finally:
                await queue.put(None)

        task = asyncio.create_task(pump())
        try:
            yield _sse({"type": "open", "sandbox": safe_name, "at": time.time()})
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=_LOG_HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield _sse({"type": "heartbeat", "at": time.time()})
                    continue
                if item is None:
                    return
                kind, payload = item
                if kind == "end":
                    yield _sse({"type": "end", "reason": payload, "at": time.time()})
                    return
                yield _sse({"type": kind, "text": sandboxes.redact(payload), "at": time.time()})
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            await view.aclose()
            _log_stream_semaphore.release()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.get("/evals/runs/{run_id}/progress", dependencies=EVAL_GUARDS)
async def get_eval_run_progress(store: StoreD, run_id: str):
    """Where a run is right now: phase, active tasks, done/total, elapsed."""
    run = await store.get_eval_run(_safe_id(run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return runner.derive_progress(run)
