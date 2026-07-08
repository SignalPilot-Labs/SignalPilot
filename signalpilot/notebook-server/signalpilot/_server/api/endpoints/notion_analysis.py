# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import io
import json
import math
import mimetypes
import os
import re
import struct
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast
from urllib.parse import quote, unquote, unquote_to_bytes, urlencode, urlparse
from uuid import NAMESPACE_URL, uuid5

import msgspec
import requests
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, JSONResponse

from signalpilot import _loggers
from signalpilot._messaging.cell_output import CellOutput
from signalpilot._runtime.commands import SerializedQueryParams
from signalpilot._runtime.virtual_file import read_virtual_file
from signalpilot._server.ai.analysis_prompts import (
    analysis_prompt as _analysis_prompt,
)
from signalpilot._server.api.deps import AppState, AppStateBase
from signalpilot._server.api.endpoints.notion_urls import (
    trail_url as _trail_url,
)
from signalpilot._server.api.utils import parse_request
from signalpilot._server.chart_theme import (
    DEFAULT_CHART_THEME,
    ChartTheme,
    contrast_text,
    ranked_series_colors,
)
from signalpilot._server.export._session_cache import (
    persist_session_view_to_cache,
)
from signalpilot._server.router import APIRouter
from signalpilot._session.consumer import SessionConsumer
from signalpilot._session.model import ConnectionState
from signalpilot._session.state.serialize import get_session_cache_file
from signalpilot._types.ids import ConsumerId, SessionId

if TYPE_CHECKING:
    from starlette.requests import Request

    from signalpilot._messaging.types import KernelMessage

LOGGER = _loggers.sp_logger()

router = APIRouter()

AnalysisStatus = Literal["New", "Analyzing", "Done", "Failed"]
ConfidenceLabel = Literal["high", "medium", "lower"]
OutputMode = Literal["answer", "deliverable"]
DEFAULT_ANALYSIS_AGENT_MODEL = "claude-sonnet-4-5-20250929"
DEFAULT_SNAPSHOT_MAX_BYTES = 1_000_000
MAX_DATA_SNAPSHOTS = 5
_ANALYSIS_AGENT_MODEL_ENV_NAMES = (
    "SIGNALPILOT_ANALYSIS_AGENT_MODEL",
    "SIGNALPILOT_WORKER_AGENT_MODEL",
)


def _analysis_agent_model() -> str:
    for name in _ANALYSIS_AGENT_MODEL_ENV_NAMES:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return DEFAULT_ANALYSIS_AGENT_MODEL


class StartNotionAnalysisRequest(msgspec.Struct, rename="camel"):
    discussion_id: str
    source_url: str
    headline: str
    prompt: str
    created_at: str
    source: str = "notion"
    notion_request_page_id: str | None = None
    requester: list[str] = msgspec.field(default_factory=list)
    previous_messages: list[str] = msgspec.field(default_factory=list)
    output_mode: OutputMode = "answer"
    theme: dict[str, Any] | None = None


class RefreshNotionAnalysisRequest(msgspec.Struct, rename="camel"):
    ephemeral_run_id: str
    deliverable_id: str
    base_notebook_code: str
    prompt: str
    base_chat_events: list[dict[str, Any]] = msgspec.field(default_factory=list)
    base_final_packet: dict[str, Any] | None = None
    output_mode: OutputMode = "deliverable"
    base_notebook_path: str | None = None
    theme: dict[str, Any] | None = None


@dataclass
class AnalysisChart:
    title: str = ""
    url: str = ""
    caption: str = ""
    alt_text: str = ""
    include_in_comment: bool = True
    include_on_page: bool = True


@dataclass
class DataSnapshot:
    name: str = ""
    description: str = ""
    columns: list[str] | None = None
    row_count: int = 0
    filename: str = ""
    url: str = ""
    bytes: int = 0


@dataclass
class AnalysisResult:
    summary: str = ""
    confidence_score: ConfidenceLabel | None = None
    final_answer: str = ""
    gotchas: list[str] | None = None
    analysis_method: str = ""
    notion_comment: str = ""
    notion_charts: list[AnalysisChart] | None = None


@dataclass
class AnalysisRecord:
    request_id: str
    discussion_id: str
    session_id: str
    notebook_path: str
    trail_url: str
    status: AnalysisStatus
    headline: str
    source_url: str
    created_at: str
    source: str = "notion"
    notion_request_page_id: str | None = None
    output_mode: OutputMode = "answer"
    theme: dict[str, Any] | None = None
    data_snapshots: list[DataSnapshot] | None = None
    latest_commit_sha: str | None = None
    error: str | None = None
    result: AnalysisResult | None = None


@dataclass
class _ImageChartCandidate:
    cell_id: str
    title: str
    content_type: str
    content: bytes


class _DetachedConsumer(SessionConsumer):
    """No-op consumer for server-created sessions without a browser yet."""

    def __init__(self, consumer_id: ConsumerId) -> None:
        self._consumer_id = consumer_id

    @property
    def consumer_id(self) -> ConsumerId:
        return self._consumer_id

    def notify(self, notification: KernelMessage) -> None:
        del notification

    def connection_state(self) -> ConnectionState:
        return ConnectionState.ORPHANED


_records_by_request_id: dict[str, AnalysisRecord] = {}
_records_by_discussion_id: dict[str, str] = {}
_running_tasks: dict[str, asyncio.Task[None]] = {}
DEFAULT_AGENT_TIMEOUT_SECONDS = 1200.0
WARM_CONTEXT_MAX_CHARS = 12_000
WARM_CONTEXT_SCHEMA_MAX_TABLES = 10
WARM_CONTEXT_GATEWAY_TIMEOUT_SECONDS = 15


def _agent_timeout_seconds() -> float:
    raw_value = os.environ.get("SIGNALPILOT_NOTION_AGENT_TIMEOUT_SECONDS")
    if raw_value is None:
        return DEFAULT_AGENT_TIMEOUT_SECONDS
    try:
        timeout = float(raw_value)
    except ValueError:
        LOGGER.warning(
            "Invalid SIGNALPILOT_NOTION_AGENT_TIMEOUT_SECONDS=%r; using default",
            raw_value,
        )
        return DEFAULT_AGENT_TIMEOUT_SECONDS
    return max(30.0, timeout)


def _clip_warm_context(
    text: str,
    *,
    max_chars: int = WARM_CONTEXT_MAX_CHARS,
) -> str:
    if len(text) <= max_chars:
        return text
    note = (
        f"\n\n[Warm context truncated to {max_chars} characters. "
        "Run notebook schema-probe cells for any missing details.]"
    )
    return text[: max(0, max_chars - len(note))].rstrip() + note


def _gateway_json_get(
    path: str,
    params: dict[str, Any] | None = None,
    *,
    timeout_seconds: int = WARM_CONTEXT_GATEWAY_TIMEOUT_SECONDS,
) -> Any:
    from signalpilot._server.gateway_client import gateway_headers, gateway_url

    url = f"{gateway_url()}{path}"
    if params:
        query = urlencode(
            {key: value for key, value in params.items() if value is not None}
        )
        if query:
            url = f"{url}?{query}"
    _validate_gateway_json_url(url)
    headers = {"Accept": "application/json", **gateway_headers()}
    try:
        response = requests.get(url, headers=headers, timeout=timeout_seconds)
        response.raise_for_status()
    except requests.HTTPError as e:
        body = e.response.text[:500] if e.response is not None else ""
        status_code = e.response.status_code if e.response is not None else "error"
        raise RuntimeError(f"Gateway HTTP {status_code}: {body}") from e
    except requests.RequestException as e:
        raise RuntimeError(f"Gateway unavailable: {e}") from e
    body = response.text
    if not body:
        return None
    return json.loads(body)


def _validate_gateway_json_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("Gateway URL must be an absolute http or https URL")


def _connection_label(connection: dict[str, Any]) -> str:
    name = str(
        connection.get("name") or connection.get("connection_name") or ""
    )
    details = [
        str(connection.get("db_type") or connection.get("type") or "").strip(),
        str(
            connection.get("database") or connection.get("catalog") or ""
        ).strip(),
        str(
            connection.get("schema_name") or connection.get("schema") or ""
        ).strip(),
    ]
    suffix = ", ".join(item for item in details if item)
    return f"{name} ({suffix})" if suffix else name


def _choose_warm_connection(
    connections: list[dict[str, Any]],
    question: str,
) -> tuple[dict[str, Any] | None, str]:
    if not connections:
        return None, "no gateway connections were returned"
    if len(connections) == 1:
        return connections[0], "only available gateway connection"

    question_lower = question.lower()
    terms = {
        term
        for term in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", question_lower)
        if len(term) >= 3
    }

    def score(connection: dict[str, Any]) -> int:
        fields = [
            connection.get("name"),
            connection.get("connection_name"),
            connection.get("db_type"),
            connection.get("database"),
            connection.get("catalog"),
            connection.get("schema_name"),
            connection.get("schema"),
        ]
        haystack = " ".join(str(field or "").lower() for field in fields)
        value = sum(1 for term in terms if term in haystack)
        name = str(
            connection.get("name") or connection.get("connection_name") or ""
        )
        if name and name.lower() in question_lower:
            value += 8
        db_type = str(connection.get("db_type") or "")
        if db_type and db_type.lower() in question_lower:
            value += 3
        return value

    selected = max(connections, key=score)
    selected_score = score(selected)
    reason = (
        f"highest metadata match score ({selected_score})"
        if selected_score > 0
        else "first available gateway connection"
    )
    return selected, reason


def _relation_variants(value: str) -> set[str]:
    cleaned = re.sub(r"[\"`]", "", value).strip().lower()
    if not cleaned:
        return set()
    parts = [part for part in cleaned.split(".") if part]
    variants = {cleaned}
    if parts:
        variants.add(parts[-1])
    if len(parts) >= 2:
        variants.add(".".join(parts[-2:]))
    return variants


def _linked_table_names_from_schema_link(data: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    scores = data.get("scores")
    if isinstance(scores, dict):
        for key in scores:
            names.update(_relation_variants(str(key)))
    tables = data.get("tables")
    if isinstance(tables, dict):
        for key, table in tables.items():
            names.update(_relation_variants(str(key)))
            if isinstance(table, dict):
                schema = str(table.get("schema") or "")
                name = str(table.get("name") or "")
                if name:
                    names.update(
                        _relation_variants(
                            f"{schema}.{name}" if schema else name
                        )
                    )
    ddl = str(data.get("ddl") or "")
    for match in re.finditer(
        r"\bCREATE\s+(?:TABLE|VIEW)\s+([^\s(]+)", ddl, re.IGNORECASE
    ):
        names.update(_relation_variants(match.group(1)))
    schema = str(data.get("schema") or "")
    for line in schema.splitlines():
        table_name = line.split(" ", 1)[0].strip()
        if table_name:
            names.update(_relation_variants(table_name))
    return names


def _format_schema_link_section(
    data: dict[str, Any],
    *,
    connection_name: str,
    question: str,
) -> tuple[str, set[str]]:
    linked_names = _linked_table_names_from_schema_link(data)
    lines = [
        "## Materialized Warehouse Schema Link",
        f"- Connection: `{connection_name}`",
        f"- Question used for schema linking: {question}",
        (
            f"- Linked tables: {data.get('linked_tables', '?')}/"
            f"{data.get('total_tables', '?')}"
        ),
    ]
    if data.get("token_estimate") is not None:
        lines.append(
            f"- Estimated schema-link tokens: {data.get('token_estimate')}"
        )

    dialect = data.get("dialect")
    if dialect:
        lines.append(
            f"- Dialect hints: {json.dumps(dialect, default=str)[:600]}"
        )

    join_hints = data.get("join_hints")
    if isinstance(join_hints, list) and join_hints:
        lines.append("- Join hints:")
        lines.extend(f"  - {hint}" for hint in join_hints[:8])

    query_hints = data.get("query_hints")
    if isinstance(query_hints, list) and query_hints:
        lines.append("- Query hints:")
        lines.extend(f"  - {hint}" for hint in query_hints[:8])

    ddl = str(data.get("ddl") or data.get("schema") or "")
    if not ddl and isinstance(data.get("tables"), dict):
        ddl = json.dumps(data["tables"], indent=2, default=str)
    if ddl:
        lines.extend(["", "```sql", ddl, "```"])
    return "\n".join(lines), linked_names


def _manifest_node_score(
    node: dict[str, Any],
    *,
    linked_table_names: set[str],
    question_terms: set[str],
) -> int:
    if node.get("resource_type") != "model":
        return -1

    variants: set[str] = set()
    for field in ("relation_name", "alias", "name"):
        value = node.get(field)
        if isinstance(value, str):
            variants.update(_relation_variants(value))
    schema = str(node.get("schema") or "")
    alias = str(node.get("alias") or node.get("name") or "")
    if alias:
        variants.update(
            _relation_variants(f"{schema}.{alias}" if schema else alias)
        )

    score = 0
    if variants & linked_table_names:
        score += 40

    searchable_parts = [
        str(node.get("name") or ""),
        str(node.get("alias") or ""),
        str(node.get("description") or ""),
    ]
    columns = node.get("columns")
    if isinstance(columns, dict):
        searchable_parts.extend(str(name) for name in columns)
    haystack = " ".join(searchable_parts).lower()
    score += sum(2 for term in question_terms if term in haystack)
    return score


def _dbt_manifest_hints(
    project_root: Path,
    *,
    linked_table_names: set[str],
    question: str,
) -> str:
    manifest_path = project_root / "target" / "manifest.json"
    if not manifest_path.exists():
        return ""

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        return (
            "## dbt Manifest Hints\n"
            f"- `target/manifest.json` exists but could not be parsed: {e}"
        )

    question_terms = {
        term
        for term in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", question.lower())
        if len(term) >= 3
    }
    nodes = manifest.get("nodes")
    if not isinstance(nodes, dict):
        return "## dbt Manifest Hints\n- `target/manifest.json` has no model nodes."

    scored: list[tuple[int, str, dict[str, Any]]] = []
    for unique_id, node in nodes.items():
        if not isinstance(node, dict):
            continue
        score = _manifest_node_score(
            node,
            linked_table_names=linked_table_names,
            question_terms=question_terms,
        )
        if score > 0:
            scored.append((score, str(unique_id), node))
    scored.sort(key=lambda item: (-item[0], item[1]))

    if not scored:
        return (
            "## dbt Manifest Hints\n"
            "- `target/manifest.json` exists, but no selected model metadata "
            "matched the linked warehouse tables or question terms."
        )

    lines = [
        "## dbt Manifest Hints",
        "- Source: `target/manifest.json` only; selected matching models, no dbt file crawl.",
    ]
    for score, unique_id, node in scored[:8]:
        name = str(node.get("name") or unique_id)
        relation_name = str(
            node.get("relation_name") or node.get("alias") or name
        )
        lines.append(
            f"- `{unique_id}` -> `{relation_name}` (match score {score})"
        )
        description = str(node.get("description") or "").strip()
        if description:
            lines.append(f"  - description: {description[:240]}")
        columns = node.get("columns")
        if isinstance(columns, dict) and columns:
            lines.append(
                "  - columns: "
                + ", ".join(
                    str(column_name)
                    for column_name in list(columns.keys())[:16]
                )
            )
        depends_on = node.get("depends_on")
        if isinstance(depends_on, dict):
            dep_nodes = depends_on.get("nodes")
            if isinstance(dep_nodes, list) and dep_nodes:
                lines.append(
                    "  - depends_on: "
                    + ", ".join(str(dep) for dep in dep_nodes[:8])
                )
    return "\n".join(lines)


def _build_analysis_warm_context(
    app_state: AppState,
    body: StartNotionAnalysisRequest,
    *,
    project_root: Path,
) -> str:
    del app_state

    question = body.prompt.strip() or body.headline.strip()
    sections = [
        "## Warm Context",
        (
            "- This bounded context was prepared before the notebook agent run. "
            "Use it for orientation only; final evidence still must come from "
            "notebook-executed SDK cells."
        ),
    ]

    try:
        from signalpilot._server.gateway_client import gateway_headers

        if not gateway_headers() and "SP_GATEWAY_URL" not in os.environ:
            sections.append(
                "- Gateway REST warm start skipped because no gateway URL or "
                "auth environment was configured."
            )
            return _clip_warm_context("\n".join(sections))

        raw_connections = _gateway_json_get("/api/connections")
        connections = (
            raw_connections if isinstance(raw_connections, list) else []
        )
        selected, reason = _choose_warm_connection(connections, question)

        sections.append("## Connection Discovery")
        if connections:
            sections.append(f"- Available connections: {len(connections)}")
            for connection in connections[:8]:
                sections.append(f"  - `{_connection_label(connection)}`")
            if len(connections) > 8:
                sections.append(f"  - ... {len(connections) - 8} more")
        else:
            sections.append("- Gateway returned no available connections.")

        if selected is None:
            return _clip_warm_context("\n".join(sections))

        connection_name = str(
            selected.get("name") or selected.get("connection_name") or ""
        )
        sections.append(f"- Likely connection: `{connection_name}` ({reason})")

        if connection_name:
            schema_link = _gateway_json_get(
                f"/api/connections/{quote(connection_name, safe='')}/schema/link",
                {
                    "question": question,
                    "format": "ddl",
                    "max_tables": WARM_CONTEXT_SCHEMA_MAX_TABLES,
                    "prune_columns": "true",
                },
            )
            if isinstance(schema_link, dict):
                schema_section, linked_names = _format_schema_link_section(
                    schema_link,
                    connection_name=connection_name,
                    question=question,
                )
                sections.append(schema_section)
                manifest_hints = _dbt_manifest_hints(
                    project_root,
                    linked_table_names=linked_names,
                    question=question,
                )
                if manifest_hints:
                    sections.append(manifest_hints)
            else:
                sections.append(
                    "- Gateway schema link returned no JSON object."
                )
    except Exception as e:
        LOGGER.info("Analysis warm context unavailable: %s", e)
        sections.append(f"- Warm context unavailable: {e}")

    return _clip_warm_context("\n".join(sections))


def _parse_chart_list(value: Any) -> list[AnalysisChart]:
    if not isinstance(value, list):
        return []
    charts: list[AnalysisChart] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        charts.append(
            AnalysisChart(
                title=str(item.get("title", "")),
                url=str(item.get("url", "")),
                caption=str(item.get("caption", "")),
                alt_text=str(item.get("altText", item.get("alt_text", ""))),
                include_in_comment=bool(
                    item.get(
                        "includeInComment",
                        item.get("include_in_comment", True),
                    )
                ),
                include_on_page=bool(
                    item.get(
                        "includeOnPage", item.get("include_on_page", True)
                    )
                ),
            )
        )
    return charts


def _parse_data_snapshot_list(value: Any) -> list[DataSnapshot]:
    if not isinstance(value, list):
        return []
    snapshots: list[DataSnapshot] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        columns_raw = item.get("columns") or []
        columns = (
            [str(column) for column in columns_raw]
            if isinstance(columns_raw, list)
            else []
        )
        snapshots.append(
            DataSnapshot(
                name=str(item.get("name", "")),
                description=str(item.get("description", "")),
                columns=columns,
                row_count=int(
                    item.get("row_count", item.get("rowCount", 0)) or 0
                ),
                filename=str(item.get("filename", "")),
                url=str(item.get("url", "")),
                bytes=int(item.get("bytes", 0) or 0),
            )
        )
    return snapshots


def _analysis_result_from_dict(value: dict[str, Any]) -> AnalysisResult:
    result = dict(value)
    result["notion_charts"] = _parse_chart_list(
        result.get("notionCharts", result.get("notion_charts", []))
    )
    result.pop("notionCharts", None)
    return AnalysisResult(**result)


def _output_mode(value: str | None) -> OutputMode:
    return "deliverable" if value == "deliverable" else "answer"


def _analysis_source(value: str | None) -> str:
    source = re.sub(
        r"[^a-zA-Z0-9_-]+", "-", (value or "notion").strip().lower()
    ).strip("-")
    return source or "notion"


def _analysis_project_context(
    app_state: AppState,
) -> tuple[str, str] | None:
    request = getattr(app_state, "request", None)
    headers = getattr(request, "headers", {}) or {}
    query_params = getattr(app_state, "query_params", lambda _key: None)
    project_id = (
        headers.get("x-gateway-project-id", "")
        or query_params("project")
        or ""
    ).strip()
    if not project_id:
        return None
    branch = (
        headers.get("x-gateway-branch-id", "")
        or query_params("branch")
        or "main"
    ).strip() or "main"
    return project_id, branch


def _project_root(app_state: AppState) -> Path:
    context = _analysis_project_context(app_state)
    if context is not None:
        project_id, branch = context
        try:
            from signalpilot._server.files.project_sync import (
                _current_git_branch,
                local_project_dir,
                sync_down,
            )

            local_dir = local_project_dir(project_id, branch)
            if (
                (local_dir / ".git").exists()
                and _current_git_branch(local_dir) == branch
            ):
                return local_dir

            result = sync_down(project_id, branch)
            if result.get("error"):
                raise RuntimeError(result["error"])
            synced_dir = Path(str(result.get("local_dir") or local_dir))
            if (synced_dir / ".git").exists():
                return synced_dir
            raise RuntimeError(
                f"Synced project checkout missing .git: {synced_dir}"
            )
        except Exception as e:
            message = f"Could not resolve project root for analysis project {project_id}: {e}"
            LOGGER.error(message)
            raise RuntimeError(message) from e

    root = app_state.session_manager.workspace.directory
    if root is None:
        return Path.cwd()
    return Path(root)


def _records_dir(app_state: AppState, source: str = "notion") -> Path:
    path = _project_root(app_state) / "notebooks" / _analysis_source(source)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _registry_path(app_state: AppState) -> Path:
    path = (
        _project_root(app_state)
        / "notebooks"
        / ".signalpilot-analysis-registry.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_notebook_path(app_state: AppState, notebook_path: str) -> Path:
    path = Path(notebook_path)
    if path.is_absolute():
        return path
    return _project_root(app_state) / path


def _load_registry(app_state: AppState) -> None:
    path = _registry_path(app_state)
    if not path.exists():
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        LOGGER.warning("Failed to read Notion analysis registry: %s", e)
        return

    for item in raw.get("records", []):
        result = item.get("result")
        disk_record = AnalysisRecord(
            request_id=item["request_id"],
            discussion_id=item["discussion_id"],
            session_id=item["session_id"],
            notebook_path=item["notebook_path"],
            trail_url=item["trail_url"],
            status=item["status"],
            headline=item["headline"],
            source_url=item["source_url"],
            created_at=item["created_at"],
            source=item.get("source", "notion"),
            notion_request_page_id=item.get("notion_request_page_id"),
            output_mode=_output_mode(item.get("output_mode")),
            theme=item.get("theme"),
            data_snapshots=_parse_data_snapshot_list(
                item.get("data_snapshots", item.get("dataSnapshots", []))
            ),
            latest_commit_sha=item.get("latest_commit_sha"),
            error=item.get("error"),
            result=_analysis_result_from_dict(result) if result else None,
        )
        record = _records_by_request_id.get(disk_record.request_id)
        if record is None or disk_record.request_id not in _running_tasks:
            record = disk_record
            _records_by_request_id[record.request_id] = record
        _records_by_discussion_id[record.discussion_id] = record.request_id


def _save_registry(app_state: AppState) -> None:
    path = _registry_path(app_state)
    records = []
    for record in _records_by_request_id.values():
        item = asdict(record)
        # The gateway DB stores the authoritative latest commit SHA. Persisting
        # it inside the committed registry would make the registry dirty after
        # every commit because the commit SHA changes when the registry changes.
        item.pop("latest_commit_sha", None)
        records.append(item)
    path.write_text(
        json.dumps({"records": records}, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:80] or "analysis-request"


def _request_id(discussion_id: str, source: str = "notion") -> str:
    return f"{_analysis_source(source)}-{uuid5(NAMESPACE_URL, discussion_id).hex[:16]}"


def _session_id(request_id: str) -> SessionId:
    return SessionId(f"session-{request_id}")


def _refresh_trail_url(
    app_state: AppState,
    record: AnalysisRecord,
    request_base_url: str,
) -> None:
    trail_url = _record_trail_url(
        app_state,
        record.notebook_path,
        record.session_id,
        request_base_url,
    )
    if record.trail_url == trail_url:
        return
    record.trail_url = trail_url
    _save_registry(app_state)


def _record_trail_url(
    app_state: AppState,
    notebook_path: str,
    session_id: str,
    request_base_url: str,
) -> str:
    project_id = app_state.request.headers.get(
        "x-gateway-project-id", ""
    ).strip()
    branch = app_state.request.headers.get("x-gateway-branch-id", "").strip()
    return _trail_url(
        notebook_path,
        session_id,
        request_base_url,
        project_id=project_id or None,
        branch=branch or None,
    )


def _notebook_template(body: StartNotionAnalysisRequest) -> str:
    request_context = f"""# SignalPilot analysis

**Source request:** {body.source_url}

**Source prompt:**

{body.prompt}
"""
    request_context_json = json.dumps(request_context)
    return f'''import signalpilot as sp

__generated_with = "0.1.0"
app = sp.App()


@app.cell(hide_code=True)
def _():
    import signalpilot as sp
    sp.md({request_context_json})
    return (sp,)


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Executive Summary and Explorations

    Pending analysis.
    """)


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Analysis steps

    Pending analysis.
    """)


if __name__ == "__main__":
    app.run()
	'''


def _refresh_request_id(ephemeral_run_id: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", ephemeral_run_id.strip()).strip("-")
    if not slug:
        slug = uuid5(NAMESPACE_URL, "notion-refresh").hex[:16]
    return slug if slug.startswith("notion-refresh-") else f"notion-refresh-{slug}"


def _refresh_discussion_id(body: RefreshNotionAnalysisRequest) -> str:
    return f"refresh:{body.deliverable_id}:{body.ephemeral_run_id}"


def _refresh_records_dir(app_state: AppState) -> Path:
    path = _project_root(app_state) / "notebooks" / "notion-refresh"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_refresh_notebook(
    app_state: AppState,
    body: RefreshNotionAnalysisRequest,
    request_id: str,
) -> str:
    if not body.base_notebook_code.strip():
        raise ValueError("baseNotebookCode is required for deliverable refresh")
    filename = f"{_slugify(body.deliverable_id)}-{request_id[-8:]}.py"
    notebook_path = _refresh_records_dir(app_state) / filename
    notebook_path.write_text(body.base_notebook_code, encoding="utf-8")
    root = _project_root(app_state)
    return (
        str(notebook_path.relative_to(root))
        if notebook_path.is_relative_to(root)
        else str(notebook_path)
    )


def _refresh_previous_messages(body: RefreshNotionAnalysisRequest) -> list[str]:
    messages: list[str] = [
        "This is an isolated refresh of an existing SignalPilot HTML deliverable.",
        "Use the notebook file seeded from the immutable code captured when the deliverable was created.",
        "Do not read or resume the original notebook path; it is metadata only.",
    ]
    if body.base_notebook_path:
        messages.append(f"Original notebook path metadata: {body.base_notebook_path}")
    if body.base_final_packet:
        summary = json.dumps(body.base_final_packet, ensure_ascii=True, separators=(",", ":"))
        messages.append(f"Original final delivery packet snapshot: {_clip_warm_context(summary, max_chars=6000)}")
    if body.base_chat_events:
        event_text = json.dumps(body.base_chat_events[-40:], ensure_ascii=True, separators=(",", ":"))
        messages.append(f"Bounded original chat trace snapshot: {_clip_warm_context(event_text, max_chars=6000)}")
    return messages


def _refresh_start_body(body: RefreshNotionAnalysisRequest) -> StartNotionAnalysisRequest:
    return StartNotionAnalysisRequest(
        discussion_id=_refresh_discussion_id(body),
        source_url=f"notion-deliverable:{body.deliverable_id}",
        headline=f"Refresh deliverable {body.deliverable_id[:8]}",
        prompt=body.prompt,
        created_at=datetime.now(UTC).isoformat(),
        source="notion",
        previous_messages=_refresh_previous_messages(body),
        output_mode=body.output_mode,
        theme=body.theme,
    )


def _append_followup_to_notebook(
    app_state: AppState,
    record: AnalysisRecord,
    body: StartNotionAnalysisRequest,
) -> None:
    path = _resolve_notebook_path(app_state, record.notebook_path)
    if not path.exists():
        return

    prompt_json = json.dumps(body.prompt)
    followup_cell = f'''


@app.cell
def _(sp):
    _followup_prompt = {prompt_json}
    sp.md(f"""
    ## Follow-up Request

    ### New requester prompt

    {{_followup_prompt}}

    ### Follow-up Analysis steps

    Append only the new queries, checks, evidence, visuals, and revised answer
    needed for this follow-up. Do not delete prior analysis work.
    """)
'''
    text = path.read_text(encoding="utf-8")
    marker = '\n\nif __name__ == "__main__":\n'
    if marker in text:
        text = text.replace(marker, followup_cell + marker, 1)
    else:
        text += followup_cell
    path.write_text(text, encoding="utf-8")


def _checkpoint_analysis_files(
    app_state: AppState,
    record: AnalysisRecord,
    message: str,
    *,
    include_parent_dir: bool = False,
) -> str | None:
    context = _analysis_project_context(app_state)
    if context is None:
        return None
    project_id, branch = context
    try:
        from signalpilot._server.files.git_auth import run_git
        from signalpilot._server.files.project_sync import (
            local_project_dir,
            sync_up,
        )

        repo = local_project_dir(project_id)
        if not (repo / ".git").exists():
            return None

        notebook_path = _resolve_notebook_path(app_state, record.notebook_path)
        targets = [
            notebook_path.parent if include_parent_dir else notebook_path,
            _registry_path(app_state),
        ]
        rel_targets: list[str] = []
        for target in targets:
            try:
                resolved = target.resolve(strict=False)
                resolved.relative_to(repo.resolve())
            except (OSError, ValueError):
                continue
            rel_targets.append(str(resolved.relative_to(repo.resolve())))
        if not rel_targets:
            return None

        code, _, err = run_git(repo, "add", "--", *rel_targets)
        if code != 0:
            LOGGER.warning("Could not stage analysis files: %s", err.strip())
            return None

        diff_code, _, _ = run_git(repo, "diff", "--cached", "--quiet")
        if diff_code == 1:
            code, out, err = run_git(
                repo, "commit", "-m", message, timeout=120
            )
            if code != 0:
                LOGGER.warning(
                    "Could not commit analysis files: %s", (err or out).strip()
                )
                return None
            sync_result = sync_up(project_id, branch)
            if sync_result.get("error"):
                LOGGER.warning(
                    "Could not push analysis checkpoint: %s",
                    sync_result["error"],
                )
        elif diff_code != 0:
            LOGGER.warning("Could not inspect staged analysis diff")
            return None

        code, out, _ = run_git(repo, "rev-parse", "HEAD")
        if code == 0 and out.strip():
            record.latest_commit_sha = out.strip()
            _save_registry(app_state)
            return record.latest_commit_sha
    except Exception as e:
        LOGGER.warning(
            "Analysis git checkpoint failed for %s: %s", record.request_id, e
        )
    return None


def _ensure_record(
    app_state: AppState,
    body: StartNotionAnalysisRequest,
    request_base_url: str,
) -> AnalysisRecord:
    _load_registry(app_state)
    existing_id = _records_by_discussion_id.get(body.discussion_id)
    if existing_id:
        record = _records_by_request_id[existing_id]
        record.output_mode = _output_mode(body.output_mode)
        _refresh_trail_url(app_state, record, request_base_url)
        if record.status != "Analyzing":
            _append_followup_to_notebook(app_state, record, body)
            _checkpoint_analysis_files(
                app_state, record, f"Append {record.source} analysis follow-up"
            )
        return record

    source = _analysis_source(body.source)
    request_id = _request_id(body.discussion_id, source)
    filename = f"{_slugify(body.headline)}-{request_id[-6:]}.py"
    notebook_path = _records_dir(app_state, source) / filename
    notebook_path.write_text(_notebook_template(body), encoding="utf-8")

    root = _project_root(app_state)
    file_key = (
        str(notebook_path.relative_to(root))
        if notebook_path.is_relative_to(root)
        else str(notebook_path)
    )
    session_id = str(_session_id(request_id))
    trail_url = _record_trail_url(
        app_state, file_key, session_id, request_base_url
    )

    record = AnalysisRecord(
        request_id=request_id,
        discussion_id=body.discussion_id,
        session_id=session_id,
        notebook_path=file_key,
        trail_url=trail_url,
        status="New",
        headline=body.headline,
        source_url=body.source_url,
        created_at=body.created_at,
        source=source,
        notion_request_page_id=body.notion_request_page_id,
        output_mode=_output_mode(body.output_mode),
        theme=body.theme,
        data_snapshots=[],
    )
    _records_by_request_id[record.request_id] = record
    _records_by_discussion_id[record.discussion_id] = record.request_id
    _save_registry(app_state)
    _checkpoint_analysis_files(
        app_state, record, f"Create {source} analysis notebook"
    )
    return record


def _ensure_session(
    app_state: AppState,
    record: AnalysisRecord,
    *,
    allow_resume: bool = True,
) -> None:
    session_id = SessionId(record.session_id)
    if app_state.session_manager.get_session(session_id) is not None:
        return

    if allow_resume:
        app_state.session_manager.maybe_resume_session(
            session_id, record.notebook_path
        )
        if app_state.session_manager.get_session(session_id) is not None:
            return

    app_state.session_manager.create_session(
        session_id=session_id,
        session_consumer=_DetachedConsumer(ConsumerId(record.session_id)),
        query_params=SerializedQueryParams(),
        file_key=record.notebook_path,
        auto_instantiate=True,
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    decoder = json.JSONDecoder()
    result_keys = {
        "summary",
        "confidenceScore",
        "confidence_score",
        "finalAnswer",
        "final_answer",
    }

    fenced_blocks = re.findall(
        r"```(?:json)?\s*(.*?)```",
        stripped,
        flags=re.DOTALL | re.IGNORECASE,
    )
    for block in reversed(fenced_blocks):
        candidate = block.strip()
        if not candidate.startswith("{"):
            continue
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data

    if stripped.startswith("{"):
        try:
            data, _ = decoder.raw_decode(stripped)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(data, dict):
                return data

    for match in reversed(list(re.finditer(r"\{", stripped))):
        candidate = stripped[match.start() :]
        try:
            data, _ = decoder.raw_decode(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and result_keys.intersection(data.keys()):
            return data

    raise ValueError("Agent did not return a JSON object")


def _parse_result(text: str) -> AnalysisResult:
    data = _extract_json_object(text)
    confidence = _confidence_label(
        data.get("confidenceScore", data.get("confidence_score"))
    )
    gotchas = data.get("gotchas") or []
    if not isinstance(gotchas, list):
        gotchas = [str(gotchas)]
    parsed_charts = _parse_chart_list(
        data.get("notionCharts", data.get("notion_charts", [])) or []
    )
    return AnalysisResult(
        summary=str(data.get("summary", "")),
        confidence_score=confidence,
        final_answer=str(
            data.get("finalAnswer", data.get("final_answer", ""))
        ),
        gotchas=[str(item) for item in gotchas],
        analysis_method=str(
            data.get(
                "analysisMethod",
                data.get("analysis_method", data.get("methodology", "")),
            )
        ),
        notion_comment=str(
            data.get("notionComment", data.get("notion_comment", ""))
        ),
        notion_charts=parsed_charts,
    )


def _parse_final_statement_result(text: str) -> AnalysisResult:
    data = _extract_marker_json(text, "FINAL_STATEMENT")
    statement = str(data.get("statement", "")).strip()
    if not statement:
        raise ValueError("Agent did not emit FINAL_STATEMENT.statement")
    confidence = _confidence_label(
        data.get("confidenceScore", data.get("confidence_score"))
    )
    caveats = data.get("caveats") or []
    if not isinstance(caveats, list):
        caveats = [str(caveats)]
    handoff_notes = (
        data.get("handoffNotes", data.get("handoff_notes", [])) or []
    )
    if not isinstance(handoff_notes, list):
        handoff_notes = [str(handoff_notes)]
    return AnalysisResult(
        summary=statement[:500],
        confidence_score=confidence,
        final_answer=statement,
        gotchas=[str(item) for item in caveats],
        analysis_method="; ".join(str(item) for item in handoff_notes),
        notion_comment=statement[:1200],
        notion_charts=[],
    )


def _extract_marker_json(text: str, marker: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    latest: dict[str, Any] | None = None
    for match in re.finditer(rf"(?m)^\s*{re.escape(marker)}\s*:\s*", text):
        try:
            parsed, _ = decoder.raw_decode(text[match.end() :].lstrip())
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            latest = parsed
    if latest is None:
        raise ValueError(f"Agent did not emit {marker}")
    return latest


def _confidence_label(value: Any) -> ConfidenceLabel | None:
    if not isinstance(value, str):
        return None
    label = value.strip()
    if label in ("high", "medium", "lower"):
        return cast(ConfidenceLabel, label)
    return None


def _is_transient_agent_overload(text: str) -> bool:
    normalized = text.lower()
    return any(
        marker in normalized
        for marker in (
            "api error: overloaded",
            "overloaded_error",
            "rate_limit_error",
            "rate limited",
        )
    )


def _agent_overload_retry_prompt(original_prompt: str) -> str:
    return (
        "The previous notebook analysis attempt was interrupted by a transient "
        "model-provider overload before it emitted FINAL_STATEMENT. Continue "
        "from the current notebook state, reuse any completed notebook outputs "
        "when they are available, and finish the requested analysis. End with "
        "exactly one FINAL_STATEMENT JSON marker.\n\n"
        f"Original user request:\n{original_prompt}"
    )


def _truncate_comment(text: str, limit: int = 1200) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _plain_text_failure_result(text: str, error: Exception) -> AnalysisResult:
    detail = text.strip() or str(error)
    return AnalysisResult(
        summary="Analysis could not be completed.",
        confidence_score="lower",
        final_answer=(
            "## Executive Summary and Explorations\n\n"
            "- I could not complete the requested analysis.\n"
            "- The agent did not emit the required FINAL_STATEMENT marker, so "
            "SignalPilot preserved the available failure details below.\n\n"
            "## Detailed Research\n\n"
            f"{detail}\n\n"
            "## Confidence Score: lower\n\n"
            "- No relevant dbt model backed a completed final answer."
        ),
        gotchas=[
            "The agent did not emit the required FINAL_STATEMENT marker.",
            "The analysis should be rerun after inspecting the notebook trail.",
        ],
        analysis_method=(
            "The agent did not emit the required FINAL_STATEMENT marker; "
            "SignalPilot preserved the available text as failure detail."
        ),
        notion_comment=_truncate_comment(
            f"I could not complete the requested analysis.\n\n{detail}"
        ),
    )


def _timeout_failure_result(timeout_seconds: float) -> AnalysisResult:
    minutes = max(1, round(timeout_seconds / 60))
    return AnalysisResult(
        summary="Analysis timed out before completion.",
        confidence_score="lower",
        final_answer=(
            "## Executive Summary and Explorations\n\n"
            "- I could not complete the requested analysis.\n"
            f"- The notebook agent exceeded the {minutes}-minute execution "
            "deadline before it edited and ran the notebook.\n"
            "- No completed analysis result was produced.\n\n"
            "## Detailed Research\n\n"
            "The agent was stopped by SignalPilot because it did not complete "
            "the notebook-first workflow within the allowed runtime. The "
            "request should be rerun after inspecting the agent event log for "
            "where progress stalled.\n\n"
            "## Confidence Score: lower\n\n"
            "- No relevant dbt model backed a completed final answer."
        ),
        gotchas=[
            "The notebook agent timed out before completion.",
            "The notebook may contain only partial setup or scouting notes.",
        ],
        analysis_method=(
            "SignalPilot stopped the notebook agent after it exceeded the "
            f"{minutes}-minute execution deadline."
        ),
        notion_comment=(
            "I could not complete the requested analysis because the notebook "
            f"agent exceeded the {minutes}-minute execution deadline before "
            "finishing the notebook run."
        ),
    )


def _persist_record_session_cache(
    app_state: AppState, record: AnalysisRecord
) -> Path | None:
    session = app_state.session_manager.get_session(
        SessionId(record.session_id)
    )
    if session is None:
        return None

    notebook_path = _resolve_notebook_path(app_state, record.notebook_path)
    return persist_session_view_to_cache(
        view=session.session_view,
        notebook_path=notebook_path,
        cell_ids=session.document.cell_ids,
    )


def _chart_dir(app_state: AppState, record: AnalysisRecord) -> Path:
    notebook_path = _resolve_notebook_path(app_state, record.notebook_path)
    chart_dir = notebook_path.parent / "public" / "signalpilot-notion-charts"
    chart_dir.mkdir(parents=True, exist_ok=True)
    return chart_dir


def _chart_url(
    app_state: AppState, record: AnalysisRecord, filename: str
) -> str:
    url = f"/api/notion-analysis/chart/{record.request_id}/{filename}"
    context = _analysis_project_context(app_state)
    if context is None:
        return url
    project_id, branch = context
    return f"{url}?{urlencode({'project': project_id, 'branch': branch})}"


def _snapshot_dir(app_state: AppStateBase, record: AnalysisRecord) -> Path:
    notebook_path = _resolve_notebook_path(app_state, record.notebook_path)
    snapshot_dir = (
        notebook_path.parent
        / "public"
        / "signalpilot-notion-snapshots"
        / record.request_id
    )
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    return snapshot_dir


def _snapshot_url(
    app_state: AppStateBase, record: AnalysisRecord, filename: str
) -> str:
    url = f"/api/notion-analysis/snapshot/{record.request_id}/{filename}"
    context = _analysis_project_context(app_state)
    if context is None:
        return url
    project_id, branch = context
    return f"{url}?{urlencode({'project': project_id, 'branch': branch})}"


def _chart_file_from_project_registries(
    request_id: str, filename: str
) -> Path | None:
    try:
        from signalpilot._server.files.project_sync import PROJECTS_ROOT
    except Exception:
        return None

    for registry_path in PROJECTS_ROOT.glob(
        "*/**/notebooks/.signalpilot-analysis-registry.json"
    ):
        try:
            raw = json.loads(registry_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        records = raw.get("records", [])
        if not isinstance(records, list):
            continue
        for item in records:
            if (
                not isinstance(item, dict)
                or item.get("request_id") != request_id
            ):
                continue
            notebook_path = item.get("notebook_path")
            if not isinstance(notebook_path, str) or not notebook_path:
                continue
            repo = registry_path.parent.parent
            chart_dir = (
                repo
                / notebook_path
            ).parent / "public" / "signalpilot-notion-charts"
            try:
                resolved_dir = chart_dir.resolve(strict=True)
                chart_path = (resolved_dir / filename).resolve(strict=True)
                chart_path.relative_to(resolved_dir)
            except (OSError, ValueError):
                continue
            if chart_path.is_file():
                return chart_path
    return None


def _snapshot_file_from_project_registries(
    request_id: str, filename: str
) -> Path | None:
    try:
        from signalpilot._server.files.project_sync import PROJECTS_ROOT
    except Exception:
        return None

    for registry_path in PROJECTS_ROOT.glob(
        "*/**/notebooks/.signalpilot-analysis-registry.json"
    ):
        try:
            raw = json.loads(registry_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        records = raw.get("records", [])
        if not isinstance(records, list):
            continue
        for item in records:
            if (
                not isinstance(item, dict)
                or item.get("request_id") != request_id
            ):
                continue
            notebook_path = item.get("notebook_path")
            if not isinstance(notebook_path, str) or not notebook_path:
                continue
            repo = registry_path.parent.parent
            snapshot_dir = (
                (repo / notebook_path).parent
                / "public"
                / "signalpilot-notion-snapshots"
                / request_id
            )
            try:
                resolved_dir = snapshot_dir.resolve(strict=True)
                snapshot_path = (resolved_dir / filename).resolve(strict=True)
                snapshot_path.relative_to(resolved_dir)
            except (OSError, ValueError):
                continue
            if snapshot_path.is_file():
                return snapshot_path
    return None


def _snapshot_max_bytes() -> int:
    raw_value = os.environ.get("SIGNALPILOT_SNAPSHOT_MAX_BYTES")
    if raw_value is None:
        return DEFAULT_SNAPSHOT_MAX_BYTES
    try:
        return max(1024, int(raw_value))
    except ValueError:
        LOGGER.warning(
            "Invalid SIGNALPILOT_SNAPSHOT_MAX_BYTES=%r; using default",
            raw_value,
        )
        return DEFAULT_SNAPSHOT_MAX_BYTES


def _snapshot_filename(name: str, index: int) -> str:
    stem = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    stem = stem[:80] or "data-snapshot"
    return f"{stem}-{index}.json"


def save_data_snapshot_for_session(
    app_state: AppStateBase,
    *,
    session_id: str,
    name: str,
    description: str,
    columns: list[Any],
    rows: list[Any],
) -> dict[str, Any]:
    _load_registry(app_state)
    record = next(
        (
            item
            for item in _records_by_request_id.values()
            if item.session_id == session_id
        ),
        None,
    )
    if record is None:
        raise ValueError(
            f"No active analysis record for session_id={session_id}"
        )

    if not isinstance(columns, list) or not isinstance(rows, list):
        raise ValueError("columns and rows must be JSON arrays")

    snapshots = list(record.data_snapshots or [])
    normalized_name = name.strip() or f"Data snapshot {len(snapshots) + 1}"
    existing_index = next(
        (
            index
            for index, snapshot in enumerate(snapshots)
            if snapshot.name == normalized_name
        ),
        None,
    )
    if existing_index is None and len(snapshots) >= MAX_DATA_SNAPSHOTS:
        raise ValueError(
            f"At most {MAX_DATA_SNAPSHOTS} data snapshots are allowed"
        )

    filename = (
        snapshots[existing_index].filename
        if existing_index is not None
        else _snapshot_filename(normalized_name, len(snapshots) + 1)
    )
    payload = {
        "name": normalized_name,
        "description": description.strip(),
        "columns": [str(column) for column in columns],
        "rows": rows,
    }
    try:
        content = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Snapshot rows must be JSON serializable: {exc}"
        ) from exc

    max_bytes = _snapshot_max_bytes()
    if len(content) > max_bytes:
        raise ValueError(
            f"Snapshot is {len(content)} bytes; the limit is {max_bytes} bytes"
        )

    snapshot_path = _snapshot_dir(app_state, record) / filename
    snapshot_path.write_bytes(content)
    snapshot = DataSnapshot(
        name=normalized_name,
        description=description.strip(),
        columns=[str(column) for column in columns],
        row_count=len(rows),
        filename=filename,
        url=_snapshot_url(app_state, record, filename),
        bytes=len(content),
    )
    if existing_index is None:
        snapshots.append(snapshot)
    else:
        snapshots[existing_index] = snapshot
    record.data_snapshots = snapshots
    _save_registry(app_state)
    return {
        "name": snapshot.name,
        "description": snapshot.description,
        "columns": snapshot.columns or [],
        "rowCount": snapshot.row_count,
        "filename": snapshot.filename,
        "url": snapshot.url,
        "bytes": snapshot.bytes,
    }


def _chart_filename_extension(content_type: str) -> str:
    normalized = content_type.lower().split(";", 1)[0].strip()
    if normalized == "image/jpeg":
        return "jpg"
    if normalized == "image/svg+xml":
        return "svg"
    if normalized == "image/gif":
        return "gif"
    if normalized == "image/webp":
        return "webp"
    return "png"


def _chart_url_path(url: str) -> str:
    return unquote(urlparse(url).path or url.split("?", 1)[0])


def _workspace_file_from_url(app_state: AppState, url: str) -> Path | None:
    url_path = _chart_url_path(url)
    workspace_root = app_state.session_manager.workspace.directory
    if workspace_root is None:
        workspace = Path.cwd().resolve()
    else:
        workspace = Path(workspace_root).resolve()

    candidates: list[Path] = []
    if url_path.startswith("/files/"):
        candidates.append(workspace / url_path.removeprefix("/files/"))
    elif url_path.startswith("/@file/"):
        candidates.append(workspace / url_path.removeprefix("/@file/"))
    elif not urlparse(url).scheme:
        if url_path.startswith("/"):
            candidates.append(Path(url_path))
            candidates.append(workspace / url_path.lstrip("/"))
        else:
            candidates.append(workspace / url_path)

    if not candidates:
        return None

    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(workspace)
        except (OSError, ValueError):
            continue

        if not resolved.is_file():
            continue
        if resolved.suffix.lower() not in {
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".webp",
        }:
            continue
        return resolved
    return None


def _workspace_chart_file(
    app_state: AppState, chart: AnalysisChart
) -> Path | None:
    return _workspace_file_from_url(app_state, chart.url)


def _backend_chart_file_exists(
    app_state: AppState, record: AnalysisRecord, chart: AnalysisChart
) -> bool:
    url_path = _chart_url_path(chart.url)
    prefix = f"/api/notion-analysis/chart/{record.request_id}/"
    if not url_path.startswith(prefix):
        return False
    filename = url_path.removeprefix(prefix)
    try:
        chart_dir = _chart_dir(app_state, record).resolve(strict=True)
        chart_path = (chart_dir / filename).resolve(strict=True)
        chart_path.relative_to(chart_dir)
    except (OSError, ValueError):
        return False
    return chart_path.is_file()


def _materialize_existing_chart_artifacts(
    app_state: AppState,
    record: AnalysisRecord,
    charts: list[AnalysisChart],
) -> list[AnalysisChart]:
    materialized: list[AnalysisChart] = []
    chart_dir = _chart_dir(app_state, record)

    for index, chart in enumerate(charts):
        if _backend_chart_file_exists(app_state, record, chart):
            materialized.append(chart)
            continue

        source_file = _workspace_chart_file(app_state, chart)
        if source_file is None:
            continue

        suffix = source_file.suffix.lower()
        filename = f"{record.request_id}-provided-{index + 1}{suffix}"
        target = chart_dir / filename
        target.write_bytes(source_file.read_bytes())
        materialized.append(
            AnalysisChart(
                title=chart.title,
                url=_chart_url(app_state, record, filename),
                caption=chart.caption,
                alt_text=chart.alt_text,
                include_in_comment=chart.include_in_comment,
                include_on_page=chart.include_on_page,
            )
        )

    return materialized[:2]


class _ImageTagParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.images: list[dict[str, str]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag.lower() != "img":
            return
        image_attrs = {
            name.lower(): value or ""
            for name, value in attrs
            if isinstance(name, str)
        }
        if image_attrs.get("src"):
            self.images.append(image_attrs)


def _image_sources_from_html(raw_html: str) -> list[dict[str, str]]:
    parser = _ImageTagParser()
    try:
        parser.feed(raw_html)
    except Exception:
        LOGGER.debug(
            "Could not parse notebook HTML image output", exc_info=True
        )
        return []
    return parser.images


def _image_title(attrs: dict[str, str], fallback_index: int) -> str:
    for key in ("alt", "title"):
        value = attrs.get(key, "").strip()
        if value:
            return value
    src = attrs.get("src", "").strip()
    name = Path(_chart_url_path(src)).name
    if name:
        stem = (
            re.sub(r"^\d+-", "", Path(name).stem)
            .replace("-", " ")
            .replace("_", " ")
        )
        if stem:
            return stem[:80]
    return f"Notebook image {fallback_index}"


def _decode_image_data_url(value: str) -> tuple[bytes, str] | None:
    if not value.startswith("data:") or "," not in value:
        return None
    header, payload = value.split(",", 1)
    metadata = header.removeprefix("data:")
    content_type = metadata.split(";", 1)[0] or "image/png"
    if not content_type.startswith("image/"):
        return None
    try:
        if ";base64" in metadata.lower():
            return base64.b64decode(payload), content_type
        return unquote_to_bytes(payload), content_type
    except Exception:
        LOGGER.debug("Could not decode notebook image data URL", exc_info=True)
        return None


def _virtual_file_parts(src: str) -> tuple[str, int] | None:
    path = _chart_url_path(src).removeprefix("./").lstrip("/")
    if not path.startswith("@file/"):
        return None
    remainder = path.removeprefix("@file/")
    if "-" not in remainder:
        return None
    byte_length_raw, filename = remainder.split("-", 1)
    try:
        byte_length = int(byte_length_raw)
    except ValueError:
        return None
    filename = unquote(filename)
    if not filename or byte_length <= 0:
        return None
    return filename, byte_length


def _image_bytes_from_src(
    app_state: AppState, src: str
) -> tuple[bytes, str] | None:
    src = html.unescape(src).strip()
    if not src:
        return None

    decoded = _decode_image_data_url(src)
    if decoded is not None:
        return decoded

    virtual_file = _virtual_file_parts(src)
    if virtual_file is not None:
        filename, byte_length = virtual_file
        try:
            content = read_virtual_file(filename, byte_length)
        except Exception:
            LOGGER.debug(
                "Could not read notebook virtual image file %s",
                filename,
                exc_info=True,
            )
            return None
        content_type = mimetypes.guess_type(filename)[0] or "image/png"
        if not content_type.startswith("image/"):
            return None
        return content, content_type

    source_file = _workspace_file_from_url(app_state, src)
    if source_file is None:
        return None
    content_type = mimetypes.guess_type(source_file.name)[0] or "image/png"
    if not content_type.startswith("image/"):
        return None
    try:
        return source_file.read_bytes(), content_type
    except OSError:
        LOGGER.debug(
            "Could not read notebook workspace image file %s",
            source_file,
            exc_info=True,
        )
        return None


def _image_candidates_from_output_data(
    app_state: AppState,
    cell_id: str,
    data: dict[str, Any],
) -> list[_ImageChartCandidate]:
    candidates: list[_ImageChartCandidate] = []
    for mimetype, value in data.items():
        if not isinstance(mimetype, str):
            continue
        if mimetype == "application/vnd.sp+mimebundle":
            mimebundle = _load_sp_mimebundle(value)
            if mimebundle is not None:
                candidates.extend(
                    _image_candidates_from_output_data(
                        app_state,
                        cell_id,
                        {
                            key: item
                            for key, item in mimebundle.items()
                            if key != "__metadata__"
                        },
                    )
                )
            continue
        if mimetype.startswith("image/"):
            if isinstance(value, bytes):
                candidates.append(
                    _ImageChartCandidate(
                        cell_id=cell_id,
                        title=f"Notebook image {len(candidates) + 1}",
                        content_type=mimetype,
                        content=value,
                    )
                )
            elif isinstance(value, str):
                decoded = _decode_image_data_url(value)
                if decoded is not None:
                    content, content_type = decoded
                else:
                    try:
                        content = base64.b64decode(value)
                    except Exception:
                        continue
                    content_type = mimetype
                candidates.append(
                    _ImageChartCandidate(
                        cell_id=cell_id,
                        title=f"Notebook image {len(candidates) + 1}",
                        content_type=content_type,
                        content=content,
                    )
                )
            continue

        if mimetype != "text/html" or not isinstance(value, str):
            continue
        for attrs in _image_sources_from_html(value):
            resolved = _image_bytes_from_src(app_state, attrs.get("src", ""))
            if resolved is None:
                continue
            content, content_type = resolved
            candidates.append(
                _ImageChartCandidate(
                    cell_id=cell_id,
                    title=_image_title(attrs, len(candidates) + 1),
                    content_type=content_type,
                    content=content,
                )
            )
    return candidates


def _load_sp_mimebundle(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _safe_chart_cell_id(cell_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", cell_id).strip("-")
    return cleaned[:64] or "cell"


def _write_image_chart_artifacts(
    app_state: AppState,
    record: AnalysisRecord,
    output_data: list[tuple[str, dict[str, Any]]],
) -> list[AnalysisChart]:
    chart_dir = _chart_dir(app_state, record)
    charts: list[AnalysisChart] = []
    for cell_id, data in output_data:
        for candidate in _image_candidates_from_output_data(
            app_state, cell_id, data
        ):
            extension = _chart_filename_extension(candidate.content_type)
            filename = (
                f"{record.request_id}-{_safe_chart_cell_id(candidate.cell_id)}"
                f"-image-{len(charts) + 1}.{extension}"
            )
            (chart_dir / filename).write_bytes(candidate.content)
            title = candidate.title or f"Notebook image {len(charts) + 1}"
            charts.append(
                AnalysisChart(
                    title=title,
                    url=_chart_url(app_state, record, filename),
                    caption=title,
                    alt_text=title,
                    include_in_comment=True,
                    include_on_page=True,
                )
            )
            if len(charts) >= 2:
                return charts
    return charts


def _chart_identity(chart: AnalysisChart) -> str:
    return chart.url.strip() or chart.title.strip()


def _merge_chart_lists(
    *chart_lists: list[AnalysisChart],
    limit: int = 2,
) -> list[AnalysisChart]:
    merged: list[AnalysisChart] = []
    seen: set[str] = set()
    for charts in chart_lists:
        for chart in charts:
            key = _chart_identity(chart)
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(chart)
            if len(merged) >= limit:
                return merged
    return merged


_PLOTLY_FIGURE_ATTR_RE = re.compile(
    r"<sp-plotly\b[^>]*\bdata-figure=(['\"])(.*?)\1",
    re.IGNORECASE | re.DOTALL,
)


def _decode_plotly_typed_array(value: Any) -> list[float] | None:
    if not isinstance(value, dict):
        return None
    dtype = value.get("dtype")
    bdata = value.get("bdata")
    if not isinstance(dtype, str) or not isinstance(bdata, str):
        return None

    try:
        raw = base64.b64decode(bdata)
    except Exception:
        return None

    formats = {
        "f8": "d",
        "f4": "f",
        "i4": "i",
        "u4": "I",
        "i2": "h",
        "u2": "H",
        "i1": "b",
        "u1": "B",
    }
    fmt = formats.get(dtype)
    if fmt is None:
        return None
    size = struct.calcsize(fmt)
    if size == 0 or len(raw) % size != 0:
        return None
    count = len(raw) // size
    return [float(item) for item in struct.unpack("<" + fmt * count, raw)]


def _as_list(value: Any) -> list[Any]:
    decoded = _decode_plotly_typed_array(value)
    if decoded is not None:
        return decoded
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value is None:
        return []
    return [value]


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _plotly_marker_color(value: Any, index: int, default: str) -> str:
    if isinstance(value, list | tuple):
        value = value[index] if index < len(value) else default
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _svg_text(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _plotly_title(fig: dict[str, Any], fallback: str) -> str:
    layout = fig.get("layout")
    if isinstance(layout, dict):
        title = layout.get("title")
        if isinstance(title, dict) and title.get("text"):
            return str(title["text"])
        if isinstance(title, str):
            return title
    return fallback


def _plotly_figures_from_html(raw_html: str) -> list[dict[str, Any]]:
    figures: list[dict[str, Any]] = []
    for match in _PLOTLY_FIGURE_ATTR_RE.finditer(raw_html):
        encoded = match.group(2)
        try:
            figure = json.loads(html.unescape(encoded))
        except Exception:
            continue
        if isinstance(figure, dict) and isinstance(figure.get("data"), list):
            figures.append(figure)
    return figures


def _render_plotly_bar_svg(
    fig: dict[str, Any], title: str, theme: ChartTheme | None = None
) -> str | None:
    theme = theme or DEFAULT_CHART_THEME
    traces = [
        trace
        for trace in cast(list[dict[str, Any]], fig.get("data", []))
        if isinstance(trace, dict) and trace.get("type") == "bar"
    ]
    if not traces:
        return None

    width = 900
    height = 560
    margin_left = 230
    margin_right = 60
    margin_top = 82
    margin_bottom = 70
    colors = theme.series
    font_family = _svg_text(theme.font_family)
    orientation = traces[0].get("orientation")

    if orientation == "h":
        categories: list[str] = []
        series: list[tuple[str, dict[str, float], dict[str, str], str]] = []
        single_trace = len(traces) == 1
        for index, trace in enumerate(traces):
            label = str(trace.get("name") or f"Series {index + 1}")
            ys = [str(item) for item in _as_list(trace.get("y"))]
            xs = [_as_float(item) for item in _as_list(trace.get("x"))]
            marker_color = (
                trace.get("marker", {}).get("color")
                if isinstance(trace.get("marker"), dict)
                else None
            )
            default_color = colors[index % len(colors)]
            rank_colors = ranked_series_colors(xs, colors) if single_trace and marker_color is None else []
            values: dict[str, float] = {}
            category_colors: dict[str, str] = {}
            for item_index, (cat, val) in enumerate(zip(ys, xs, strict=False)):
                if cat not in categories:
                    categories.append(cat)
                values[cat] = val
                category_colors[cat] = (
                    rank_colors[item_index]
                    if rank_colors
                    else _plotly_marker_color(marker_color, item_index, default_color)
                )
            series.append((label, values, category_colors, default_color))

        totals = [
            sum(values.get(cat, 0.0) for _, values, _, _ in series)
            for cat in categories
        ]
        max_total = max(max(totals or [1.0]), 1.0)
        plot_width = width - margin_left - margin_right
        row_height = min(
            62, (height - margin_top - margin_bottom) / max(len(categories), 1)
        )
        svg: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            f'<rect width="100%" height="100%" fill="{_svg_text(theme.bg)}"/>',
            f'<text x="{width / 2}" y="36" text-anchor="middle" font-family="{font_family}" font-size="24" font-weight="700" fill="{_svg_text(theme.text)}">{_svg_text(title)}</text>',
        ]
        for i in range(6):
            x = margin_left + plot_width * i / 5
            svg.append(
                f'<line x1="{x:.1f}" y1="{margin_top - 10}" x2="{x:.1f}" y2="{height - margin_bottom + 8}" stroke="{_svg_text(theme.grid)}" stroke-width="1"/>'
            )
            svg.append(
                f'<text x="{x:.1f}" y="{height - margin_bottom + 32}" text-anchor="middle" font-family="{font_family}" font-size="12" fill="{_svg_text(theme.axis)}">{max_total * i / 5:.0f}</text>'
            )
        for row, cat in enumerate(categories):
            y = margin_top + row * row_height
            svg.append(
                f'<text x="{margin_left - 14}" y="{y + row_height / 2 + 5:.1f}" text-anchor="end" font-family="{font_family}" font-size="13" fill="{_svg_text(theme.text)}">{_svg_text(cat)}</text>'
            )
            x_cursor = margin_left
            for _, values, category_colors, default_color in series:
                value = values.get(cat, 0.0)
                color = category_colors.get(cat, default_color)
                bar_width = max(plot_width * value / max_total, 2.0) if value != 0 else 0.0
                svg.append(
                    f'<rect x="{x_cursor:.1f}" y="{y + 10:.1f}" width="{bar_width:.1f}" height="{max(row_height - 20, 8):.1f}" rx="4" fill="{_svg_text(color)}"/>'
                )
                if bar_width > 32:
                    svg.append(
                        f'<text x="{x_cursor + bar_width / 2:.1f}" y="{y + row_height / 2 + 5:.1f}" text-anchor="middle" font-family="{font_family}" font-size="12" fill="{_svg_text(contrast_text(color))}">{value:.0f}</text>'
                    )
                x_cursor += bar_width
        legend_y = height - 22
        legend_x = margin_left
        for label, _, _, color in series[:5]:
            svg.append(
                f'<rect x="{legend_x}" y="{legend_y - 10}" width="12" height="12" rx="2" fill="{_svg_text(color)}"/>'
            )
            svg.append(
                f'<text x="{legend_x + 18}" y="{legend_y}" font-family="{font_family}" font-size="12" fill="{_svg_text(theme.muted)}">{_svg_text(label)}</text>'
            )
            legend_x += min(180, 28 + len(label) * 7)
        svg.append("</svg>")
        return "".join(svg)

    pending_bars: list[tuple[str, float, str | None]] = []
    for index, trace in enumerate(traces):
        xs = [str(item) for item in _as_list(trace.get("x"))]
        ys = [_as_float(item) for item in _as_list(trace.get("y"))]
        marker_color = (
            trace.get("marker", {}).get("color")
            if isinstance(trace.get("marker"), dict)
            else None
        )
        default_color = colors[index % len(colors)]
        for item_index, (label, value) in enumerate(zip(xs, ys, strict=False)):
            pending_bars.append(
                (
                    label or str(trace.get("name") or ""),
                    value,
                    _plotly_marker_color(marker_color, item_index, default_color)
                    if marker_color is not None
                    else None,
                )
            )
    if not pending_bars:
        return None
    rank_colors = ranked_series_colors([value for _, value, _ in pending_bars], colors)
    bars = [
        (label, value, color or rank_colors[index])
        for index, (label, value, color) in enumerate(pending_bars)
    ]

    plot_width = width - 90 - 40
    plot_height = height - margin_top - 105
    left = 70
    bottom = height - 88
    max_value = max(max([value for _, value, _ in bars] or [1.0]), 1.0)
    bar_gap = 16
    bar_width = max(16, (plot_width - bar_gap * (len(bars) - 1)) / len(bars))
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="100%" height="100%" fill="{_svg_text(theme.bg)}"/>',
        f'<text x="{width / 2}" y="36" text-anchor="middle" font-family="{font_family}" font-size="24" font-weight="700" fill="{_svg_text(theme.text)}">{_svg_text(title)}</text>',
    ]
    for i in range(6):
        y = bottom - plot_height * i / 5
        svg.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" y2="{y:.1f}" stroke="{_svg_text(theme.grid)}" stroke-width="1"/>'
        )
        svg.append(
            f'<text x="{left - 12}" y="{y + 4:.1f}" text-anchor="end" font-family="{font_family}" font-size="12" fill="{_svg_text(theme.axis)}">{max_value * i / 5:.0f}</text>'
        )
    for index, (label, value, color) in enumerate(bars):
        x = left + index * (bar_width + bar_gap)
        h = max(plot_height * value / max_value, 2.0) if value > 0 else 0.0
        svg.append(
            f'<rect x="{x:.1f}" y="{bottom - h:.1f}" width="{bar_width:.1f}" height="{h:.1f}" rx="6" fill="{_svg_text(color)}"/>'
        )
        svg.append(
            f'<text x="{x + bar_width / 2:.1f}" y="{bottom - h - 8:.1f}" text-anchor="middle" font-family="{font_family}" font-size="13" font-weight="700" fill="{_svg_text(theme.text)}">{value:.1f}</text>'
        )
        svg.append(
            f'<text x="{x + bar_width / 2:.1f}" y="{bottom + 18:.1f}" text-anchor="middle" font-family="{font_family}" font-size="11" fill="{_svg_text(theme.muted)}">{_svg_text(label[:18])}</text>'
        )
    svg.append("</svg>")
    return "".join(svg)


def _render_plotly_radar_svg(
    fig: dict[str, Any], title: str, theme: ChartTheme | None = None
) -> str | None:
    theme = theme or DEFAULT_CHART_THEME
    traces = [
        trace
        for trace in cast(list[dict[str, Any]], fig.get("data", []))
        if isinstance(trace, dict) and trace.get("type") == "scatterpolar"
    ]
    if not traces:
        return None

    width = 900
    height = 640
    cx = 390
    cy = 345
    radius = 210
    colors = theme.series
    font_family = _svg_text(theme.font_family)
    first_theta = [str(item) for item in _as_list(traces[0].get("theta"))]
    categories = (
        first_theta[:-1]
        if len(first_theta) > 1 and first_theta[0] == first_theta[-1]
        else first_theta
    )
    if not categories:
        return None

    def point(index: int, value: float) -> tuple[float, float]:
        angle = -math.pi / 2 + 2 * math.pi * index / len(categories)
        r = radius * max(0.0, min(value, 100.0)) / 100.0
        return cx + r * math.cos(angle), cy + r * math.sin(angle)

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="100%" height="100%" fill="{_svg_text(theme.bg)}"/>',
        f'<text x="{width / 2}" y="38" text-anchor="middle" font-family="{font_family}" font-size="24" font-weight="700" fill="{_svg_text(theme.text)}">{_svg_text(title)}</text>',
    ]
    for pct in [20, 40, 60, 80, 100]:
        points = " ".join(
            f"{point(i, pct)[0]:.1f},{point(i, pct)[1]:.1f}"
            for i in range(len(categories))
        )
        svg.append(
            f'<polygon points="{points}" fill="none" stroke="{_svg_text(theme.grid)}" stroke-width="1"/>'
        )
    for i, category in enumerate(categories):
        x, y = point(i, 108)
        ax, ay = point(i, 100)
        svg.append(
            f'<line x1="{cx}" y1="{cy}" x2="{ax:.1f}" y2="{ay:.1f}" stroke="{_svg_text(theme.grid)}" stroke-width="1"/>'
        )
        svg.append(
            f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="middle" font-family="{font_family}" font-size="12" fill="{_svg_text(theme.muted)}">{_svg_text(category).replace("&#x27;", "&apos;")}</text>'
        )
    for index, trace in enumerate(traces[:5]):
        values = [_as_float(item) for item in _as_list(trace.get("r"))]
        if len(values) > len(categories):
            values = values[: len(categories)]
        if len(values) < len(categories):
            continue
        color = (
            trace.get("line", {}).get("color")
            if isinstance(trace.get("line"), dict)
            else None
        ) or colors[index % len(colors)]
        points = " ".join(
            f"{point(i, values[i])[0]:.1f},{point(i, values[i])[1]:.1f}"
            for i in range(len(categories))
        )
        svg.append(
            f'<polygon points="{points}" fill="{_svg_text(str(color))}" fill-opacity="0.14" stroke="{_svg_text(str(color))}" stroke-width="2"/>'
        )
    legend_x = 660
    legend_y = 125
    for index, trace in enumerate(traces[:5]):
        name = str(trace.get("name") or f"Series {index + 1}")
        color = (
            trace.get("line", {}).get("color")
            if isinstance(trace.get("line"), dict)
            else None
        ) or colors[index % len(colors)]
        y = legend_y + index * 26
        svg.append(
            f'<rect x="{legend_x}" y="{y - 11}" width="14" height="14" rx="3" fill="{_svg_text(str(color))}"/>'
        )
        svg.append(
            f'<text x="{legend_x + 22}" y="{y}" font-family="{font_family}" font-size="13" fill="{_svg_text(theme.text)}">{_svg_text(name)}</text>'
        )
    svg.append("</svg>")
    return "".join(svg)


def _render_plotly_svg(
    fig: dict[str, Any], fallback_title: str, theme: ChartTheme | None = None
) -> tuple[str, str] | None:
    title = _plotly_title(fig, fallback_title)
    svg = _render_plotly_radar_svg(fig, title, theme) or _render_plotly_bar_svg(
        fig, title, theme
    )
    if svg is None:
        return None
    return title, svg


def _pil_font(size: int, *, bold: bool = False) -> Any:
    from PIL import ImageFont

    candidates = (
        ["DejaVuSans-Bold.ttf", "Arial Bold.ttf"] if bold else []
    ) + ["DejaVuSans.ttf", "Arial.ttf"]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _png_bytes(image: Any) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _render_plotly_bar_png(
    fig: dict[str, Any], title: str, theme: ChartTheme | None = None
) -> bytes | None:
    from PIL import Image, ImageDraw

    theme = theme or DEFAULT_CHART_THEME

    traces = [
        trace
        for trace in cast(list[dict[str, Any]], fig.get("data", []))
        if isinstance(trace, dict) and trace.get("type") == "bar"
    ]
    if not traces:
        return None

    width = 900
    height = 560
    image = Image.new("RGB", (width, height), theme.bg)
    draw = ImageDraw.Draw(image)
    title_font = _pil_font(24, bold=True)
    label_font = _pil_font(13)
    small_font = _pil_font(12)
    value_font = _pil_font(13, bold=True)
    colors = theme.series

    draw.text(
        (width / 2, 30), title, fill=theme.text, font=title_font, anchor="mm"
    )
    if traces[0].get("orientation") == "h":
        margin_left = 230
        margin_right = 60
        margin_top = 82
        margin_bottom = 70
        categories: list[str] = []
        series: list[tuple[str, dict[str, float], dict[str, str], str]] = []
        single_trace = len(traces) == 1
        for index, trace in enumerate(traces):
            label = str(trace.get("name") or f"Series {index + 1}")
            ys = [str(item) for item in _as_list(trace.get("y"))]
            xs = [_as_float(item) for item in _as_list(trace.get("x"))]
            marker_color = (
                trace.get("marker", {}).get("color")
                if isinstance(trace.get("marker"), dict)
                else None
            )
            default_color = colors[index % len(colors)]
            rank_colors = ranked_series_colors(xs, colors) if single_trace and marker_color is None else []
            values: dict[str, float] = {}
            category_colors: dict[str, str] = {}
            for item_index, (category, value) in enumerate(
                zip(ys, xs, strict=False)
            ):
                if category not in categories:
                    categories.append(category)
                values[category] = value
                category_colors[category] = (
                    rank_colors[item_index]
                    if rank_colors
                    else _plotly_marker_color(marker_color, item_index, default_color)
                )
            series.append((label, values, category_colors, default_color))
        all_values = [
            value for _, values, _, _ in series for value in values.values()
        ]
        min_value = min(0.0, min(all_values or [0.0]))
        max_value = max(0.0, max(all_values or [1.0]))
        value_span = max(max_value - min_value, 1.0)
        plot_width = width - margin_left - margin_right
        zero_x = margin_left + ((0.0 - min_value) / value_span) * plot_width
        row_height = min(
            62, (height - margin_top - margin_bottom) / max(len(categories), 1)
        )
        for i in range(6):
            x = margin_left + plot_width * i / 5
            tick_value = min_value + value_span * i / 5
            draw.line(
                [(x, margin_top - 10), (x, height - margin_bottom + 8)],
                fill=theme.grid,
            )
            draw.text(
                (x, height - margin_bottom + 32),
                f"{tick_value:.1f}",
                fill=theme.axis,
                font=small_font,
                anchor="mm",
            )
        draw.line(
            [(zero_x, margin_top - 16), (zero_x, height - margin_bottom + 12)],
            fill=theme.axis,
            width=2,
        )
        for row, category in enumerate(categories):
            y = margin_top + row * row_height
            draw.text(
                (margin_left - 14, y + row_height / 2),
                category,
                fill=theme.text,
                font=label_font,
                anchor="rm",
            )
            slot_height = max(
                14,
                min(28, (row_height - 16) / max(len(series), 1)),
            )
            for series_index, (
                _,
                values,
                category_colors,
                default_color,
            ) in enumerate(series):
                value = values.get(category, 0.0)
                color = category_colors.get(category, default_color)
                raw_width = plot_width * abs(value) / value_span
                bar_width = max(raw_width, 2.0) if value != 0 else 0.0
                x0 = zero_x if value >= 0 else zero_x - bar_width
                x1 = zero_x + bar_width if value >= 0 else zero_x
                y0 = y + 8 + series_index * slot_height
                y1 = min(y0 + slot_height - 4, y + row_height - 8)
                if y1 <= y0:
                    y1 = y0 + 10
                draw.rounded_rectangle(
                    [
                        x0,
                        y0,
                        x1,
                        y1,
                    ],
                    radius=4,
                    fill=color,
                )
                if bar_width > 38:
                    draw.text(
                        ((x0 + x1) / 2, (y0 + y1) / 2),
                        f"{value:.2f}",
                        fill=contrast_text(color),
                        font=small_font,
                        anchor="mm",
                    )
                else:
                    label_x = x1 + 18 if value >= 0 else x0 - 18
                    draw.text(
                        (label_x, (y0 + y1) / 2),
                        f"{value:.2f}",
                        fill=theme.text,
                        font=small_font,
                        anchor="mm",
                    )
        return _png_bytes(image)

    pending_bars: list[tuple[str, float, str | None]] = []
    for index, trace in enumerate(traces):
        xs = [str(item) for item in _as_list(trace.get("x"))]
        ys = [_as_float(item) for item in _as_list(trace.get("y"))]
        marker_color = (
            trace.get("marker", {}).get("color")
            if isinstance(trace.get("marker"), dict)
            else None
        )
        default_color = colors[index % len(colors)]
        for item_index, (label, value) in enumerate(zip(xs, ys, strict=False)):
            pending_bars.append(
                (
                    label or str(trace.get("name") or ""),
                    value,
                    _plotly_marker_color(
                        marker_color, item_index, default_color
                    )
                    if marker_color is not None
                    else None,
                )
            )
    if not pending_bars:
        return None
    rank_colors = ranked_series_colors([value for _, value, _ in pending_bars], colors)
    bars = [
        (label, value, color or rank_colors[index])
        for index, (label, value, color) in enumerate(pending_bars)
    ]

    left = 70
    bottom = height - 88
    plot_width = width - 130
    plot_height = height - 187
    max_value = max(max([value for _, value, _ in bars] or [1.0]), 1.0)
    bar_gap = 16
    bar_width = max(16, (plot_width - bar_gap * (len(bars) - 1)) / len(bars))
    for i in range(6):
        y = bottom - plot_height * i / 5
        draw.line([(left, y), (left + plot_width, y)], fill=theme.grid)
        draw.text(
            (left - 12, y),
            f"{max_value * i / 5:.0f}",
            fill=theme.axis,
            font=small_font,
            anchor="rm",
        )
    for index, (label, value, color) in enumerate(bars):
        x = left + index * (bar_width + bar_gap)
        h = max(plot_height * value / max_value, 2.0) if value > 0 else 0.0
        draw.rounded_rectangle(
            [x, bottom - h, x + bar_width, bottom],
            radius=6,
            fill=color,
        )
        draw.text(
            (x + bar_width / 2, bottom - h - 12),
            f"{value:.1f}",
            fill=theme.text,
            font=value_font,
            anchor="mm",
        )
        draw.text(
            (x + bar_width / 2, bottom + 22),
            label[:18],
            fill=theme.muted,
            font=small_font,
            anchor="mm",
        )
    return _png_bytes(image)


def _render_plotly_radar_png(
    fig: dict[str, Any], title: str, theme: ChartTheme | None = None
) -> bytes | None:
    from PIL import Image, ImageDraw

    theme = theme or DEFAULT_CHART_THEME

    traces = [
        trace
        for trace in cast(list[dict[str, Any]], fig.get("data", []))
        if isinstance(trace, dict) and trace.get("type") == "scatterpolar"
    ]
    if not traces:
        return None

    first_theta = [str(item) for item in _as_list(traces[0].get("theta"))]
    categories = (
        first_theta[:-1]
        if len(first_theta) > 1 and first_theta[0] == first_theta[-1]
        else first_theta
    )
    if not categories:
        return None

    width = 900
    height = 640
    cx = 390
    cy = 345
    radius = 210
    image = Image.new("RGB", (width, height), theme.bg)
    draw = ImageDraw.Draw(image, "RGBA")
    title_font = _pil_font(24, bold=True)
    label_font = _pil_font(12)
    legend_font = _pil_font(13)
    colors = theme.series
    draw.text(
        (width / 2, 38), title, fill=theme.text, font=title_font, anchor="mm"
    )

    def point(index: int, value: float) -> tuple[float, float]:
        angle = -math.pi / 2 + 2 * math.pi * index / len(categories)
        r = radius * max(0.0, min(value, 100.0)) / 100.0
        return cx + r * math.cos(angle), cy + r * math.sin(angle)

    for pct in [20, 40, 60, 80, 100]:
        draw.polygon(
            [point(i, pct) for i in range(len(categories))], outline=theme.grid
        )
    for index, category in enumerate(categories):
        axis_end = point(index, 100)
        label_point = point(index, 108)
        draw.line([(cx, cy), axis_end], fill=theme.grid)
        draw.text(
            label_point, category, fill=theme.muted, font=label_font, anchor="mm"
        )
    for index, trace in enumerate(traces[:5]):
        values = [_as_float(item) for item in _as_list(trace.get("r"))]
        if len(values) > len(categories):
            values = values[: len(categories)]
        if len(values) < len(categories):
            continue
        color = (
            trace.get("line", {}).get("color")
            if isinstance(trace.get("line"), dict)
            else None
        ) or colors[index % len(colors)]
        points = [point(i, values[i]) for i in range(len(categories))]
        draw.polygon(points, fill=color + "24", outline=color)
    for index, trace in enumerate(traces[:5]):
        name = str(trace.get("name") or f"Series {index + 1}")
        color = (
            trace.get("line", {}).get("color")
            if isinstance(trace.get("line"), dict)
            else None
        ) or colors[index % len(colors)]
        y = 125 + index * 26
        draw.rounded_rectangle([660, y - 11, 674, y + 3], radius=3, fill=color)
        draw.text(
            (682, y), name, fill=theme.text, font=legend_font, anchor="lm"
        )
    return _png_bytes(image)


def _render_plotly_png(
    fig: dict[str, Any], fallback_title: str, theme: ChartTheme | None = None
) -> tuple[str, bytes] | None:
    title = _plotly_title(fig, fallback_title)
    png = _render_plotly_radar_png(fig, title, theme) or _render_plotly_bar_png(
        fig, title, theme
    )
    if png is None:
        return None
    return title, png


def _write_plotly_chart_artifacts(
    app_state: AppState,
    record: AnalysisRecord,
    html_outputs: list[tuple[str, str]],
) -> list[AnalysisChart]:
    chart_dir = _chart_dir(app_state, record)
    theme = ChartTheme.from_payload(record.theme)
    charts: list[AnalysisChart] = []
    for cell_id, raw_html in html_outputs:
        for figure in _plotly_figures_from_html(raw_html):
            try:
                rendered = _render_plotly_png(
                    figure, f"Notebook chart {len(charts) + 1}", theme
                )
            except Exception as e:
                LOGGER.warning(
                    "Failed to render Notion chart from cell %s for %s: %s",
                    cell_id,
                    record.request_id,
                    e,
                )
                continue
            if rendered is None:
                continue
            title, png = rendered
            filename = f"{record.request_id}-{cell_id}-{len(charts) + 1}.png"
            (chart_dir / filename).write_bytes(png)
            charts.append(
                AnalysisChart(
                    title=title,
                    url=_chart_url(app_state, record, filename),
                    caption=title,
                    alt_text=f"Chart from notebook cell {cell_id}: {title}",
                    include_in_comment=True,
                    include_on_page=True,
                )
            )
            if len(charts) >= 2:
                return charts
    return charts


def _strip_markdown_cell(value: str) -> str:
    cleaned = re.sub(r"[*_`~]+", "", value)
    cleaned = re.sub(r"<br\s*/?>", " ", cleaned, flags=re.IGNORECASE)
    return html.unescape(cleaned).strip()


def _markdown_table_cells(line: str) -> list[str] | None:
    stripped = line.strip()
    if "|" not in stripped:
        return None
    stripped = stripped.removeprefix("|").removesuffix("|")
    cells = [_strip_markdown_cell(cell) for cell in stripped.split("|")]
    return cells if len(cells) >= 2 else None


def _is_markdown_table_separator(line: str) -> bool:
    cells = _markdown_table_cells(line)
    if not cells:
        return False
    return all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _markdown_tables(
    content: str,
) -> list[tuple[list[str], list[dict[str, str]]]]:
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    tables: list[tuple[list[str], list[dict[str, str]]]] = []
    index = 0
    while index + 1 < len(lines):
        headers = _markdown_table_cells(lines[index])
        if not headers or not _is_markdown_table_separator(lines[index + 1]):
            index += 1
            continue

        rows: list[dict[str, str]] = []
        cursor = index + 2
        while cursor < len(lines):
            cells = _markdown_table_cells(lines[cursor])
            if not cells:
                break
            padded = cells + [""] * (len(headers) - len(cells))
            rows.append(
                dict(zip(headers, padded[: len(headers)], strict=False))
            )
            cursor += 1
        if rows:
            tables.append((headers, rows))
        index = cursor
    return tables


def _metric_value(value: str) -> float | None:
    match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", value)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _normalise(values: list[float]) -> list[float]:
    if not values:
        return []
    minimum = min(values)
    maximum = max(values)
    if maximum == minimum:
        return [50.0 for _ in values]
    return [
        round((value - minimum) / (maximum - minimum) * 100, 1)
        for value in values
    ]


def _find_header(headers: list[str], *keywords: str) -> str | None:
    for header in headers:
        lowered = header.lower()
        if all(keyword.lower() in lowered for keyword in keywords):
            return header
    return None


def _fallback_chart_table(
    record: AnalysisRecord,
) -> tuple[list[str], list[dict[str, str]]] | None:
    if record.result is None:
        return None
    for headers, rows in _markdown_tables(record.result.final_answer):
        if _find_header(headers, "company") and (
            _find_header(headers, "score")
            or _find_header(headers, "composite")
        ):
            return headers, rows
    return None


def _write_result_fallback_chart_artifacts(
    app_state: AppState,
    record: AnalysisRecord,
) -> list[AnalysisChart]:
    table = _fallback_chart_table(record)
    if table is None:
        return []
    headers, rows = table
    company_header = _find_header(headers, "company")
    score_header = _find_header(headers, "score") or _find_header(
        headers, "composite"
    )
    if not company_header or not score_header:
        return []

    parsed_rows = []
    for row in rows:
        company = row.get(company_header, "").strip()
        score = _metric_value(row.get(score_header, ""))
        if company and score is not None:
            parsed_rows.append((company, score, row))
    if len(parsed_rows) < 2:
        return []
    parsed_rows.sort(key=lambda item: item[1], reverse=True)

    chart_dir = _chart_dir(app_state, record)
    theme = ChartTheme.from_payload(record.theme)
    charts: list[AnalysisChart] = []

    ranking_figure = {
        "data": [
            {
                "type": "bar",
                "orientation": "h",
                "y": [company for company, _, _ in parsed_rows],
                "x": [score for _, score, _ in parsed_rows],
            }
        ],
        "layout": {"title": {"text": "Operating momentum composite ranking"}},
    }
    ranking_png = _render_plotly_bar_png(
        ranking_figure, "Operating momentum composite ranking", theme
    )
    if ranking_png:
        filename = f"{record.request_id}-fallback-ranking.png"
        (chart_dir / filename).write_bytes(ranking_png)
        winner = parsed_rows[0][0]
        charts.append(
            AnalysisChart(
                title="Operating momentum composite ranking",
                url=_chart_url(app_state, record, filename),
                caption=f"{winner} has the highest composite momentum score.",
                alt_text=(
                    "Horizontal bar chart ranking companies by composite "
                    "operating momentum score."
                ),
                include_in_comment=True,
                include_on_page=True,
            )
        )

    dimension_headers = [
        header
        for header in headers
        if header not in {company_header, score_header}
        and not header.lower().startswith("rank")
    ]
    dimension_headers = dimension_headers[:4]
    dimension_traces = []
    colors = list(theme.series)
    for index, header in enumerate(dimension_headers):
        values: list[float] = []
        for _, _, row in parsed_rows:
            value = _metric_value(row.get(header, ""))
            values.append(value if value is not None else 0.0)
        if not any(value != 0 for value in values):
            continue
        dimension_traces.append(
            {
                "type": "bar",
                "orientation": "h",
                "name": header,
                "y": [company for company, _, _ in parsed_rows],
                "x": _normalise(values),
                "marker": {"color": colors[index % len(colors)]},
            }
        )
    if dimension_traces:
        dimension_figure = {
            "data": dimension_traces,
            "layout": {
                "title": {"text": "Operating momentum dimension breakdown"}
            },
        }
        dimension_png = _render_plotly_bar_png(
            dimension_figure, "Operating momentum dimension breakdown", theme
        )
        if dimension_png:
            filename = f"{record.request_id}-fallback-dimensions.png"
            (chart_dir / filename).write_bytes(dimension_png)
            charts.append(
                AnalysisChart(
                    title="Operating momentum dimension breakdown",
                    url=_chart_url(app_state, record, filename),
                    caption=(
                        "Normalized comparison of the component momentum "
                        "dimensions from the final ranking table."
                    ),
                    alt_text=(
                        "Grouped horizontal bar chart comparing normalized "
                        "momentum dimension scores by company."
                    ),
                    include_in_comment=False,
                    include_on_page=True,
                )
            )

    return charts[:2]


def _html_outputs_from_output_data(
    output_data: list[tuple[str, dict[str, Any]]],
) -> list[tuple[str, str]]:
    html_outputs: list[tuple[str, str]] = []
    for cell_id, data in output_data:
        raw_html = data.get("text/html")
        if isinstance(raw_html, str):
            html_outputs.append((cell_id, raw_html))
        mimebundle = _load_sp_mimebundle(data.get("application/vnd.sp+mimebundle"))
        if mimebundle is None:
            continue
        raw_html = mimebundle.get("text/html")
        if isinstance(raw_html, str):
            html_outputs.append((cell_id, raw_html))
    return html_outputs


def _fallback_chart_artifacts_from_session_cache(
    app_state: AppState, record: AnalysisRecord
) -> list[AnalysisChart]:
    notebook_path = _resolve_notebook_path(app_state, record.notebook_path)
    cache_file = get_session_cache_file(notebook_path)
    if not cache_file.exists():
        return []

    try:
        snapshot = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    output_data: list[tuple[str, dict[str, Any]]] = []
    cells = snapshot.get("cells", [])
    if not isinstance(cells, list):
        return []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        cell_id = str(cell.get("id", "cell"))
        outputs = cell.get("outputs", [])
        if not isinstance(outputs, list):
            continue
        for output in outputs:
            if not isinstance(output, dict):
                continue
            data = output.get("data")
            if not isinstance(data, dict):
                continue
            output_data.append((cell_id, data))
    plotly_charts = _write_plotly_chart_artifacts(
        app_state, record, _html_outputs_from_output_data(output_data)
    )
    image_charts = _write_image_chart_artifacts(app_state, record, output_data)
    return _merge_chart_lists(plotly_charts, image_charts)


def _fallback_chart_artifacts_from_session(
    app_state: AppState, record: AnalysisRecord
) -> list[AnalysisChart]:
    session = app_state.session_manager.get_session(
        SessionId(record.session_id)
    )
    if session is None:
        return _fallback_chart_artifacts_from_session_cache(app_state, record)

    output_data: list[tuple[str, dict[str, Any]]] = []
    for cell_id in session.document.cell_ids:
        notification = session.session_view.cell_notifications.get(cell_id)
        output = notification.output if notification is not None else None
        if not isinstance(output, CellOutput):
            continue
        output_data.append((str(cell_id), {output.mimetype: output.data}))
    plotly_charts = _write_plotly_chart_artifacts(
        app_state, record, _html_outputs_from_output_data(output_data)
    )
    image_charts = _write_image_chart_artifacts(app_state, record, output_data)
    charts = _merge_chart_lists(plotly_charts, image_charts)
    if len(charts) >= 2:
        return charts
    cache_charts = _fallback_chart_artifacts_from_session_cache(app_state, record)
    return _merge_chart_lists(charts, cache_charts)


def _ensure_notion_chart_artifacts(
    app_state: AppState, record: AnalysisRecord
) -> None:
    if record.result is None:
        return
    existing_charts = [
        chart
        for chart in (record.result.notion_charts or [])
        if chart.url.strip()
    ]
    materialized = _materialize_existing_chart_artifacts(app_state, record, existing_charts)
    session_charts = _fallback_chart_artifacts_from_session(app_state, record)
    charts = _merge_chart_lists(materialized, session_charts)
    if len(charts) < 2:
        result_charts = _write_result_fallback_chart_artifacts(app_state, record)
        charts = _merge_chart_lists(charts, result_charts)
    if len(charts) < 2:
        external_charts = [
            chart
            for chart in existing_charts
            if urlparse(chart.url).scheme in {"http", "https"}
        ]
        charts = _merge_chart_lists(charts, external_charts)
    record.result.notion_charts = charts


def _persist_record_completion_artifacts(
    app_state: AppState,
    record: AnalysisRecord,
    *,
    checkpoint: bool = True,
) -> None:
    try:
        cache_path = _persist_record_session_cache(app_state, record)
        if cache_path is not None:
            LOGGER.info(
                "Persisted Notion analysis session cache %s for %s",
                cache_path,
                record.request_id,
            )
    except Exception as e:
        LOGGER.warning(
            "Failed to persist Notion analysis session cache for %s: %s",
            record.request_id,
            e,
        )

    try:
        _ensure_notion_chart_artifacts(app_state, record)
    except Exception as e:
        LOGGER.warning(
            "Failed to generate Notion analysis chart artifacts for %s: %s",
            record.request_id,
            e,
        )

    _save_registry(app_state)
    if checkpoint:
        _checkpoint_analysis_files(
            app_state,
            record,
            f"Checkpoint {record.source} analysis {record.request_id}",
            include_parent_dir=True,
        )


async def _run_analysis(
    app_state: AppState,
    record: AnalysisRecord,
    body: StartNotionAnalysisRequest,
    *,
    new_chat: bool,
    allow_resume_session: bool = True,
    checkpoint_completion: bool = True,
) -> None:
    from signalpilot._server.ai.chat_store import (
        ChatThread,
        get_gateway_chat_trace_store,
    )
    from signalpilot._server.ai.claude_agent import (
        buffer_event,
        clear_event_buffer,
        run_notebook_agent,
        stop_agent,
    )

    record.status = "Analyzing"
    record.error = None
    _save_registry(app_state)
    _ensure_session(app_state, record, allow_resume=allow_resume_session)
    project_root = _project_root(app_state)
    agent_cwd = str(project_root)
    LOGGER.info(
        "Starting %s analysis %s session=%s notebook=%s cwd=%s",
        record.source,
        record.request_id,
        record.session_id,
        record.notebook_path,
        agent_cwd,
    )

    warm_context = _build_analysis_warm_context(
        app_state,
        body,
        project_root=project_root,
    )
    prompt = _analysis_prompt(
        record,
        body,
        warm_context=warm_context,
        output_mode=record.output_mode,
    )
    text_parts: list[str] = []
    store = get_gateway_chat_trace_store()

    async def append_trace_event(event_data: dict[str, Any]) -> int:
        buffer_event(
            record.session_id,
            event_data,
            thread_id=record.session_id,
        )
        return await store.append_event(record.session_id, event_data)

    await store.upsert_thread(
        ChatThread(
            thread_id=record.session_id,
            session_id=record.session_id,
            source=record.source,
            title=record.headline,
            status="active",
            notebook_path=record.notebook_path,
            notion_request_page_id=record.notion_request_page_id,
            notion_discussion_id=record.discussion_id,
            metadata={
                "request_id": record.request_id,
                "source_url": record.source_url,
                "created_at": record.created_at,
            },
        )
    )
    try:
        clear_event_buffer(record.session_id, thread_id=record.session_id)
        await store.clear_events(record.session_id)
        await append_trace_event(
            {
                "type": "user",
                "role": "user",
                "content": body.prompt,
                "tool_name": "",
                "tool_input": None,
                "tool_call_id": "",
                "is_error": False,
                "cost_usd": None,
                "turn": 0,
                "metadata": {
                    "request_id": record.request_id,
                    "status": record.status,
                    "result": asdict(record.result) if record.result else None,
                },
            },
        )

        async def stream_agent_once(agent_message: str, *, new_chat_for_run: bool) -> None:
            async with asyncio.timeout(_agent_timeout_seconds()):
                async for event in run_notebook_agent(
                    message=agent_message,
                    session_id=SessionId(record.session_id),
                    model=_analysis_agent_model(),
                    new_chat=new_chat_for_run,
                    thread_id=record.session_id,
                    notebook_mcp_app=app_state.request.app,
                    cwd=agent_cwd,
                    disallow_file_edits=True,
                    additional_disallowed_tools=["Agent"],
                ):
                    event_data = {
                        "type": event.type,
                        "content": event.content,
                        "tool_name": event.tool_name,
                        "tool_input": event.tool_input,
                        "tool_call_id": event.tool_call_id,
                        "is_error": event.is_error,
                        "cost_usd": event.cost_usd,
                        "turn": event.turn,
                    }
                    await append_trace_event(event_data)
                    if event.type in ("text", "text_delta") and event.content:
                        text_parts.append(event.content)
                    if event.type == "error":
                        if event.content:
                            text_parts.append(event.content)
                        raise RuntimeError(event.content or "Agent failed")

        try:
            try:
                await stream_agent_once(prompt, new_chat_for_run=new_chat)
            except RuntimeError as exc:
                if not _is_transient_agent_overload(str(exc)):
                    raise
        except TimeoutError:
            stop_agent(record.session_id)
            timeout_seconds = _agent_timeout_seconds()
            record.result = _timeout_failure_result(timeout_seconds)
            record.status = "Done"
            record.error = None
            await append_trace_event(
                {
                    "type": "error",
                    "content": (
                        "Notebook agent timed out after "
                        f"{timeout_seconds:.0f} seconds."
                    ),
                    "tool_name": "",
                    "tool_input": None,
                    "tool_call_id": "",
                    "is_error": True,
                    "cost_usd": None,
                    "turn": 0,
                    "metadata": {
                        "request_id": record.request_id,
                        "status": record.status,
                    },
                },
            )
            _persist_record_completion_artifacts(app_state, record, checkpoint=checkpoint_completion)
            await store.upsert_thread(
                ChatThread(
                    thread_id=record.session_id,
                    session_id=record.session_id,
                    source=record.source,
                    title=record.headline,
                    status="done",
                    notebook_path=record.notebook_path,
                    notion_request_page_id=record.notion_request_page_id,
                    notion_discussion_id=record.discussion_id,
                )
            )
            await append_trace_event(
                {
                    "type": "done",
                    "content": "",
                    "tool_name": "",
                    "tool_input": None,
                    "tool_call_id": "",
                    "is_error": False,
                    "cost_usd": None,
                    "turn": 0,
                    "metadata": {
                        "request_id": record.request_id,
                        "status": record.status,
                        "result": asdict(record.result),
                    },
                },
            )
            return

        try:
            record.result = _parse_final_statement_result("".join(text_parts))
        except Exception:
            if not _is_transient_agent_overload("".join(text_parts)):
                raise
            LOGGER.warning(
                "Retrying %s analysis %s after transient model overload",
                record.source,
                record.request_id,
            )
            await append_trace_event(
                {
                    "type": "text",
                    "content": "Transient model overload detected. Retrying the analysis once.",
                    "tool_name": "",
                    "tool_input": None,
                    "tool_call_id": "",
                    "is_error": False,
                    "cost_usd": None,
                    "turn": 0,
                    "metadata": {
                        "request_id": record.request_id,
                        "status": record.status,
                    },
                },
            )
            text_parts.clear()
            await stream_agent_once(
                _agent_overload_retry_prompt(body.prompt),
                new_chat_for_run=False,
            )
            record.result = _parse_final_statement_result("".join(text_parts))
        record.status = "Done"
        record.error = None
        _persist_record_completion_artifacts(app_state, record, checkpoint=checkpoint_completion)
        await store.upsert_thread(
            ChatThread(
                thread_id=record.session_id,
                session_id=record.session_id,
                source=record.source,
                title=record.headline,
                status="done",
                notebook_path=record.notebook_path,
                notion_request_page_id=record.notion_request_page_id,
                notion_discussion_id=record.discussion_id,
            )
        )
        await append_trace_event(
            {
                "type": "done",
                "content": "",
                "tool_name": "",
                "tool_input": None,
                "tool_call_id": "",
                "is_error": False,
                "cost_usd": None,
                "turn": 0,
                "metadata": {
                    "request_id": record.request_id,
                    "status": record.status,
                    "result": asdict(record.result) if record.result else None,
                },
            },
        )
    except Exception as e:
        LOGGER.exception("Notion analysis %s failed", record.request_id)
        failed = False
        try:
            record.result = _parse_final_statement_result("".join(text_parts))
            record.status = "Done"
            record.error = None
        except Exception:
            if "".join(text_parts).strip():
                if _is_transient_agent_overload("".join(text_parts)):
                    failed = True
                    record.status = "Failed"
                    record.error = (
                        "The analysis model returned a transient overload response. "
                        "Please retry the request."
                    )
                else:
                    record.result = _plain_text_failure_result(
                        "".join(text_parts), e
                    )
                    record.status = "Done"
                    record.error = None
            else:
                failed = True
                record.status = "Failed"
                record.error = str(e)
        _persist_record_completion_artifacts(app_state, record, checkpoint=checkpoint_completion)
        if failed:
            await store.upsert_thread(
                ChatThread(
                    thread_id=record.session_id,
                    session_id=record.session_id,
                    source=record.source,
                    title=record.headline,
                    status="failed",
                    notebook_path=record.notebook_path,
                    notion_request_page_id=record.notion_request_page_id,
                    notion_discussion_id=record.discussion_id,
                )
            )
            await append_trace_event(
                {
                    "type": "error",
                    "content": str(e),
                    "tool_name": "",
                    "tool_input": None,
                    "tool_call_id": "",
                    "is_error": True,
                    "cost_usd": None,
                    "turn": 0,
                    "metadata": {
                        "request_id": record.request_id,
                        "status": record.status,
                    },
                },
            )
        else:
            await store.upsert_thread(
                ChatThread(
                    thread_id=record.session_id,
                    session_id=record.session_id,
                    source=record.source,
                    title=record.headline,
                    status="done",
                    notebook_path=record.notebook_path,
                    notion_request_page_id=record.notion_request_page_id,
                    notion_discussion_id=record.discussion_id,
                )
            )
            await append_trace_event(
                {
                    "type": "done",
                    "content": "",
                    "tool_name": "",
                    "tool_input": None,
                    "tool_call_id": "",
                    "is_error": False,
                    "cost_usd": None,
                    "turn": 0,
                    "metadata": {
                        "request_id": record.request_id,
                        "status": record.status,
                        "result": asdict(record.result)
                        if record.result
                        else None,
                    },
                },
            )
    finally:
        _save_registry(app_state)
        _running_tasks.pop(record.request_id, None)


def _record_response(record: AnalysisRecord, app_state: AppState | None = None) -> dict[str, Any]:
    result = record.result or AnalysisResult()
    response = {
        "requestId": record.request_id,
        "source": record.source,
        "outputMode": record.output_mode,
        "sessionId": record.session_id,
        "notebookPath": record.notebook_path,
        "trailUrl": record.trail_url,
        "status": record.status,
        "latestCommitSha": record.latest_commit_sha,
        "summary": result.summary,
        "confidenceScore": result.confidence_score,
        "finalAnswer": result.final_answer,
        "gotchas": result.gotchas or [],
        "analysisMethod": result.analysis_method,
        "notionComment": result.notion_comment,
        "notionCharts": [
            {
                "title": chart.title,
                "url": chart.url,
                "caption": chart.caption,
                "altText": chart.alt_text,
                "includeInComment": chart.include_in_comment,
                "includeOnPage": chart.include_on_page,
            }
            for chart in (result.notion_charts or [])
        ],
        "dataSnapshots": [
            {
                "name": snapshot.name,
                "description": snapshot.description,
                "columns": snapshot.columns or [],
                "rowCount": snapshot.row_count,
                "filename": snapshot.filename,
                "url": snapshot.url,
                "bytes": snapshot.bytes,
            }
            for snapshot in (record.data_snapshots or [])
        ],
        "error": record.error,
    }
    notebook_code = _record_notebook_code_for_response(record, app_state)
    if notebook_code is not None:
        response["notebookCode"] = notebook_code
        response["notebookCodeSha256"] = hashlib.sha256(notebook_code.encode("utf-8")).hexdigest()
    return response


def _record_notebook_code_for_response(record: AnalysisRecord, app_state: AppState | None) -> str | None:
    if record.output_mode != "deliverable" or record.status != "Done":
        return None
    try:
        path = Path(record.notebook_path)
        if not path.is_absolute():
            if app_state is None:
                return None
            path = _resolve_notebook_path(app_state, record.notebook_path)
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _mark_stale_analysis_failed(
    app_state: AppState, record: AnalysisRecord
) -> None:
    task = _running_tasks.get(record.request_id)
    if task is not None and task.done():
        _running_tasks.pop(record.request_id, None)

    if record.status != "Analyzing" or record.request_id in _running_tasks:
        return

    record.status = "Failed"
    record.error = "Analysis was interrupted before completion."
    _save_registry(app_state)
    _checkpoint_analysis_files(
        app_state,
        record,
        f"Checkpoint {record.source} analysis {record.request_id}",
        include_parent_dir=True,
    )


async def _recover_completed_record_from_trace(
    app_state: AppState, record: AnalysisRecord
) -> bool:
    if record.status != "Analyzing":
        return False
    try:
        from signalpilot._server.ai.chat_store import (
            get_gateway_chat_trace_store,
        )

        store = get_gateway_chat_trace_store()
        thread = await store.get_thread(record.session_id)
        if not isinstance(thread, dict) or thread.get("status") != "done":
            return False
        events = await store.get_events(record.session_id)
        text = "".join(
            str(event.get("content") or "")
            for event in events
            if event.get("type") in ("text", "text_delta")
        )
        record.result = _parse_final_statement_result(text)
        record.status = "Done"
        record.error = None
        _save_registry(app_state)
        return True
    except Exception as exc:
        LOGGER.debug("Could not recover completed analysis from trace: %s", exc)
        return False


@router.post("/start")
async def start_notion_analysis(*, request: Request) -> JSONResponse:
    app_state = AppState(request)
    body = await parse_request(request, cls=StartNotionAnalysisRequest)
    record = _ensure_record(app_state, body, str(request.base_url))

    should_start_new_chat = record.status == "New"
    if record.status != "Analyzing":
        record.status = "Analyzing"
        record.error = None
        _save_registry(app_state)

    if (
        record.status == "Analyzing"
        and record.request_id not in _running_tasks
    ):
        _running_tasks[record.request_id] = asyncio.create_task(
            _run_analysis(
                app_state,
                record,
                body,
                new_chat=should_start_new_chat,
            )
        )

    return JSONResponse(_record_response(record, app_state))


@router.post("/refresh")
async def refresh_notion_analysis(*, request: Request) -> JSONResponse:
    app_state = AppState(request)
    body = await parse_request(request, cls=RefreshNotionAnalysisRequest)
    request_id = _refresh_request_id(body.ephemeral_run_id)
    start_body = _refresh_start_body(body)
    _load_registry(app_state)

    record = _records_by_request_id.get(request_id)
    if record is None:
        notebook_path = _write_refresh_notebook(app_state, body, request_id)
        session_id = str(_session_id(request_id))
        record = AnalysisRecord(
            request_id=request_id,
            discussion_id=start_body.discussion_id,
            session_id=session_id,
            notebook_path=notebook_path,
            trail_url=_record_trail_url(app_state, notebook_path, session_id, str(request.base_url)),
            status="New",
            headline=start_body.headline,
            source_url=start_body.source_url,
            created_at=start_body.created_at,
            source=start_body.source,
            output_mode=_output_mode(start_body.output_mode),
            theme=start_body.theme,
            data_snapshots=[],
        )
        _records_by_request_id[record.request_id] = record
        _records_by_discussion_id[record.discussion_id] = record.request_id
        _save_registry(app_state)
    else:
        _refresh_trail_url(app_state, record, str(request.base_url))

    if record.status != "Analyzing":
        record.status = "Analyzing"
        record.error = None
        _save_registry(app_state)

    if record.request_id not in _running_tasks:
        _running_tasks[record.request_id] = asyncio.create_task(
            _run_analysis(
                app_state,
                record,
                start_body,
                new_chat=True,
                allow_resume_session=False,
                checkpoint_completion=False,
            )
        )

    return JSONResponse(_record_response(record, app_state))


@router.get("/chart/{request_id}/{filename:path}")
async def notion_analysis_chart(*, request: Request) -> FileResponse:
    app_state = AppState(request)
    _load_registry(app_state)
    request_id = request.path_params["request_id"]
    filename = request.path_params["filename"]
    record = _records_by_request_id.get(request_id)
    if record is None:
        chart_path = _chart_file_from_project_registries(
            request_id, filename
        )
        if chart_path is None:
            raise HTTPException(
                status_code=404, detail="Analysis request not found"
            )
    else:
        chart_dir = _chart_dir(app_state, record).resolve(strict=True)
        try:
            chart_path = (chart_dir / filename).resolve(strict=True)
            chart_path.relative_to(chart_dir)
        except (OSError, ValueError):
            raise HTTPException(
                status_code=404, detail="Chart not found"
            ) from None

    media_type = mimetypes.guess_type(chart_path.name)[0] or "image/svg+xml"
    return FileResponse(
        chart_path,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/snapshot/{request_id}/{filename:path}")
async def notion_analysis_snapshot(*, request: Request) -> FileResponse:
    app_state = AppState(request)
    _load_registry(app_state)
    request_id = request.path_params["request_id"]
    filename = request.path_params["filename"]
    record = _records_by_request_id.get(request_id)
    if record is None:
        snapshot_path = _snapshot_file_from_project_registries(
            request_id, filename
        )
        if snapshot_path is None:
            raise HTTPException(
                status_code=404, detail="Analysis request not found"
            )
    else:
        snapshot_dir = _snapshot_dir(app_state, record).resolve(strict=True)
        try:
            snapshot_path = (snapshot_dir / filename).resolve(strict=True)
            snapshot_path.relative_to(snapshot_dir)
        except (OSError, ValueError):
            raise HTTPException(
                status_code=404, detail="Snapshot not found"
            ) from None

    return FileResponse(
        snapshot_path,
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/status/{request_id}")
async def notion_analysis_status(*, request: Request) -> JSONResponse:
    app_state = AppState(request)
    _load_registry(app_state)
    request_id = request.path_params["request_id"]
    record = _records_by_request_id.get(request_id)
    if record is None:
        return JSONResponse(
            {"error": f"Analysis request not found: {request_id}"},
            status_code=404,
        )
    _refresh_trail_url(app_state, record, str(request.base_url))
    _ensure_session(app_state, record)
    await _recover_completed_record_from_trace(app_state, record)
    _mark_stale_analysis_failed(app_state, record)
    if record.status == "Done":
        _persist_record_completion_artifacts(app_state, record)
        _save_registry(app_state)
    return JSONResponse(_record_response(record, app_state))
