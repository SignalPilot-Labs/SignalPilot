"""Internal streaming execution endpoint for durable standalone data chat."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import html as html_lib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, StreamingResponse

from signalpilot import _loggers
from signalpilot._server.ai.chat_runtime_output import (
    compact_chat_runtime_output,
)
from signalpilot._server.ai.claude_agent import (
    clear_chat_session,
    run_notebook_agent,
    stop_agent,
)
from signalpilot._server.ai.standalone_chat_tools import (
    StandaloneArtifactCollector,
    StandaloneNotebookLifecycle,
    _collected_artifact_is_complete,
    build_standalone_chat_mcp_server,
)
from signalpilot._server.files import project_sync
from signalpilot._server.router import APIRouter
from signalpilot._types.ids import SessionId
from signalpilot._utils.requests import RequestError

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from starlette.requests import Request

router = APIRouter()
LOGGER = _loggers.sp_logger()
_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9-]{8,80}$")
_ANALYSIS_SESSIONS_BY_RUN: dict[str, str] = {}

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
    "mcp__signalpilot__plan_query",
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
    "mcp__standalone-chat__list_saved_report_catalog",
    "mcp__standalone-chat__load_report_context",
    "mcp__standalone-chat__propose_report_action",
    "mcp__standalone-chat__inspect_dbt",
    "mcp__standalone-chat__start_analysis_notebook",
    "mcp__signalpilot-notebook__edit_notebook",
    "mcp__signalpilot-notebook__run_cells",
    "mcp__signalpilot-notebook__get_lightweight_cell_map",
    "mcp__signalpilot-notebook__get_notebook_errors",
]

# Additional gateway tools available only to automated improvement runs. The
# gateway enforces this server-side through the sandbox:execute JWT capability;
# this list only widens the agent-side allowlist for those runs.
IMPROVEMENT_EXTRA_TOOLS = [
    "mcp__signalpilot__sandbox_exec",
    "mcp__signalpilot__sandbox_write_file",
    "mcp__signalpilot__sandbox_read_file",
]

# Gateway MCP tools that must not be offered to the ordinary Data Chat agent.
# analyze_project_db and map_columns can return after they use the governed
# plan/result and frozen-project boundaries. get_dbt_profile is intentionally
# reserved for writable dbt/Xata administration.
STANDALONE_DISALLOWED_MCP_TOOLS = [
    "mcp__signalpilot__analyze_project_db",
    "mcp__signalpilot__get_dbt_profile",
    "mcp__signalpilot__map_columns",
]

IMPROVEMENT_SYSTEM_PROMPT_SUFFIX = """

<automated_improvement_run>
This is an AUTOMATED IMPROVEMENT RUN scheduled by SignalPilot, not a user
conversation. Your mission: analyze the selected dbt project for warehouse
cost-saving opportunities and publish an HTML report.

Additional rules for this run only:
- You have sandbox VM tools (sandbox_exec, sandbox_write_file,
  sandbox_read_file): a disposable Linux VM with python3, uv, pip, and git.
  Use it to install dbt and parse/compile the project sources you need.
  The project files are also available read-only in your working directory.
- Workflow: enumerate the project's models, use estimate_query_cost on the
  compiled SQL of the most material models against the selected connection,
  and identify concrete savings (duplicated subqueries worth extracting into
  a cached staging model, SELECT * from wide tables, expensive views that
  many models reference, dead models with no downstream refs).
- Rank recommendations by estimated savings and show before/after cost when
  you can estimate both.
- Publish exactly one HTML report artifact via publish_report titled
  "Cost optimization report". The report must include: an executive summary,
  a ranked recommendation table with estimated impact, and the per-model
  cost estimates you gathered. If you find no meaningful savings, publish
  the report saying so with the evidence.
- Never modify the database, the project, or any external system. Read-only
  queries and the sandbox only.
- End with a 3-6 sentence plain-language summary of the findings.
</automated_improvement_run>"""

STANDALONE_SYSTEM_PROMPT = """You are SignalPilot Data Chat, helping a non-technical business user answer questions from one governed project.

Rules:
- Respond in English only and lead with the business answer.
- Inspect the supplied dbt metadata, schema, and relevant data before asking a question.
- Query only the selected connection shown below. Queries must be read-only.
- Do not modify a database, project, notebook, file, external system, or repository.
- Call plan_query before every execution. Obey its route exactly.
- Use query_database with the returned plan_id only when the plan route is mcp.
- If the route is notebook_sdk or dataset_ref, call start_analysis_notebook with that plan_id, then use only the seeded notebook and the plan-bound SDK.
- The analysis notebook is a marimo reactive notebook, not a Jupyter notebook. Before editing it, inspect the current cell map. Every non-private top-level name may be defined by exactly one live cell across the entire notebook. Imports, assignments, function and class names, and top-level loop targets all define names.
- Define shared imports and reusable DataFrames once, then reference them from downstream cells. Prefix disposable cell-local names with one underscore (for example `_fig`, `_ax`, `_i`, `_row`, or `_segment`), or place scratch work inside a uniquely named function. Underscore-prefixed names are cell-local and must never be referenced from another cell; any cross-cell value needs one unique public name. Never repeat public helper names across cells.
- If edit_notebook returns MultipleDefinitionError, use its variable and cell_ids to update, rename, or delete the conflicting definitions in one atomic edit batch. Do not add a replacement definition in a separate transaction while the old defining cell remains live.
- Never edit, remove, or redefine the seeded hidden context/import cell or the seeded SDK setup cell. They already run `sp.init(...)` and define the plan-bound `db = sp.connect(...)` connection. `sp.init()` returns None, and there is no `signalpilot.db` export.
- For notebook_sdk, first define `plan_id` from the exact ID returned by plan_query, then execute the exact planned SQL with `source = db.query_result(sql, plan_id=plan_id)` and build the in-kernel DataFrame from `source["rows"]`; retain `source["result_id"]` for publication. A plan ID authorizes only its exact planned SQL and execution scope. If you change the SQL, call plan_query again and use its new plan ID. There is no `db.read_plan` method.
- If the route is aggregate_required, rewrite the work as a bounded warehouse aggregate. If it is refuse, stop.
- Never copy MCP previews into notebook DataFrames, including as a fallback during recovery. MCP previews are model context, not a data transport.
- Keep complete bounded DataFrames inside the kernel. Notebook cells may display only schema, completeness, statistics, checks, and a small preview.
- Publish derived rows from the kernel with exactly `derived = sp.publish_result(dataframe, name="...", source_result_ids=[source["result_id"]], completeness="complete" | "truncated" | "unknown", reconciliation="...")`. The SDK computes the notebook code hash; do not pass `result=`, `code_hash=`, or `metadata=`.
- Publish a runtime file with exactly `artifact = sp.publish_artifact(path, kind="table" | "chart" | "report", result_id=derived.id, assumptions=[...], exclusions=[...], caveats=[...])`. Create chart PNGs and other artifacts only under `SP_CHAT_SCRATCH_DIRECTORY`. Finalize every notebook cell before executing publication: the result and artifact must be published from the same unchanged notebook code hash. Do not edit the notebook between `sp.publish_result` and `sp.publish_artifact`; after any edit, publish both again from the final notebook version.
- PublishedResult exposes only `id`, `name`, `row_count`, `byte_size`, and `completeness`. PublishedArtifact exposes only `id`, `filename`, `kind`, and `byte_size`.
- Do not catch or suppress publication exceptions. A failed `sp.publish_result` or `sp.publish_artifact` means the analysis is incomplete and must not be reported as successful.
- Ask for clarification only when exploration leaves a material ambiguity that would change the answer. If needed, return exactly `CLARIFICATION_REQUESTED: <one conversational question>`.
- Choose text, a table, a chart, or a report automatically. Publish every displayed table, chart, or report with the publication tools.
- Never guess. State freshness, assumptions, exclusions, truncation, and caveats explicitly.
- Explicitly disclose incomplete, unknown-completeness, or display-limited results.
- Use SignalPilot MCP for schema discovery and bounded pre-analysis. MCP row samples are context-limited and must never be treated as a complete dataset.
- Prefer governed SDK structured-result IDs for substantial analysis and for every published artifact.
- REQUIRED POST-PUBLICATION STEP: after publishing any complete non-truncated table, chart, or report, do not give the final answer yet; scan every page from list_saved_report_catalog and then call propose_report_action exactly once. Catalog pages contain semantics, never result rows.
- Compare reports in this order: exact artifact content, normalized title, then semantic meaning across the complete catalog. Semantic equivalence requires the same business question, project/data domain, core metrics, entity or grain, and compatible dimensions and filters.
- Treat newer dates or warehouse data, formatting, visualization changes, additional breakdowns, and small wording changes as updates. Treat changed metric definitions, entity or grain, business purpose, governed project, or incompatible populations as distinct reports.
- Load the matched report with load_report_context before proposing an update, except when the user explicitly attached that report. Historical SQL is context only; plan every new execution normally.
- Call propose_report_action exactly once for an eligible completed artifact. Use open for exact content, update for a semantic match, create only when the full catalog has no match, or no_suggestion with a concrete reason when the artifact should not be promoted. Report creation or update always waits for the user's UI approval.
- The dbt project is frozen at the supplied commit. Inspect it but never run dbt run, build, seed, or snapshot.
- Never mention or expose confidence scores, hidden reasoning, chain-of-thought, credentials, or implementation internals.
- Do not suggest follow-up questions.
"""


_NOTEBOOK_ONLY_RULE_PREFIXES = (
    "- If the route is notebook_sdk or dataset_ref",
    "- The analysis notebook is a marimo reactive notebook",
    "- Define shared imports and reusable DataFrames once",
    "- If edit_notebook returns MultipleDefinitionError",
    "- Never edit, remove, or redefine the seeded",
    "- For notebook_sdk, first define `plan_id`",
    "- Never copy MCP previews into notebook DataFrames",
    "- Keep complete bounded DataFrames inside the kernel",
    "- Publish derived rows from the kernel",
    "- Publish a runtime file with exactly",
    "- PublishedResult exposes only",
    "- Do not catch or suppress publication exceptions",
    "- Prefer governed SDK structured-result IDs",
)


def _system_prompt_for_features(*, notebook_analysis_enabled: bool) -> str:
    if notebook_analysis_enabled:
        return STANDALONE_SYSTEM_PROMPT
    lines = [
        line
        for line in STANDALONE_SYSTEM_PROMPT.splitlines()
        if not line.startswith(_NOTEBOOK_ONLY_RULE_PREFIXES)
    ]
    disabled_rule = (
        "- Notebook analysis is disabled for this run. Do not call notebook "
        "tools; use an exact MCP plan or rewrite aggregate_required work as "
        "bounded warehouse SQL."
    )
    insert_at = (
        lines.index(
            "- Use query_database with the returned plan_id only when the plan route is mcp."
        )
        + 1
    )
    lines.insert(insert_at, disabled_rule)
    return "\n".join(lines)


def _allowed_tools_for_features(
    *,
    notebook_analysis_enabled: bool,
) -> list[str]:
    if notebook_analysis_enabled:
        return list(STANDALONE_ALLOWED_TOOLS)
    return [
        tool
        for tool in STANDALONE_ALLOWED_TOOLS
        if "signalpilot-notebook" not in tool
        and not tool.endswith("start_analysis_notebook")
    ]


def _require_execution_scope(
    body: dict[str, Any],
) -> tuple[str, str, str, str, str]:
    run_id = str(body.get("run_id") or "")
    project_id = str(body.get("project_id") or "")
    branch = str(body.get("branch") or "")
    connection_name = str(body.get("connection_name") or "")
    commit_sha = str(body.get("commit_sha") or "")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit_sha):
        raise HTTPException(status_code=400, detail="Invalid commit SHA")
    if not _RUN_ID_RE.fullmatch(run_id):
        raise HTTPException(status_code=400, detail="Invalid run id")
    expected = {
        "run": os.getenv("SP_CHAT_RUN_ID"),
        "project": os.getenv("SP_CHAT_PROJECT_ID"),
        "branch": os.getenv("SP_CHAT_BRANCH"),
        "connection": os.getenv("SP_CHAT_CONNECTION_NAME"),
        "commit": os.getenv("SP_CHAT_COMMIT_SHA"),
    }
    supplied = {
        "run": run_id,
        "project": project_id,
        "branch": branch,
        "connection": connection_name,
        "commit": commit_sha,
    }
    for key, value in expected.items():
        if value and supplied[key] != value:
            raise HTTPException(
                status_code=403, detail="Execution scope mismatch"
            )
    return run_id, project_id, branch, connection_name, commit_sha


def _scoped_gateway_mcp_config(
    body: dict[str, Any],
    *,
    run_id: str,
    project_id: str,
    branch: str,
    connection_name: str,
    commit_sha: str,
) -> dict[str, Any]:
    token = str(body.get("gateway_session_token") or "").strip()
    if not token:
        raise HTTPException(
            status_code=403, detail="Scoped gateway identity required"
        )
    try:
        payload_segment = token.split(".")[1]
        padding = "=" * (-len(payload_segment) % 4)
        claims = json.loads(
            base64.urlsafe_b64decode(payload_segment + padding)
        )
    except Exception as exc:
        raise HTTPException(
            status_code=403, detail="Invalid scoped gateway identity"
        ) from exc
    expected_claims = {
        "execution_identity": f"chat:{run_id}",
        "project_id": project_id,
        "branch": branch,
        "connection_name": connection_name,
        "commit_sha": commit_sha,
    }
    if any(claims.get(key) != value for key, value in expected_claims.items()):
        raise HTTPException(
            status_code=403, detail="Scoped gateway identity mismatch"
        )
    if "write" in list(claims.get("scopes") or []):
        raise HTTPException(
            status_code=403, detail="Scoped gateway identity permits writes"
        )

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
    root = Path(
        os.getenv(
            "SP_CHAT_SCRATCH_ROOT",
            "/tmp/signalpilot-chat-runs",  # nosec B108 - container-local scratch
        )
    ).resolve()
    scratch = (root / run_id).resolve()
    if root not in scratch.parents:
        raise HTTPException(status_code=400, detail="Invalid scratch path")
    scratch.mkdir(parents=True, exist_ok=True)
    return scratch


def _seed_analysis_notebook(
    *,
    scratch: Path,
    run_id: str,
    project_id: str,
    connection_name: str,
    gateway_url: str,
    scoped_token: str,
) -> Path:
    token_file = scratch / ".gateway-token"
    token_file.write_text(scoped_token, encoding="utf-8")
    token_file.chmod(0o600)
    notebook_path = scratch / "analysis.py"
    context = json.dumps(
        {
            "run_id": run_id,
            "project_id": project_id,
            "connection_name": connection_name,
        }
    )
    notebook_path.write_text(
        f"""import signalpilot as sp

__generated_with = "0.1.0"
app = sp.App()


@app.cell(hide_code=True)
def _():
    import os
    from pathlib import Path
    import signalpilot as sp
    runtime_context = {context}
    os.environ["SP_CHAT_SCRATCH_DIRECTORY"] = {str(scratch)!r}
    os.environ["SP_CHAT_NOTEBOOK_PATH"] = {str(notebook_path)!r}
    return Path, runtime_context, sp


@app.cell
def _(Path, sp):
    sp.init(gateway_url={gateway_url!r}, session_token=Path({str(token_file)!r}).read_text(encoding="utf-8"))
    db = sp.connect({connection_name!r})
    return (db,)


@app.cell
def _(db):
    analysis_summary = {{"status": "pending", "preview": []}}
    return (analysis_summary,)


@app.cell
def _(analysis_summary):
    analysis_checks = {{"nulls": None, "duplicates": None, "freshness": None, "reconciled": False}}
    return (analysis_checks,)


@app.cell
def _(analysis_checks, analysis_summary, sp):
    sp.md("## Analysis output\\n\\nPending governed notebook analysis.")


if __name__ == "__main__":
    app.run()
""",
        encoding="utf-8",
    )
    return notebook_path


def _analysis_session(app: Any, session_id: str) -> Any:
    from signalpilot._server.ai.tools.base import ToolContext

    return ToolContext(app=app).get_session(session_id)


def _is_error_output(output: Any) -> bool:
    channel = getattr(output, "channel", None)
    return getattr(channel, "value", channel) == "sp-error"


def _safe_notebook_error(error: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": str(error.get("type") or "NotebookValidationError")[:100],
        "variable": str(error.get("variable") or "")[:100] or None,
        "cell_ids": [
            str(value)[:100] for value in error.get("cell_ids") or []
        ][:20],
    }


def _with_recorded_notebook_errors(
    session: Any, failure: dict[str, Any]
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    seen: set[str] = set()
    recorded = getattr(session, "_signalpilot_notebook_failures", ())
    candidates = [
        *(item.get("error") or {} for item in recorded),
        failure.get("error") or {},
    ]
    for candidate in candidates:
        safe = _safe_notebook_error(candidate)
        key = json.dumps(safe, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        errors.append(safe)
    return {**failure, "errors": errors[-20:]}


def _notebook_failure(app: Any, session_id: str) -> dict[str, Any] | None:
    session = _analysis_session(app, session_id)
    if getattr(session, "_signalpilot_notebook_dirty", False):
        failure = dict(
            getattr(session, "_signalpilot_last_notebook_failure", None)
            or {
                "error": {
                    "type": "DocumentKernelSynchronizationError",
                    "variable": None,
                    "cell_ids": [],
                }
            }
        )
        return _with_recorded_notebook_errors(session, failure)

    for cell in session.app_file_manager.app.cell_manager.cell_data():
        cell_id = cell.cell_id
        notification = session.session_view.cell_notifications.get(cell_id)
        if notification is None:
            return _with_recorded_notebook_errors(
                session,
                {
                    "error": {
                        "type": "UnknownStateError",
                        "variable": None,
                        "cell_ids": [str(cell_id)],
                    }
                },
            )
        status = str(getattr(notification, "status", "") or "")
        if status != "idle":
            return _with_recorded_notebook_errors(
                session,
                {
                    "error": {
                        "type": "UnknownStateError",
                        "variable": None,
                        "cell_ids": [str(cell_id)],
                    }
                },
            )
        output = getattr(notification, "output", None)
        if _is_error_output(output):
            raw_errors = getattr(output, "data", None)
            error = (
                raw_errors[0]
                if isinstance(raw_errors, list) and raw_errors
                else None
            )
            involved = {str(cell_id)}
            involved.update(
                str(value) for value in getattr(error, "cells", ())
            )
            edge_variables: set[str] = set()
            for source, variables, target in getattr(
                error, "edges_with_vars", ()
            ):
                involved.update((str(source), str(target)))
                edge_variables.update(str(value) for value in variables)
            variable = getattr(error, "name", None)
            if variable is None and edge_variables:
                variable = sorted(edge_variables)[0]
            return _with_recorded_notebook_errors(
                session,
                {
                    "error": {
                        "type": type(error).__name__
                        if error
                        else "CellExecutionError",
                        "variable": variable,
                        "cell_ids": sorted(involved),
                    }
                },
            )
    return None


def _notebook_has_errors(app: Any, session_id: str) -> bool:
    return _notebook_failure(app, session_id) is not None


def _recovery_context(failure: dict[str, Any]) -> str:
    raw_errors = failure.get("errors") or [failure.get("error") or {}]
    safe_errors = [_safe_notebook_error(error) for error in raw_errors][:20]
    return (
        "The first notebook attempt was rejected and its notebook and artifacts "
        "were discarded. Start the newly seeded notebook, execute the evidence "
        "again, validate every requested cell, and answer only from this clean "
        "attempt. Treat every listed graph error as an explicit instruction not "
        "to recreate those duplicate globals; use unique public names, private "
        "underscore-prefixed scratch names, or uniquely named functions. Private "
        "underscore-prefixed names are cell-local and cannot be read from another "
        "cell. A governed plan ID can be reused only with its exact original SQL; "
        "changed SQL requires a new plan_query result. Never replace SDK query "
        "evidence with copied MCP preview rows. "
        f"Recovery errors: {json.dumps(safe_errors, sort_keys=True)}"
    )


def _log_notebook_failure(
    *,
    run_id: str,
    session_id: str,
    attempt: int,
    failure: dict[str, Any],
) -> None:
    error = failure.get("error") or {}
    LOGGER.error(
        "Standalone notebook validation failed run_id=%s session_id=%s "
        "attempt=%s error_type=%s variable=%s cell_ids=%s",
        run_id,
        session_id,
        attempt,
        error.get("type"),
        error.get("variable"),
        error.get("cell_ids"),
    )


async def _archive_analysis_notebook(
    *,
    app: Any,
    session_id: str,
    run_id: str,
    gateway_api_url: str,
    scoped_token: str,
) -> str:
    from signalpilot._server.export.exporter import Exporter
    from signalpilot._server.models.export import ExportAsHTMLRequest

    session = _analysis_session(app, session_id)
    source = session.app_file_manager.app.to_py().encode("utf-8")
    if scoped_token.encode("utf-8") in source:
        raise RuntimeError(
            "Refusing to archive notebook source containing a runtime token"
        )
    try:
        html, _ = Exporter().export_as_html(
            app=session.app_file_manager.app,
            filename="analysis.py",
            session_view=session.session_view,
            display_config=session.config_manager.get_config()["display"],
            request=ExportAsHTMLRequest(
                download=False,
                files=[],
                include_code=False,
            ),
        )
    except (FileNotFoundError, RequestError, httpx.HTTPError) as exc:
        # The slim runtime image intentionally omits the notebook frontend
        # bundle. Preserve the validated evidence in a bounded, code-free HTML
        # archive instead of rejecting an otherwise clean analysis.
        LOGGER.warning(
            "Notebook frontend assets unavailable; using safe archive fallback "
            "run_id=%s session_id=%s error_type=%s",
            run_id,
            session_id,
            type(exc).__name__,
        )
        html = _fallback_archive_html(
            session,
            run_id=run_id,
            redactions=(scoped_token,),
        )
    cells = []
    for cell in session.app_file_manager.app.cell_manager.cell_data():
        notification = session.session_view.cell_notifications.get(
            cell.cell_id
        )
        cells.append(
            {
                "cell_id": str(cell.cell_id),
                "code_hash": hashlib.sha256(
                    cell.code.encode("utf-8")
                ).hexdigest(),
                "status": str(
                    getattr(notification, "status", "unknown") or "unknown"
                ),
                "has_errors": bool(
                    notification is not None
                    and _is_error_output(getattr(notification, "output", None))
                ),
            }
        )
    manifest = json.dumps(
        {"version": 1, "run_id": run_id, "cells": cells},
        separators=(",", ":"),
    ).encode("utf-8")
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{gateway_api_url}/api/chat/runtime-archives",
            headers={"Authorization": f"Bearer {scoped_token}"},
            json={
                "source_base64": base64.b64encode(source).decode("ascii"),
                "html_base64": base64.b64encode(html.encode("utf-8")).decode(
                    "ascii"
                ),
                "manifest_base64": base64.b64encode(manifest).decode("ascii"),
            },
        )
    response.raise_for_status()
    return str(response.json()["archive_id"])


def _fallback_archive_html(
    session: Any,
    *,
    run_id: str,
    redactions: tuple[str, ...],
) -> str:
    """Render validated cell outputs without notebook code or active markup."""
    sections: list[str] = []
    for index, cell in enumerate(
        session.app_file_manager.app.cell_manager.cell_data(), start=1
    ):
        notification = session.session_view.cell_notifications.get(
            cell.cell_id
        )
        status = str(getattr(notification, "status", "unknown") or "unknown")
        output = getattr(notification, "output", None)
        mimetype = str(getattr(output, "mimetype", "") or "")
        rendered_output = "No displayed output."
        if output is not None:
            rendered_output = compact_chat_runtime_output(
                getattr(output, "data", ""),
                mimetype=mimetype,
                redactions=redactions,
            )
        sections.append(
            "<section>"
            f"<h2>Cell {index}</h2>"
            f"<p>Status: {html_lib.escape(status)}</p>"
            f"<p>Output type: {html_lib.escape(mimetype or 'none')}</p>"
            f"<pre>{html_lib.escape(rendered_output)}</pre>"
            "</section>"
        )
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Validated analysis notebook</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:960px;margin:40px auto;"
        "padding:0 20px;background:#141416;color:#ededed}section{border:1px solid #333;"
        "border-radius:8px;padding:16px;margin:16px 0}pre{white-space:pre-wrap;"
        "overflow-wrap:anywhere;background:#1d1d20;padding:12px;border-radius:6px}</style>"
        "</head><body><h1>Validated analysis notebook</h1>"
        f"<p>Run {html_lib.escape(run_id)}</p>{''.join(sections)}</body></html>"
    )


def _close_analysis_kernel(app: Any, session_id: str) -> bool:
    from signalpilot._server.ai.tools.base import ToolContext
    from signalpilot._types.ids import SessionId

    return ToolContext(app=app).session_manager.close_session(
        SessionId(session_id)
    )


def _start_analysis_kernel(app: Any, notebook_path: Path) -> str:
    from signalpilot._server.ai.notebook_mcp import (
        _handle_start_notebook_session,
    )
    from signalpilot._server.ai.tools.base import ToolContext

    result = _handle_start_notebook_session(
        ToolContext(app=app),
        {"file_path": str(notebook_path), "auto_run": True},
    )
    if not result:
        raise RuntimeError("Clean notebook kernel did not start")
    try:
        started = json.loads(str(getattr(result[0], "text", "")))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Clean notebook kernel returned an invalid response"
        ) from exc
    session_id = str(started.get("session_id") or "")
    if not session_id or str(started.get("status") or "").startswith("error"):
        raise RuntimeError("Clean notebook kernel did not start")
    return session_id


def _frozen_project_directory(project_id: str) -> Path | None:
    parent = project_sync.PROJECTS_ROOT / project_id
    if not parent.exists():
        return None
    roots = sorted(
        (path.parent for path in parent.rglob(".git") if path.is_dir()),
        key=lambda path: len(path.parts),
    )
    return roots[0] if roots else None


async def _execution_project_directory(
    *,
    run_id: str,
    project_id: str,
    branch: str,
    commit_sha: str,
    gateway_token: str,
) -> tuple[Path, bool]:
    project_directory = _frozen_project_directory(project_id)
    if project_directory is not None and _project_is_unchanged(
        project_directory, commit_sha
    ):
        return project_directory, False
    if os.getenv("SP_CHAT_RUN_ID"):
        raise HTTPException(
            status_code=409,
            detail="Frozen project workspace is not reproducible",
        )
    try:
        project_directory = await asyncio.to_thread(
            project_sync.materialize_frozen_checkout,
            project_id=project_id,
            branch=branch,
            commit_sha=commit_sha,
            checkout_id=run_id,
            gateway_token=gateway_token,
        )
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        httpx.HTTPError,
    ) as exc:
        raise HTTPException(
            status_code=409,
            detail="Frozen project workspace could not be prepared",
        ) from exc
    if not _project_is_unchanged(project_directory, commit_sha):
        shutil.rmtree(project_directory, ignore_errors=True)
        raise HTTPException(
            status_code=409,
            detail="Frozen project workspace is not reproducible",
        )
    return project_directory, True


def _project_is_unchanged(project_directory: Path, commit_sha: str) -> bool:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_directory,
            capture_output=True,
            text=True,
            timeout=10,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=project_directory,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return (
        head.returncode == 0
        and head.stdout.strip().lower() == commit_sha.lower()
        and status.returncode == 0
        and not status.stdout.strip()
    )


def _runtime_auth_override(body: dict[str, Any]) -> dict[str, str] | None:
    value = body.get("runtime_auth")
    if not isinstance(value, dict):
        return None
    auth_type = str(value.get("type") or "")
    token = str(value.get("token") or "").strip()
    if (
        auth_type not in {"api_key", "oauth"}
        or not token
        or len(token) > 20_000
    ):
        raise HTTPException(
            status_code=400, detail="Invalid runtime credential"
        )
    return {"type": auth_type, "token": token}


@router.post("/execute")
async def execute(*, request: Request) -> StreamingResponse:
    body = await request.json()
    run_id, project_id, branch, connection_name, commit_sha = (
        _require_execution_scope(body)
    )
    mcp_config = _scoped_gateway_mcp_config(
        body,
        run_id=run_id,
        project_id=project_id,
        branch=branch,
        connection_name=connection_name,
        commit_sha=commit_sha,
    )
    prompt = str(body.get("prompt") or "").strip()
    if not prompt or len(prompt) > 50_000:
        raise HTTPException(
            status_code=400, detail="Prompt is empty or too large"
        )
    history = [
        {
            "role": str(item.get("role") or "user"),
            "content": str(item.get("content") or ""),
        }
        for item in list(body.get("messages") or [])[-40:]
        if isinstance(item, dict)
    ]
    warm_context = json.dumps(body.get("warm_context") or {}, default=str)[
        :120_000
    ]
    feature_values = (
        body.get("features") if isinstance(body.get("features"), dict) else {}
    )
    notebook_analysis_enabled = bool(feature_values.get("notebook_analysis"))
    is_improvement_run = str(body.get("run_origin") or "user") == "improvement"
    system_prompt = (
        f"{_system_prompt_for_features(notebook_analysis_enabled=notebook_analysis_enabled)}"
        f"{IMPROVEMENT_SYSTEM_PROMPT_SUFFIX if is_improvement_run else ''}\n\n"
        f"Selected project: {project_id}\nFrozen branch: {branch}\nFrozen commit: {commit_sha}\n"
        f"Selected connection: {connection_name}\n\n"
        f"<governed_project_context>\n{warm_context}\n</governed_project_context>"
    )
    scoped_token = str(body.get("gateway_session_token") or "")
    gateway_api_url = str(
        os.getenv("SP_GATEWAY_INTERNAL_URL")
        or os.getenv("SP_GATEWAY_URL")
        or "http://gateway:3300"
    ).rstrip("/")
    if gateway_api_url.endswith("/mcp"):
        gateway_api_url = gateway_api_url.removesuffix("/mcp")

    scratch = _scratch_directory(run_id)
    analysis_notebook_path = _seed_analysis_notebook(
        scratch=scratch,
        run_id=run_id,
        project_id=project_id,
        connection_name=connection_name,
        gateway_url=gateway_api_url,
        scoped_token=scoped_token,
    )
    seeded_notebook_source = analysis_notebook_path.read_text(encoding="utf-8")

    async def load_result(result_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{gateway_api_url}/api/query/results/{result_id}",
                headers={"Authorization": f"Bearer {scoped_token}"},
            )
        if response.status_code == 404:
            raise ValueError("Governed structured result not found")
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("Invalid governed structured result")
        return value

    async def check_plan(plan_id: str) -> dict[str, Any]:
        if not notebook_analysis_enabled:
            raise ValueError("Notebook analysis is not enabled for this run")
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{gateway_api_url}/api/query/plans/{plan_id}",
                headers={"Authorization": f"Bearer {scoped_token}"},
            )
        if response.status_code == 404:
            raise ValueError("Governed query plan not found")
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("Invalid governed query plan")
        return value

    async def load_report_catalog(cursor: str | None) -> dict[str, Any]:
        params = {"limit": "50"}
        if cursor:
            params["cursor"] = cursor
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{gateway_api_url}/api/chat/runs/{run_id}/report-catalog",
                params=params,
                headers={"Authorization": f"Bearer {scoped_token}"},
            )
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("Invalid saved report catalog")
        return value

    async def load_report_context(report_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{gateway_api_url}/api/chat/runs/{run_id}/report-context/{report_id}",
                headers={"Authorization": f"Bearer {scoped_token}"},
            )
        if response.status_code == 404:
            raise ValueError("Saved report not found")
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("Invalid saved report context")
        return value

    async def check_published_artifact(
        artifact_kind: str,
        artifact_filename: str,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{gateway_api_url}/api/chat/runs/{run_id}/published-report-artifact",
                params={
                    "artifact_kind": artifact_kind,
                    "artifact_filename": artifact_filename,
                },
                headers={"Authorization": f"Bearer {scoped_token}"},
            )
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("Invalid published artifact state")
        return value

    auth_config_override = _runtime_auth_override(body)
    session_id = SessionId(f"standalone-{run_id}")
    remove_project_directory = False
    try:
        (
            project_directory,
            remove_project_directory,
        ) = await _execution_project_directory(
            run_id=run_id,
            project_id=project_id,
            branch=branch,
            commit_sha=commit_sha,
            gateway_token=scoped_token,
        )
    except Exception:
        shutil.rmtree(scratch, ignore_errors=True)
        raise

    async def stream() -> AsyncGenerator[bytes, None]:
        current_lifecycle: StandaloneNotebookLifecycle | None = None
        try:
            recovery_failure: dict[str, Any] | None = None
            previous_notebook_session_id: str | None = None
            recovery_plan_id: str | None = None
            for attempt in (1, 2):
                collector = StandaloneArtifactCollector()
                lifecycle = StandaloneNotebookLifecycle()
                current_lifecycle = lifecycle

                async def lifecycle_event(
                    event_type: str,
                    payload: dict[str, Any],
                    lifecycle: StandaloneNotebookLifecycle = lifecycle,
                    attempt: int = attempt,
                ) -> None:
                    del payload
                    if (
                        event_type != "notebook_started"
                        or not lifecycle.session_id
                    ):
                        return
                    _ANALYSIS_SESSIONS_BY_RUN[run_id] = lifecycle.session_id
                    runtime_session = _analysis_session(
                        request.app, lifecycle.session_id
                    )
                    runtime_session._signalpilot_chat_run_id = run_id
                    runtime_session._signalpilot_chat_session_id = (
                        lifecycle.session_id
                    )
                    runtime_session._signalpilot_chat_attempt = attempt

                if recovery_failure is not None:
                    if not recovery_plan_id:
                        yield (
                            json.dumps(
                                {
                                    "type": "error",
                                    "content": "The failed notebook did not retain a governed recovery plan.",
                                    "is_error": True,
                                }
                            )
                            + "\n"
                        ).encode("utf-8")
                        return
                    try:
                        lifecycle.session_id = _start_analysis_kernel(
                            request.app, analysis_notebook_path
                        )
                    except Exception:
                        LOGGER.exception(
                            "Clean notebook kernel start failed run_id=%s attempt=%s",
                            run_id,
                            attempt,
                        )
                        yield (
                            json.dumps(
                                {
                                    "type": "error",
                                    "content": "The failed notebook kernel could not be restarted safely.",
                                    "is_error": True,
                                }
                            )
                            + "\n"
                        ).encode("utf-8")
                        return
                    lifecycle.plan_id = recovery_plan_id
                    clean_session = _analysis_session(
                        request.app, lifecycle.session_id
                    )
                    clean_session._signalpilot_chat_runtime = True
                    clean_session._signalpilot_chat_redactions = (
                        scoped_token,
                    )
                    await lifecycle_event(
                        "notebook_started", {"plan_id": recovery_plan_id}
                    )

                artifact_server = build_standalone_chat_mcp_server(
                    collector,
                    result_loader=load_result,
                    project_directory=project_directory,
                    scratch_directory=scratch,
                    notebook_mcp_app=(
                        request.app if notebook_analysis_enabled else None
                    ),
                    analysis_notebook_path=analysis_notebook_path,
                    plan_checker=check_plan,
                    event_sink=lifecycle_event,
                    notebook_lifecycle=lifecycle,
                    runtime_redactions=(scoped_token,),
                    report_catalog_loader=load_report_catalog,
                    report_context_loader=load_report_context,
                    published_artifact_checker=check_published_artifact,
                    attached_report_id=str(
                        (
                            (body.get("warm_context") or {}).get(
                                "report_reference"
                            )
                            or {}
                        ).get("report_id")
                        or ""
                    )
                    or None,
                )
                attempt_prompt = prompt
                if recovery_failure is not None:
                    attempt_prompt = (
                        f"{prompt}\n\n<notebook_recovery>\n"
                        f"{_recovery_context(recovery_failure)}\n"
                        "The clean notebook kernel is already running. Use "
                        f"session_id `{lifecycle.session_id}` and governed plan_id "
                        f"`{recovery_plan_id}`; do not create a different session.\n"
                        "</notebook_recovery>"
                    )

                final_text = ""
                streamed_text = ""
                tool_names_by_id: dict[str, str] = {}
                successful_run_cells = False
                agent_failed = False
                async for event in run_notebook_agent(
                    attempt_prompt,
                    session_id,
                    model=str(
                        body.get("model")
                        or os.getenv("SIGNALPILOT_ANALYSIS_AGENT_MODEL")
                        or "claude-sonnet-4-5-20250929"
                    ),
                    max_turns=40,
                    new_chat=bool(body.get("new_execution", False))
                    or attempt > 1,
                    message_history=history,
                    system_prompt_override=system_prompt,
                    mcp_config=mcp_config,
                    thread_id=f"standalone:{run_id}",
                    notebook_mcp_app=(
                        request.app if notebook_analysis_enabled else None
                    ),
                    cwd=str(project_directory),
                    disallow_file_edits=True,
                    additional_disallowed_tools=[
                        "WebFetch",
                        "WebSearch",
                        *STANDALONE_DISALLOWED_MCP_TOOLS,
                        *(
                            []
                            if is_improvement_run
                            else IMPROVEMENT_EXTRA_TOOLS
                        ),
                    ],
                    allowed_tools=(
                        _allowed_tools_for_features(
                            notebook_analysis_enabled=notebook_analysis_enabled
                        )
                        + (
                            IMPROVEMENT_EXTRA_TOOLS
                            if is_improvement_run
                            else []
                        )
                    ),
                    additional_mcp_servers={
                        "standalone-chat": artifact_server
                    },
                    persist_session_mapping=False,
                    auth_config_override=auth_config_override,
                    notebook_session_authorizer=(
                        lambda candidate, lifecycle=lifecycle: (
                            lifecycle.session_id == candidate
                        )
                    ),
                ):
                    if event.type in {
                        "thinking",
                        "thinking_delta",
                        "block_start",
                    }:
                        continue
                    if event.type == "text_delta":
                        streamed_text += event.content
                        continue
                    if event.type == "text":
                        final_text = event.content
                        continue
                    if event.type == "error":
                        agent_failed = True
                        yield (
                            json.dumps(
                                {
                                    "type": "error",
                                    "content": "The analysis agent failed before validation.",
                                    "is_error": True,
                                }
                            )
                            + "\n"
                        ).encode("utf-8")
                        break
                    if event.type == "tool_use" and event.tool_call_id:
                        tool_names_by_id[event.tool_call_id] = event.tool_name
                    if event.type == "tool_result":
                        completed_tool = tool_names_by_id.get(
                            event.tool_call_id, ""
                        )
                        if (
                            completed_tool.endswith("run_cells")
                            and not event.is_error
                        ):
                            successful_run_cells = True
                    payload = {
                        "type": event.type,
                        "content": event.content,
                        "tool_name": event.tool_name,
                        "tool_input": event.tool_input,
                        "tool_call_id": event.tool_call_id,
                        "is_error": event.is_error,
                    }
                    yield (json.dumps(payload, default=str) + "\n").encode(
                        "utf-8"
                    )
                if agent_failed:
                    return

                if project_directory is not None and not _project_is_unchanged(
                    project_directory, commit_sha
                ):
                    yield (
                        json.dumps(
                            {
                                "type": "error",
                                "content": "The frozen project workspace changed; the run was rejected.",
                                "is_error": True,
                            }
                        )
                        + "\n"
                    ).encode("utf-8")
                    return

                notebook_failure: dict[str, Any] | None = None
                if lifecycle.session_id:
                    notebook_failure = _notebook_failure(
                        request.app, lifecycle.session_id
                    )
                    if (
                        recovery_failure is not None
                        and lifecycle.session_id
                        == previous_notebook_session_id
                    ):
                        notebook_failure = {
                            "error": {
                                "type": "NotebookSessionReuseError",
                                "variable": None,
                                "cell_ids": [],
                            }
                        }
                    elif not successful_run_cells:
                        notebook_failure = {
                            "error": {
                                "type": "NotebookEvidenceNotValidatedError",
                                "variable": None,
                                "cell_ids": [],
                            }
                        }
                    if notebook_failure is not None:
                        notebook_failure = _with_recorded_notebook_errors(
                            _analysis_session(
                                request.app, lifecycle.session_id
                            ),
                            notebook_failure,
                        )
                elif recovery_failure is not None:
                    notebook_failure = {
                        "error": {
                            "type": "NotebookNotRestartedError",
                            "variable": None,
                            "cell_ids": [],
                        }
                    }

                if notebook_failure is not None:
                    active_session_id = str(lifecycle.session_id or "")
                    _log_notebook_failure(
                        run_id=run_id,
                        session_id=active_session_id,
                        attempt=attempt,
                        failure=notebook_failure,
                    )
                    if attempt == 1 and lifecycle.session_id:
                        previous_notebook_session_id = lifecycle.session_id
                        recovery_plan_id = lifecycle.plan_id
                        kernel_closed = _close_analysis_kernel(
                            request.app, lifecycle.session_id
                        )
                        _ANALYSIS_SESSIONS_BY_RUN.pop(run_id, None)
                        lifecycle.session_id = None
                        if not kernel_closed:
                            yield (
                                json.dumps(
                                    {
                                        "type": "error",
                                        "content": "The failed notebook kernel could not be reset safely.",
                                        "is_error": True,
                                    }
                                )
                                + "\n"
                            ).encode("utf-8")
                            return
                        clear_chat_session(
                            f"standalone:{run_id}", persist=False
                        )
                        analysis_notebook_path.write_text(
                            seeded_notebook_source, encoding="utf-8"
                        )
                        recovery_failure = notebook_failure
                        yield (
                            json.dumps(
                                {
                                    "type": "progress",
                                    "content": "Restarting analysis in a clean notebook",
                                    "is_error": False,
                                }
                            )
                            + "\n"
                        ).encode("utf-8")
                        continue
                    yield (
                        json.dumps(
                            {
                                "type": "error",
                                "content": "Notebook validation failed after one clean retry; the answer was rejected.",
                                "is_error": True,
                            }
                        )
                        + "\n"
                    ).encode("utf-8")
                    return

                archive_id = None
                kernel_stopped = False
                if lifecycle.session_id:
                    try:
                        archive_id = await _archive_analysis_notebook(
                            app=request.app,
                            session_id=lifecycle.session_id,
                            run_id=run_id,
                            gateway_api_url=gateway_api_url,
                            scoped_token=scoped_token,
                        )
                    except Exception as exc:
                        LOGGER.error(
                            "Standalone notebook archive failed run_id=%s "
                            "session_id=%s attempt=%s error_type=%s",
                            run_id,
                            lifecycle.session_id,
                            attempt,
                            type(exc).__name__,
                        )
                        yield (
                            json.dumps(
                                {
                                    "type": "error",
                                    "content": "The validated notebook could not be archived; the answer was rejected.",
                                    "is_error": True,
                                }
                            )
                            + "\n"
                        ).encode("utf-8")
                        return
                    kernel_stopped = _close_analysis_kernel(
                        request.app, lifecycle.session_id
                    )
                    _ANALYSIS_SESSIONS_BY_RUN.pop(run_id, None)
                    lifecycle.session_id = None
                accepted_text = (final_text or streamed_text).strip()
                complete_artifacts = [
                    artifact
                    for artifact in collector.artifacts
                    if _collected_artifact_is_complete(artifact)
                ]
                if (
                    complete_artifacts
                    and collector.report_action_outcome is None
                ):
                    artifact = complete_artifacts[-1]
                    LOGGER.warning(
                        "Completed standalone artifact had no report action outcome "
                        "run_id=%s kind=%s filename=%s",
                        run_id,
                        artifact.get("kind"),
                        artifact.get("filename"),
                    )
                    collector.report_action_outcome = {
                        "action": "no_suggestion",
                        "artifact_kind": artifact.get("kind"),
                        "artifact_filename": artifact.get("filename"),
                        "title": artifact.get("filename"),
                        "reason": (
                            "The analysis agent completed without recording the required "
                            "catalog-backed report decision."
                        ),
                        "source": "completion_check",
                        "catalog_revision": collector.report_catalog_revision,
                        "catalog_scan_complete": (
                            collector.report_catalog_scan_complete
                        ),
                    }
                final_payload = {
                    "type": "final",
                    "content": accepted_text,
                    "artifacts": collector.artifacts,
                }
                if collector.report_proposal is not None:
                    final_payload["report_proposal"] = (
                        collector.report_proposal
                    )
                if collector.report_action_outcome is not None:
                    final_payload["report_action_outcome"] = (
                        collector.report_action_outcome
                    )
                if archive_id is not None:
                    final_payload["archive_id"] = archive_id
                    final_payload["kernel_stopped"] = kernel_stopped
                yield (json.dumps(final_payload, default=str) + "\n").encode(
                    "utf-8"
                )
                return
        finally:
            if current_lifecycle and current_lifecycle.session_id:
                try:
                    _close_analysis_kernel(
                        request.app, current_lifecycle.session_id
                    )
                except Exception:
                    pass
            _ANALYSIS_SESSIONS_BY_RUN.pop(run_id, None)
            clear_chat_session(f"standalone:{run_id}", persist=False)
            shutil.rmtree(scratch, ignore_errors=True)
            if remove_project_directory:
                shutil.rmtree(project_directory, ignore_errors=True)

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
    kernel_stopped = False
    if analysis_session_id := _ANALYSIS_SESSIONS_BY_RUN.pop(run_id, None):
        try:
            kernel_stopped = _close_analysis_kernel(
                request.app, analysis_session_id
            )
        except Exception:
            kernel_stopped = False
    return JSONResponse({"stopped": stopped, "kernel_stopped": kernel_stopped})
