"""In-process publication tools for one standalone data-chat run."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from signalpilot._server.ai.standalone_chat_artifacts import (
    StandaloneArtifactCollector,
    StandaloneNotebookLifecycle,
    _clean_metadata,
    _collected_artifact_is_complete,
)
from signalpilot._server.ai.standalone_chat_chart_renderer import (
    _render_chart_png,
)
from signalpilot._server.ai.standalone_chat_chart_theme import (
    prepare_signalpilot_chart,
)
from signalpilot._server.ai.standalone_chat_dbt import run_inspect_dbt
from signalpilot._server.ai.standalone_chat_tool_schemas import (
    standalone_chat_tools,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

# Mirrors the start_analysis_notebook input schema pattern.
_NOTEBOOK_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,40}$")


def build_standalone_chat_mcp_server(
    collector: StandaloneArtifactCollector,
    *,
    result_loader: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
    project_directory: Path | None = None,
    scratch_directory: Path | None = None,
    notebook_mcp_app: Any | None = None,
    analysis_notebook_path: Path | None = None,
    event_sink: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    notebook_lifecycle: StandaloneNotebookLifecycle | None = None,
    runtime_redactions: tuple[str, ...] = (),
    notebook_starter: Callable[[Any, dict[str, Any]], list[Any]] | None = None,
    notebook_session_resolver: Callable[[str], Any] | None = None,
    notebook_seeder: Callable[[str], Path] | None = None,
    report_catalog_loader: Callable[[str | None], Awaitable[dict[str, Any]]]
    | None = None,
    report_context_loader: Callable[[str], Awaitable[dict[str, Any]]]
    | None = None,
    published_artifact_checker: Callable[[str, str], Awaitable[dict[str, Any]]]
    | None = None,
    dashboard_preview_creator: Callable[[str, str, str | None], Awaitable[dict[str, Any]]]
    | None = None,
    attached_report_id: str | None = None,
) -> Any:
    """Build the isolated artifact publication server used by one run."""
    from claude_agent_sdk import McpSdkServerConfig
    from mcp.server import Server
    from mcp.types import TextContent, Tool

    server = Server("standalone-chat", version="1.0.0")
    tools = standalone_chat_tools(notebook_enabled=notebook_mcp_app is not None)
    dashboard_preview_request: tuple[str, str, str | None] | None = None
    dashboard_preview_result: dict[str, Any] | None = None

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return tools

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict[str, Any]
    ) -> list[TextContent]:
        nonlocal dashboard_preview_request, dashboard_preview_result
        try:
            if name == "create_dashboard_preview":
                if dashboard_preview_creator is None:
                    raise ValueError("Dashboard authoring is unavailable")
                request = str(arguments.get("request") or "").strip()
                timezone = str(arguments.get("timezone") or "UTC").strip()
                authoring_session_id = str(arguments.get("authoring_session_id") or "").strip() or None
                if not request or len(request) > 50_000:
                    raise ValueError("A dashboard request is required")
                if not timezone or len(timezone) > 100:
                    raise ValueError("Invalid dashboard timezone")
                request_key = (request, timezone, authoring_session_id)
                if dashboard_preview_result is not None:
                    if request_key != dashboard_preview_request:
                        raise ValueError(
                            "Only one dashboard preview may be created per chat run"
                        )
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(dashboard_preview_result),
                        )
                    ]
                created = await dashboard_preview_creator(request, timezone, authoring_session_id)
                session_id = str(created.get("id") or "").strip()
                if not session_id:
                    raise ValueError("Dashboard authoring returned no preview")
                definition = created.get("definition")
                definition = definition if isinstance(definition, dict) else {}
                charts = definition.get("charts")
                charts = charts if isinstance(charts, list) else []
                plan = created.get("plan")
                plan = plan if isinstance(plan, dict) else {}
                chart_drafts = created.get("chart_drafts")
                chart_drafts = chart_drafts if isinstance(chart_drafts, list) else []
                failed_charts = [
                    {
                        "label": str(
                            ((draft.get("intent") or {}).get("label"))
                            or draft.get("chart_id")
                            or "Chart"
                        ),
                        "error": str(draft.get("safe_error") or "Chart generation failed"),
                    }
                    for draft in chart_drafts
                    if isinstance(draft, dict) and draft.get("status") == "failed"
                ]
                created_status = str(created.get("status") or "preview")
                dashboard_preview_request = request_key
                dashboard_preview_result = {
                    "status": (
                        "partial_failed"
                        if created_status == "partial_failed"
                        else "preview_ready"
                    ),
                    "authoring_session_id": session_id,
                    "preview_url": f"/dashboards/new?authoring={session_id}",
                    "summary": str(created.get("summary") or ""),
                    "dashboard_name": str(
                        definition.get("name")
                        or plan.get("name")
                        or "Dashboard preview"
                    ),
                    "chart_count": len(charts),
                    "chart_titles": [
                        str(chart.get("title") or "Untitled chart")
                        for chart in charts[:12]
                        if isinstance(chart, dict)
                    ],
                    **({"failed_charts": failed_charts} if failed_charts else {}),
                    "requires_review": True,
                    "apply_required": True,
                }
                collector.dashboard_preview = dashboard_preview_result
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(dashboard_preview_result),
                    )
                ]
            if name == "list_saved_report_catalog":
                if report_catalog_loader is None:
                    raise ValueError("The saved report catalog is unavailable")
                cursor = str(arguments.get("cursor") or "") or None
                if cursor is None:
                    collector.report_catalog_revision = None
                    collector.next_report_catalog_cursor = None
                    collector.report_catalog_scan_complete = False
                    collector.proactive_creation_allowed = False
                elif cursor != collector.next_report_catalog_cursor:
                    raise ValueError(
                        "Scan report catalog pages in the returned order"
                    )
                page = await report_catalog_loader(cursor)
                revision = str(page.get("catalog_revision") or "")
                if not revision:
                    raise ValueError(
                        "The saved report catalog returned no revision"
                    )
                if (
                    collector.report_catalog_revision
                    and collector.report_catalog_revision != revision
                ):
                    raise ValueError(
                        "The saved report catalog changed; restart the scan"
                    )
                collector.report_catalog_revision = revision
                collector.next_report_catalog_cursor = (
                    str(page.get("next_cursor") or "") or None
                )
                collector.report_catalog_scan_complete = (
                    collector.next_report_catalog_cursor is None
                )
                collector.proactive_creation_allowed = bool(
                    page.get("proactive_creation_allowed")
                )
                return [TextContent(type="text", text=json.dumps(page))]
            if name == "load_report_context":
                if report_context_loader is None:
                    raise ValueError("Saved report context is unavailable")
                report_id = str(arguments.get("report_id") or "").strip()
                if not report_id:
                    raise ValueError("A report_id is required")
                context = await report_context_loader(report_id)
                collector.loaded_report_ids.add(report_id)
                return [TextContent(type="text", text=json.dumps(context))]
            if name == "propose_report_action":
                if collector.report_action_outcome is not None:
                    raise ValueError(
                        "Only one report action outcome may be recorded per run"
                    )
                action = str(arguments.get("action") or "")
                artifact_kind = str(arguments.get("artifact_kind") or "")
                artifact_filename = str(
                    arguments.get("artifact_filename") or ""
                ).strip()
                existing_report_id = (
                    str(arguments.get("existing_report_id") or "") or None
                )
                local_artifact = next(
                    (
                        artifact
                        for artifact in collector.artifacts
                        if artifact.get("kind") == artifact_kind
                        and artifact.get("filename") == artifact_filename
                    ),
                    None,
                )
                published = {
                    "published": local_artifact is not None,
                    "complete": bool(
                        local_artifact
                        and _collected_artifact_is_complete(local_artifact)
                    ),
                }
                if (
                    local_artifact is None
                    and published_artifact_checker is not None
                ):
                    published = await published_artifact_checker(
                        artifact_kind,
                        artifact_filename,
                    )
                if not published.get("published"):
                    raise ValueError(
                        "Publish the proposed artifact successfully before proposing a report action"
                    )
                if not published.get("complete"):
                    raise ValueError(
                        "Incomplete or truncated artifacts cannot become reports"
                    )
                if not collector.report_catalog_scan_complete:
                    raise ValueError(
                        "Scan every saved report catalog page before recording a report action outcome"
                    )
                if action == "create":
                    if not collector.proactive_creation_allowed:
                        raise ValueError(
                            "Proactive report creation is unavailable for this catalog"
                        )
                    if existing_report_id:
                        raise ValueError(
                            "A create proposal cannot target an existing report"
                        )
                elif action in {"update", "open"}:
                    if not existing_report_id:
                        raise ValueError("An existing_report_id is required")
                    if (
                        action == "update"
                        and existing_report_id != attached_report_id
                        and existing_report_id
                        not in collector.loaded_report_ids
                    ):
                        raise ValueError(
                            "Load the matched report context before proposing an update"
                        )
                elif action == "no_suggestion":
                    if existing_report_id:
                        raise ValueError(
                            "A no-suggestion outcome cannot target an existing report"
                        )
                else:
                    raise ValueError("Unsupported report action")
                outcome = {
                    "action": action,
                    "artifact_kind": artifact_kind,
                    "artifact_filename": artifact_filename,
                    "title": str(arguments.get("title") or "").strip(),
                    "reason": str(arguments.get("reason") or "").strip(),
                    "existing_report_id": existing_report_id,
                    "catalog_revision": collector.report_catalog_revision,
                    "catalog_scan_complete": collector.report_catalog_scan_complete,
                    "proactive_creation_allowed": collector.proactive_creation_allowed,
                    "loaded_report_ids": sorted(collector.loaded_report_ids),
                    "attached_report_id": attached_report_id,
                }
                collector.report_action_outcome = outcome
                if action != "no_suggestion":
                    collector.report_proposal = outcome
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "recorded": True,
                                "proposed": action != "no_suggestion",
                                "action": action,
                            }
                        ),
                    )
                ]
            if name == "start_analysis_notebook":
                if (
                    notebook_mcp_app is None
                    or analysis_notebook_path is None
                ):
                    raise ValueError(
                        "The run-bound analysis notebook is unavailable"
                    )
                notebook_name = str(
                    arguments.get("notebook") or "analysis"
                )
                if not _NOTEBOOK_NAME_RE.fullmatch(notebook_name):
                    raise ValueError("Invalid notebook name")
                if notebook_name == "analysis":
                    target_path = analysis_notebook_path
                else:
                    target_path = (
                        analysis_notebook_path.parent
                        / f"{notebook_name}.py"
                    )
                running_session = (
                    notebook_lifecycle.sessions.get(notebook_name)
                    if notebook_lifecycle is not None
                    else None
                )
                if running_session:
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                {
                                    "session_id": running_session,
                                    "status": "already_running",
                                    "notebook_path": str(target_path),
                                    "notebook": notebook_name,
                                }
                            ),
                        )
                    ]
                if notebook_name != "analysis" and not target_path.is_file():
                    # Named notebooks seed lazily in the SAME scratch.
                    if notebook_seeder is None:
                        raise ValueError(
                            "Named notebooks are unavailable in this run"
                        )
                    target_path = notebook_seeder(notebook_name)
                if notebook_starter is None:
                    from signalpilot._server.ai.notebook_mcp import (
                        _handle_start_notebook_session,
                    )
                    from signalpilot._server.ai.tools.base import ToolContext

                    result = _handle_start_notebook_session(
                        ToolContext(app=notebook_mcp_app),
                        {
                            "file_path": str(target_path),
                            "auto_run": True,
                        },
                    )
                else:
                    result = notebook_starter(
                        notebook_mcp_app,
                        {
                            "file_path": str(target_path),
                            "auto_run": True,
                        },
                    )
                if not result:
                    raise ValueError("Notebook kernel did not start")
                raw = str(getattr(result[0], "text", ""))
                try:
                    started = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        "Notebook kernel returned an invalid response"
                    ) from exc
                session_id = str(started.get("session_id") or "")
                if not session_id or str(
                    started.get("status") or ""
                ).startswith("error"):
                    raise ValueError("Notebook kernel did not start")
                if notebook_lifecycle is not None:
                    notebook_lifecycle.sessions[notebook_name] = session_id
                if notebook_session_resolver is not None:
                    runtime_session = notebook_session_resolver(session_id)
                else:
                    from signalpilot._server.ai.tools.base import ToolContext

                    runtime_session = ToolContext(
                        app=notebook_mcp_app
                    ).get_session(session_id)
                runtime_session._signalpilot_chat_runtime = True
                runtime_session._signalpilot_chat_redactions = (
                    runtime_redactions
                )
                if event_sink is not None:
                    await event_sink(
                        "notebook_started",
                        {
                            "notebook": notebook_name,
                            "session_id": session_id,
                        },
                    )
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "session_id": session_id,
                                "status": "started",
                                "cell_ids": started.get("cell_ids") or [],
                                "notebook_path": str(target_path),
                                "notebook": notebook_name,
                            }
                        ),
                    )
                ]
            if name == "inspect_dbt":
                if project_directory is None or scratch_directory is None:
                    raise ValueError("The frozen dbt project is unavailable")
                inspected = await run_inspect_dbt(
                    project_directory=project_directory,
                    scratch_directory=scratch_directory,
                    arguments=arguments,
                )
                return [
                    TextContent(type="text", text=json.dumps(inspected))
                ]
            metadata = _clean_metadata(arguments)
            loaded_result: dict[str, Any] | None = None
            result_id = str(arguments.get("result_id") or "").strip()
            if name in {"publish_table", "publish_chart"}:
                if not result_id or result_loader is None:
                    raise ValueError(
                        "A governed structured result ID is required"
                    )
                loaded_result = await result_loader(result_id)
                metadata["provenance"] = {
                    **dict(loaded_result.get("provenance") or {}),
                    **metadata["provenance"],
                    "result_id": result_id,
                    "execution_id": loaded_result.get("execution_id"),
                }
            if name == "publish_table":
                assert loaded_result is not None
                source_rows = list(loaded_result.get("rows") or [])
                rows = source_rows
                artifact = {
                    **metadata,
                    "kind": "table",
                    "mime_type": "text/csv",
                    "payload": {
                        "columns": list(loaded_result.get("columns") or []),
                        "rows": rows,
                        "column_descriptions": dict(
                            arguments.get("column_descriptions") or {}
                        ),
                        "query_row_count": loaded_result.get(
                            "query_row_count"
                        ),
                        "saved_row_count": loaded_result.get(
                            "saved_row_count"
                        ),
                        "completeness": loaded_result.get("completeness"),
                        "truncation_reason": loaded_result.get(
                            "truncation_reason"
                        ),
                        "truncated": loaded_result.get("completeness")
                        != "complete",
                    },
                }
            elif name == "publish_chart":
                assert loaded_result is not None
                source_rows = list(loaded_result.get("rows") or [])
                rows = source_rows
                spec, display_rows, display = prepare_signalpilot_chart(
                    dict(arguments.get("spec") or {}),
                    rows,
                )
                columns = [
                    {"name": str(name), "type": "unknown"}
                    for name in (rows[0].keys() if rows else [])
                ]
                truncated = loaded_result.get("completeness") != "complete"
                binary_base64 = _render_chart_png(
                    spec,
                    display_rows,
                    truncated=truncated,
                )
                if not binary_base64:
                    raise ValueError(
                        "Chart publication requires a supported x/y Vega-Lite encoding so a PNG can be generated"
                    )
                artifact = {
                    **metadata,
                    "kind": "chart",
                    "mime_type": "image/png",
                    "payload": {
                        "spec": spec,
                        "rows": display_rows,
                        "source": {
                            "columns": columns,
                            "rows": rows,
                            "truncated": truncated,
                            "completeness": loaded_result.get("completeness"),
                            "truncation_reason": loaded_result.get(
                                "truncation_reason"
                            ),
                        },
                        "display": display,
                        "truncated": truncated,
                    },
                    "binary_base64": binary_base64,
                }
            elif name == "publish_report":
                result_ids = [
                    str(value) for value in arguments.get("result_ids") or []
                ]
                if result_ids and result_loader is None:
                    raise ValueError("Governed result loading is unavailable")
                result_refs = []
                for report_result_id in result_ids:
                    loaded = await result_loader(report_result_id)  # type: ignore[misc]
                    result_refs.append(
                        {
                            "result_id": report_result_id,
                            "execution_id": loaded.get("execution_id"),
                            "completeness": loaded.get("completeness"),
                            "provenance": loaded.get("provenance"),
                        }
                    )
                metadata["provenance"] = {
                    **metadata["provenance"],
                    "result_references": result_refs,
                    "artifact_references": list(
                        arguments.get("artifact_references") or []
                    ),
                }
                artifact = {
                    **metadata,
                    "kind": "report",
                    "mime_type": "text/html",
                    "payload": {"html": str(arguments.get("html") or "")},
                }
            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]
            collector.artifacts.append(artifact)
            complete = _collected_artifact_is_complete(artifact)
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "published": True,
                            "artifact_index": len(collector.artifacts) - 1,
                            "kind": artifact["kind"],
                            "filename": artifact["filename"],
                            **(
                                {
                                    "next_required_action": (
                                        "REQUIRED BEFORE YOUR FINAL ANSWER: scan every page with "
                                        "list_saved_report_catalog, then call propose_report_action exactly once "
                                        "with create, update, open, or no_suggestion."
                                    )
                                }
                                if complete
                                and collector.report_action_outcome is None
                                else {}
                            ),
                        }
                    ),
                )
            ]
        except Exception as exc:
            # Raising lets the MCP protocol mark the tool result as an error.
            # Returning an error-shaped TextContent reports isError=false and
            # makes failed artifact publication look successful to Data Chat.
            raise ValueError(str(exc)) from exc

    return McpSdkServerConfig(
        type="sdk", name="standalone-chat", instance=server
    )
