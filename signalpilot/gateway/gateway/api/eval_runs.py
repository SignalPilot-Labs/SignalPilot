"""Eval-run endpoints: config, trigger, status ("Evaluate Change" on KB entries).

File-based state (SP_DATA_DIR/eval-runs/<org>) — see gateway/evals/runner.py.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ..config import get_governance_settings
from ..config.evals import get_eval_run_settings
from ..evals import runner
from ..security.scope_guard import RequireScope
from .deps import StoreD

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


async def _require_platform_staff(store: StoreD) -> None:
    """Restrict eval runs to platform staff (SP_ADMIN_USER_IDS).

    Eval runs create containers through the host Docker socket, so an org-admin
    role — which a tenant can grant itself — is not a sufficient gate. In cloud
    deployments SP_ADMIN_USER_IDS is unset by default, which refuses everyone.
    """
    if not store.user_id or store.user_id not in get_governance_settings().admin_user_ids:
        raise HTTPException(status_code=403, detail="Platform staff access required.")


RequireStaff = Depends(_require_platform_staff)

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


@router.get("/evals/config", dependencies=[RequireScope("admin"), RequireStaff])
async def get_eval_config(store: StoreD):
    settings = get_eval_run_settings()
    return {
        "enabled": settings.enabled,
        "runner_image": settings.runner_image,
        **EvalConfig(**runner.load_eval_config(store.org_id)).model_dump(),
    }


@router.put("/evals/config", dependencies=[RequireScope("admin"), RequireStaff])
async def put_eval_config(store: StoreD, cfg: EvalConfig):
    return runner.save_eval_config(store.org_id, cfg.model_dump())


@router.get("/evals/questions", dependencies=[RequireScope("admin"), RequireStaff])
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


@router.post("/evals/runs", status_code=201, dependencies=[RequireScope("admin"), RequireStaff])
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


@router.get("/evals/runs", dependencies=[RequireScope("admin"), RequireStaff])
async def list_eval_runs(store: StoreD):
    return {"runs": runner.list_runs(store.org_id)}


@router.get("/evals/runs/{run_id}", dependencies=[RequireScope("admin"), RequireStaff])
async def get_eval_run(store: StoreD, run_id: str):
    run = runner.read_run(store.org_id, _safe_id(run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get(
    "/evals/runs/{run_id}/setup/{state}/log",
    response_class=PlainTextResponse,
    dependencies=[RequireScope("admin"), RequireStaff],
)
async def get_eval_setup_log(store: StoreD, run_id: str, state: str):
    text = runner.read_setup_log(store.org_id, _safe_id(run_id), state)
    if text is None:
        raise HTTPException(status_code=404, detail="Setup log not found")
    return text


@router.get(
    "/evals/runs/{run_id}/questions/{question_id}/transcript",
    response_class=PlainTextResponse,
    dependencies=[RequireScope("admin"), RequireStaff],
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
