"""Eval-run endpoints: config, trigger, status ("Evaluate Change" on KB entries).

File-based state (SP_DATA_DIR/eval-runs/<org>) — see gateway/evals/runner.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..config import get_governance_settings
from ..config.evals import get_eval_run_settings
from ..evals import runner, sandboxes
from ..security.scope_guard import RequireScope
from .deps import StoreD

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def _is_platform_staff(store: StoreD) -> bool:
    return bool(store.user_id) and store.user_id in get_governance_settings().admin_user_ids


async def _require_platform_staff(store: StoreD) -> None:
    """Restrict eval runs to platform staff (SP_ADMIN_USER_IDS).

    Eval runs execute model-authored commands in a container (the host Docker
    socket locally, a sandboxed pod in cloud), so an org-admin role — which a
    tenant can grant itself — is not a sufficient gate. In cloud deployments
    SP_ADMIN_USER_IDS is unset by default, which refuses everyone.
    """
    if not _is_platform_staff(store):
        raise HTTPException(status_code=403, detail="Platform staff access required.")


async def _require_allowed_org(store: StoreD) -> None:
    """Restrict evals to the orgs named in SP_EVAL_ALLOWED_ORGS.

    Independent of the staff gate above: staff switching into a non-allowlisted
    org loses access, because the active org is what carries the eval state.
    """
    if not get_eval_run_settings().org_allowed(store.org_id):
        raise HTTPException(status_code=403, detail="Evals are not enabled for this workspace.")


RequireStaff = Depends(_require_platform_staff)
RequireAllowedOrg = Depends(_require_allowed_org)

# Every eval route carries all three. Adding a route means reusing this list —
# tests/test_eval_org_allowlist.py enumerates router.routes, so one that is
# gated some other way fails there rather than shipping ungated.
EVAL_GUARDS = [RequireScope("admin"), RequireStaff, RequireAllowedOrg]

# In-process registry so a second trigger doesn't stack runs unboundedly.
_active_tasks: dict[str, asyncio.Task] = {}
_MAX_CONCURRENT_RUNS = 2


class EvalConfig(BaseModel):
    repo_url: str = Field("", max_length=2048)
    model: str = Field("sonnet", max_length=64)
    max_questions: int = Field(0, ge=0, le=100)  # 0 = all
    prompt_preamble: str = Field("", max_length=4000)


class EvalRunRequest(BaseModel):
    doc_ids: list[str] = Field(..., min_length=1, max_length=20)
    question_ids: list[str] | None = Field(None, max_length=100)


@router.get("/evals/availability", dependencies=[RequireScope("read")])
async def get_eval_availability(store: StoreD):
    """Whether the caller may use evals — the only eval route the gates let through.

    Deliberately says nothing about who else is allowed: no org id (not even the
    caller's), no allowlist size, no runner config. The reason is what the page
    needs to pick a setup state, and nothing more.
    """
    if not get_eval_run_settings().org_allowed(store.org_id):
        return {"enabled": False, "reason": "not_enabled_for_org"}
    if not _is_platform_staff(store):
        return {"enabled": False, "reason": "not_staff"}
    return {"enabled": True, "reason": "ok"}


@router.get("/evals/config", dependencies=EVAL_GUARDS)
async def get_eval_config(store: StoreD):
    settings = get_eval_run_settings()
    return {
        "enabled": settings.enabled,
        "runner_image": settings.runner_image,
        **EvalConfig(**runner.load_eval_config(store.org_id)).model_dump(),
    }


@router.put("/evals/config", dependencies=EVAL_GUARDS)
async def put_eval_config(store: StoreD, cfg: EvalConfig):
    return runner.save_eval_config(store.org_id, cfg.model_dump())


@router.get("/evals/questions", dependencies=EVAL_GUARDS)
async def list_eval_questions(store: StoreD):
    """The configured eval set (metadata + questions), for the /evals page."""
    try:
        eval_set = await runner.get_eval_set(store.org_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    questions = eval_set.questions
    return {
        "name": eval_set.name,
        "description": eval_set.description,
        "setup": eval_set.setup,
        "questions": [
            {
                "id": q.id,
                "kind": q.kind,
                "state": q.state,
                "gt": q.gt,
                "title": q.title,
                "why": q.why,
                "prompt": q.prompt,
                "doc": q.doc,
                "checks": q.checks,
            }
            for q in questions
        ]
    }


@router.post("/evals/runs", status_code=201, dependencies=EVAL_GUARDS)
async def start_eval_run(store: StoreD, req: EvalRunRequest):
    settings = get_eval_run_settings()
    if not settings.enabled:
        raise HTTPException(status_code=404, detail="Eval runs are not enabled (SP_EVAL_RUNNER_IMAGE unset)")
    cfg = runner.load_eval_config(store.org_id)
    if not cfg.get("repo_url"):
        raise HTTPException(status_code=400, detail="No eval repo configured — set one on the Evals page")

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

    run = runner.create_run(
        store.org_id, doc_ids=req.doc_ids, doc_titles=titles, question_ids=req.question_ids
    )

    # MCP auth requires a real stored key once any exist — mint a scoped key
    # for this run; the runner revokes it when the run finishes. Commit now:
    # the eval container connects before this request's session would flush.
    key_record, raw_key = await store.create_api_key(f"eval-{run['id']}", ["read", "write"])
    await store.session.commit()

    task = asyncio.create_task(
        runner.execute_run(store.org_id, run["id"], api_key=raw_key, api_key_id=key_record.id)
    )
    _active_tasks[run["id"]] = task
    logger.info("Eval run %s started (docs=%s)", run["id"], req.doc_ids)
    return run


def _active_tasks_prune() -> None:
    for run_id in [rid for rid, t in _active_tasks.items() if t.done()]:
        _active_tasks.pop(run_id, None)


@router.get("/evals/runs", dependencies=EVAL_GUARDS)
async def list_eval_runs(store: StoreD):
    return {"runs": runner.list_runs(store.org_id)}


@router.get("/evals/runs/{run_id}", dependencies=EVAL_GUARDS)
async def get_eval_run(store: StoreD, run_id: str):
    run = runner.read_run(store.org_id, _safe_id(run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get(
    "/evals/runs/{run_id}/setup/{state}/log",
    response_class=PlainTextResponse,
    dependencies=EVAL_GUARDS,
)
async def get_eval_setup_log(store: StoreD, run_id: str, state: str):
    text = runner.read_setup_log(store.org_id, _safe_id(run_id), state)
    if text is None:
        raise HTTPException(status_code=404, detail="Setup log not found")
    return text


@router.get(
    "/evals/runs/{run_id}/questions/{question_id}/transcript",
    response_class=PlainTextResponse,
    dependencies=EVAL_GUARDS,
)
async def get_eval_transcript(store: StoreD, run_id: str, question_id: str):
    text = runner.read_transcript(store.org_id, _safe_id(run_id), question_id)
    if text is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return text


def _safe_id(run_id: str) -> str:
    import re

    if not re.fullmatch(r"run-[0-9]{8}-[0-9]{6}-[a-f0-9]{6}", run_id):
        raise HTTPException(status_code=400, detail="Invalid run id")
    return run_id


# ─── Sandbox panel (live view of the containers a run is executing in) ───────
#
# Read-only, staff-gated and org-scoped like every route above. The view layer
# (gateway/evals/sandboxes.py) never returns a pod or container spec, so the
# credentials those carry cannot reach a response; the free text that a cluster
# can put in front of us is redacted there.

# One log stream holds an open connection to the cluster for as long as the
# sandbox lives, so viewers are capped globally rather than per user.
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
    """Recent Kubernetes events for a sandbox pod — what makes a stuck pod
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

    Terminates on its own when the sandbox exits (the follow stream closes),
    when the byte cap or the wall-clock deadline is hit, or when the viewer
    disconnects — the pump task is cancelled in `finally` either way, so a
    closed tab never leaves a task or an open cluster connection behind.
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
                    # Signs of life for the connection itself, so the panel can
                    # tell "the agent is quiet" from "the stream is dead".
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
    """Where a run is right now: phase, question index, elapsed, live sandbox."""
    run = runner.read_run(store.org_id, _safe_id(run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return runner.run_progress(run)
