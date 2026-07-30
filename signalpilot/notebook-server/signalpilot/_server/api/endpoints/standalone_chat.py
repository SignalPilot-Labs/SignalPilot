"""Internal streaming execution endpoint for durable standalone data chat."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, StreamingResponse

from signalpilot._server.ai.claude_agent import (
    clear_chat_session,
    run_notebook_agent,
    stop_agent,
)
from signalpilot._server.ai.standalone_chat_tools import (
    StandaloneArtifactCollector,
    build_standalone_chat_mcp_server,
)
from signalpilot._server.router import APIRouter
from signalpilot._types.ids import SessionId

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from starlette.requests import Request

router = APIRouter()
_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9-]{8,80}$")

STANDALONE_ALLOWED_TOOLS = [
    "mcp__signalpilot__check_budget",
    "mcp__signalpilot__connector_capabilities",
    "mcp__signalpilot__debug_cte_query",
    "mcp__signalpilot__describe_table",
    "mcp__signalpilot__estimate_query_cost",
    "mcp__signalpilot__explain_query",
    "mcp__signalpilot__explore_column",
    "mcp__signalpilot__explore_columns",
    "mcp__signalpilot__explore_table",
    "mcp__signalpilot__find_join_path",
    "mcp__signalpilot__get_date_boundaries",
    "mcp__signalpilot__get_relationships",
    "mcp__signalpilot__list_database_connections",
    "mcp__signalpilot__list_semantic_metrics",
    "mcp__signalpilot__list_tables",
    "mcp__signalpilot__query_database",
    "mcp__signalpilot__schema_ddl",
    "mcp__signalpilot__schema_link",
    "mcp__signalpilot__schema_overview",
    "mcp__signalpilot__schema_statistics",
    "mcp__signalpilot__validate_sql",
    "mcp__signalpilot__verify_metric_conformance",
    "mcp__standalone-chat__publish_chart",
    "mcp__standalone-chat__publish_report",
    "mcp__standalone-chat__publish_table",
    "mcp__standalone-chat__run_scratch_python",
]

STANDALONE_SYSTEM_PROMPT = """You are SignalPilot Data Chat, helping a non-technical business user answer questions from one governed project.

Rules:
- Respond in English only and lead with the business answer.
- Inspect the supplied dbt metadata, schema, and relevant data before asking a question.
- Query only the selected connection shown below. Queries must be read-only.
- Do not modify a database, project, notebook, file, external system, or repository.
- Use restricted scratch Python only for in-memory calculations.
- Ask for clarification only when exploration leaves a material ambiguity that would change the answer. If needed, return exactly `CLARIFICATION_REQUESTED: <one conversational question>`.
- Choose text, a table, a chart, or a report automatically. Publish every displayed table, chart, or report with the publication tools.
- Never guess. State freshness, assumptions, exclusions, truncation, and caveats explicitly.
- Never mention or expose confidence scores, hidden reasoning, chain-of-thought, credentials, or implementation internals.
- Do not suggest follow-up questions.
"""


def _require_execution_scope(body: dict[str, Any]) -> tuple[str, str, str, str]:
    run_id = str(body.get("run_id") or "")
    project_id = str(body.get("project_id") or "")
    branch = str(body.get("branch") or "")
    connection_name = str(body.get("connection_name") or "")
    if not _RUN_ID_RE.fullmatch(run_id):
        raise HTTPException(status_code=400, detail="Invalid run id")
    expected = {
        "run": os.getenv("SP_CHAT_RUN_ID"),
        "project": os.getenv("SP_CHAT_PROJECT_ID"),
        "branch": os.getenv("SP_CHAT_BRANCH"),
        "connection": os.getenv("SP_CHAT_CONNECTION_NAME"),
    }
    supplied = {
        "run": run_id,
        "project": project_id,
        "branch": branch,
        "connection": connection_name,
    }
    for key, value in expected.items():
        if value and supplied[key] != value:
            raise HTTPException(status_code=403, detail="Execution scope mismatch")
    return run_id, project_id, branch, connection_name


def _scoped_gateway_mcp_config(
    body: dict[str, Any],
    *,
    run_id: str,
    project_id: str,
    branch: str,
    connection_name: str,
) -> dict[str, Any]:
    token = str(body.get("gateway_session_token") or "").strip()
    if not token:
        raise HTTPException(status_code=403, detail="Scoped gateway identity required")
    try:
        payload_segment = token.split(".")[1]
        padding = "=" * (-len(payload_segment) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload_segment + padding))
    except Exception as exc:
        raise HTTPException(status_code=403, detail="Invalid scoped gateway identity") from exc
    expected_claims = {
        "execution_identity": f"chat:{run_id}",
        "project_id": project_id,
        "branch": branch,
        "connection_name": connection_name,
    }
    if any(claims.get(key) != value for key, value in expected_claims.items()):
        raise HTTPException(status_code=403, detail="Scoped gateway identity mismatch")
    if "write" in list(claims.get("scopes") or []):
        raise HTTPException(status_code=403, detail="Scoped gateway identity permits writes")

    gateway_url = str(
        os.getenv("SP_GATEWAY_INTERNAL_URL")
        or os.getenv("SP_GATEWAY_URL")
        or "http://gateway:3300"
    ).rstrip("/")
    if not gateway_url.endswith("/mcp"):
        gateway_url = f"{gateway_url}/mcp"
    return {
        "mcpServers": {
            "signalpilot": {
                "type": "http",
                "url": gateway_url,
                "headers": {"Authorization": f"Bearer {token}"},
            }
        }
    }


def _scratch_directory(run_id: str) -> Path:
    root = Path(os.getenv("SP_CHAT_SCRATCH_ROOT", "/tmp/signalpilot-chat-runs")).resolve()
    scratch = (root / run_id).resolve()
    if root not in scratch.parents:
        raise HTTPException(status_code=400, detail="Invalid scratch path")
    scratch.mkdir(parents=True, exist_ok=True)
    return scratch


def _runtime_auth_override(body: dict[str, Any]) -> dict[str, str] | None:
    value = body.get("runtime_auth")
    if not isinstance(value, dict):
        return None
    auth_type = str(value.get("type") or "")
    token = str(value.get("token") or "").strip()
    if auth_type not in {"api_key", "oauth"} or not token or len(token) > 20_000:
        raise HTTPException(status_code=400, detail="Invalid runtime credential")
    return {"type": auth_type, "token": token}


@router.post("/execute")
async def execute(*, request: Request) -> StreamingResponse:
    body = await request.json()
    run_id, project_id, branch, connection_name = _require_execution_scope(body)
    mcp_config = _scoped_gateway_mcp_config(
        body,
        run_id=run_id,
        project_id=project_id,
        branch=branch,
        connection_name=connection_name,
    )
    prompt = str(body.get("prompt") or "").strip()
    if not prompt or len(prompt) > 50_000:
        raise HTTPException(status_code=400, detail="Prompt is empty or too large")
    history = [
        {"role": str(item.get("role") or "user"), "content": str(item.get("content") or "")}
        for item in list(body.get("messages") or [])[-40:]
        if isinstance(item, dict)
    ]
    warm_context = json.dumps(body.get("warm_context") or {}, default=str)[:120_000]
    system_prompt = (
        f"{STANDALONE_SYSTEM_PROMPT}\n\n"
        f"Selected project: {project_id}\nFrozen branch: {branch}\n"
        f"Selected connection: {connection_name}\n\n"
        f"<governed_project_context>\n{warm_context}\n</governed_project_context>"
    )
    collector = StandaloneArtifactCollector()
    artifact_server = build_standalone_chat_mcp_server(collector)
    auth_config_override = _runtime_auth_override(body)
    session_id = SessionId(f"standalone-{run_id}")
    scratch = _scratch_directory(run_id)

    async def stream() -> AsyncGenerator[bytes, None]:
        try:
            final_text = ""
            async for event in run_notebook_agent(
                prompt,
                session_id,
                model=str(
                    body.get("model")
                    or os.getenv("SIGNALPILOT_ANALYSIS_AGENT_MODEL")
                    or "claude-sonnet-4-5-20250929"
                ),
                max_turns=40,
                new_chat=bool(body.get("new_execution", False)),
                message_history=history,
                system_prompt_override=system_prompt,
                mcp_config=mcp_config,
                thread_id=f"standalone:{run_id}",
                cwd=str(scratch),
                disallow_file_edits=True,
                additional_disallowed_tools=["WebFetch", "WebSearch"],
                allowed_tools=STANDALONE_ALLOWED_TOOLS,
                additional_mcp_servers={"standalone-chat": artifact_server},
                persist_session_mapping=False,
                auth_config_override=auth_config_override,
            ):
                if event.type in {"thinking", "thinking_delta", "block_start"}:
                    continue
                if event.type == "text":
                    final_text = event.content
                payload = {
                    "type": event.type,
                    "content": event.content,
                    "tool_name": event.tool_name,
                    "tool_input": event.tool_input,
                    "tool_call_id": event.tool_call_id,
                    "is_error": event.is_error,
                }
                yield (json.dumps(payload, default=str) + "\n").encode("utf-8")
            yield (
                json.dumps(
                    {
                        "type": "final",
                        "content": final_text,
                        "artifacts": collector.artifacts,
                    },
                    default=str,
                )
                + "\n"
            ).encode("utf-8")
        finally:
            clear_chat_session(f"standalone:{run_id}", persist=False)
            shutil.rmtree(scratch, ignore_errors=True)

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@router.post("/cancel/{run_id}")
async def cancel(*, request: Request) -> JSONResponse:
    run_id = request.path_params["run_id"]
    if not _RUN_ID_RE.fullmatch(run_id):
        raise HTTPException(status_code=400, detail="Invalid run id")
    expected = os.getenv("SP_CHAT_RUN_ID")
    if expected and expected != run_id:
        raise HTTPException(status_code=403, detail="Execution scope mismatch")
    stopped = stop_agent(f"standalone-{run_id}")
    return JSONResponse({"stopped": stopped})
