"""In-process publication and restricted scratch-analysis tools for data chat."""

from __future__ import annotations

import ast
import asyncio
import base64
import io
import json
import math
import statistics
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

from signalpilot._server.ai.standalone_chat_chart_theme import (
    CHART_BACKGROUND,
    CHART_BORDER,
    CHART_COLORS,
    CHART_GRID,
    CHART_MUTED_TEXT,
    CHART_TEXT,
    chart_field,
    chart_mark_type,
    prepare_signalpilot_chart,
)

MAX_PYTHON_SOURCE_CHARS = 12_000


@dataclass
class StandaloneArtifactCollector:
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    report_proposal: dict[str, Any] | None = None
    report_action_outcome: dict[str, Any] | None = None
    report_catalog_revision: str | None = None
    next_report_catalog_cursor: str | None = None
    report_catalog_scan_complete: bool = False
    proactive_creation_allowed: bool = False
    loaded_report_ids: set[str] = field(default_factory=set)


@dataclass
class StandaloneNotebookLifecycle:
    session_id: str | None = None
    plan_id: str | None = None


def _clean_metadata(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "filename": str(arguments.get("filename") or "").strip(),
        "freshness_at": arguments.get("freshness_at"),
        "assumptions": list(arguments.get("assumptions") or []),
        "exclusions": list(arguments.get("exclusions") or []),
        "caveats": list(arguments.get("caveats") or []),
        "provenance": dict(arguments.get("provenance") or {}),
        "parent_artifact_id": arguments.get("parent_artifact_id"),
    }


def _collected_artifact_is_complete(artifact: dict[str, Any]) -> bool:
    if (
        artifact.get("kind") not in {"table", "chart", "report"}
        or not str(artifact.get("filename") or "").strip()
    ):
        return False
    payload = (
        artifact.get("payload")
        if isinstance(artifact.get("payload"), dict)
        else {}
    )
    if artifact.get("kind") == "report":
        references = (artifact.get("provenance") or {}).get(
            "result_references"
        ) or []
        return bool(str(payload.get("html") or "").strip()) and all(
            not isinstance(reference, dict)
            or reference.get("completeness") == "complete"
            for reference in references
        )
    source = (
        payload.get("source") if artifact.get("kind") == "chart" else payload
    )
    return (
        isinstance(source, dict)
        and source.get("truncated") is not True
        and source.get("completeness") in {None, "complete"}
    )


def _render_chart_png(
    spec: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    truncated: bool = False,
) -> str | None:
    if not rows:
        return None
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.ticker import FuncFormatter

        spec, rows, _ = prepare_signalpilot_chart(spec, rows)
        encoding = spec.get("encoding") or {}
        x_field = chart_field(encoding.get("x"))
        y_field = chart_field(encoding.get("y"))
        color_field = chart_field(encoding.get("color"))
        if not x_field or not y_field:
            return None

        mark = chart_mark_type(spec)
        horizontal_bar = (
            mark == "bar"
            and (encoding.get("x") or {}).get("type") == "quantitative"
            and (encoding.get("y") or {}).get("type") != "quantitative"
        )
        figure, axis = plt.subplots(
            figsize=(8, 5),
            dpi=150,
            facecolor=CHART_BACKGROUND,
        )
        axis.set_facecolor(CHART_BACKGROUND)
        if color_field:
            groups: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                groups.setdefault(str(row.get(color_field, "")), []).append(
                    row
                )
        else:
            groups = {"": rows}

        def numeric(value: Any) -> float:
            if value is None or isinstance(value, bool):
                return math.nan
            try:
                number = float(value)
            except (TypeError, ValueError):
                return math.nan
            return number if math.isfinite(number) else math.nan

        def compact_number(value: float, _position: float) -> str:
            absolute = abs(value)
            for scale, suffix in (
                (1_000_000_000_000, "T"),
                (1_000_000_000, "B"),
                (1_000_000, "M"),
                (1_000, "k"),
            ):
                if absolute >= scale:
                    return f"{value / scale:.3g}{suffix}"
            return f"{value:.3g}"

        if mark == "bar":
            category_field = y_field if horizontal_bar else x_field
            value_field = x_field if horizontal_bar else y_field
            categories = list(
                dict.fromkeys(
                    str(row.get(category_field, "—")) for row in rows
                )
            )
            positions = list(range(len(categories)))
            category_positions = {
                category: position
                for category, position in zip(
                    categories, positions, strict=True
                )
            }
            group_count = len(groups)
            width = min(0.72 / max(group_count, 1), 0.72)
            for index, (label, group) in enumerate(groups.items()):
                values_by_category = {
                    str(row.get(category_field, "—")): numeric(
                        row.get(value_field)
                    )
                    for row in group
                }
                offsets = [
                    category_positions[category]
                    + (index - (group_count - 1) / 2) * width
                    for category in categories
                ]
                values = [
                    values_by_category.get(category, math.nan)
                    for category in categories
                ]
                kwargs = {
                    "color": CHART_COLORS[index % len(CHART_COLORS)],
                    "label": label if color_field else None,
                    "zorder": 3,
                }
                if horizontal_bar:
                    axis.barh(
                        offsets,
                        values,
                        height=width * 0.9,
                        **kwargs,
                    )
                else:
                    axis.bar(
                        offsets,
                        values,
                        width=width * 0.9,
                        **kwargs,
                    )
            display_categories = [
                category if len(category) <= 28 else f"{category[:27]}…"
                for category in categories
            ]
            if horizontal_bar:
                axis.set_yticks(positions, display_categories)
                axis.invert_yaxis()
            else:
                axis.set_xticks(positions, display_categories)
        else:
            for index, (label, group) in enumerate(groups.items()):
                x_values = [row.get(x_field) for row in group]
                y_values = [numeric(row.get(y_field)) for row in group]
                color = CHART_COLORS[index % len(CHART_COLORS)]
                kwargs = {
                    "label": label if color_field else None,
                    "color": color,
                    "zorder": 3,
                }
                if mark == "line":
                    axis.plot(
                        x_values,
                        y_values,
                        marker="o",
                        linewidth=2.5,
                        markersize=4.5,
                        **kwargs,
                    )
                else:
                    valid = [
                        (x_value, y_value)
                        for x_value, y_value in zip(
                            x_values, y_values, strict=True
                        )
                        if not math.isnan(y_value)
                    ]
                    axis.scatter(
                        [value[0] for value in valid],
                        [value[1] for value in valid],
                        s=38,
                        edgecolors=CHART_BACKGROUND,
                        linewidths=0.8,
                        **kwargs,
                    )

        def axis_title(channel: Any, fallback: str) -> str:
            if not isinstance(channel, dict):
                return fallback
            axis_config = channel.get("axis")
            if isinstance(axis_config, dict) and axis_config.get("title"):
                return str(axis_config["title"])
            return str(channel.get("title") or fallback)

        axis.set_xlabel(axis_title(encoding.get("x"), x_field))
        axis.set_ylabel(axis_title(encoding.get("y"), y_field))
        axis.set_title(
            str(spec.get("title") or ""),
            loc="left",
            color=CHART_TEXT,
            fontsize=13,
            fontweight=600,
            pad=14,
        )
        axis.xaxis.label.set_color(CHART_TEXT)
        axis.yaxis.label.set_color(CHART_TEXT)
        axis.xaxis.label.set_size(10)
        axis.yaxis.label.set_size(10)
        axis.tick_params(
            axis="both",
            colors=CHART_TEXT,
            labelsize=9,
            color=CHART_BORDER,
        )
        for spine in axis.spines.values():
            spine.set_color(CHART_BORDER)
        value_axis = "x" if horizontal_bar else "y"
        axis.grid(axis=value_axis, color=CHART_GRID, linewidth=0.8, zorder=0)
        if horizontal_bar:
            axis.axvline(0, color=CHART_BORDER, linewidth=0.9, zorder=1)
            axis.xaxis.set_major_formatter(FuncFormatter(compact_number))
        else:
            axis.axhline(0, color=CHART_BORDER, linewidth=0.9, zorder=1)
            axis.yaxis.set_major_formatter(FuncFormatter(compact_number))
        category_field = y_field if horizontal_bar else x_field
        labels = [str(row.get(category_field, "")) for row in rows]
        rotate_labels = not horizontal_bar and (
            len(set(labels)) > 8
            or max((len(label) for label in labels), default=0) > 12
        )
        if rotate_labels:
            plt.setp(axis.get_xticklabels(), rotation=45, ha="right")
        if color_field:
            handles, legend_labels = axis.get_legend_handles_labels()
            legend = figure.legend(
                handles,
                [
                    label if len(label) <= 24 else f"{label[:23]}…"
                    for label in legend_labels
                ],
                title=color_field,
                loc="lower center",
                bbox_to_anchor=(0.5, 0.015),
                ncol=min(4, len(groups)),
                frameon=False,
                fontsize=8,
                title_fontsize=9,
            )
            if legend:
                legend.get_title().set_color(CHART_TEXT)
                for text in legend.get_texts():
                    text.set_color(CHART_TEXT)
        figure.subplots_adjust(
            left=0.29 if horizontal_bar else 0.12,
            right=0.975,
            top=0.86,
            bottom=(
                0.43
                if color_field and rotate_labels
                else 0.29
                if rotate_labels
                else 0.23
                if color_field
                else 0.16
            ),
        )
        if truncated:
            figure.text(
                0.99,
                0.985,
                "Data truncated by the governed query row limit.",
                fontsize=7,
                color=CHART_MUTED_TEXT,
                ha="right",
                va="top",
            )
        output = io.BytesIO()
        figure.savefig(
            output,
            format="png",
            facecolor=CHART_BACKGROUND,
        )
        plt.close(figure)
        return base64.b64encode(output.getvalue()).decode("ascii")
    except Exception:
        return None


_FORBIDDEN_AST_NODES = (
    ast.Import,
    ast.ImportFrom,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.ClassDef,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.Lambda,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Global,
    ast.Nonlocal,
)
_FORBIDDEN_CALLS = {
    "__import__",
    "breakpoint",
    "compile",
    "eval",
    "exec",
    "globals",
    "help",
    "input",
    "locals",
    "open",
    "vars",
}


def _run_restricted_python(source: str, data: Any) -> dict[str, Any]:
    if len(source) > MAX_PYTHON_SOURCE_CHARS:
        raise ValueError("Python source is too large")
    if len(json.dumps(data, default=str).encode("utf-8")) > 1_000_000:
        raise ValueError("Scratch input is too large")
    tree = ast.parse(source, mode="exec")
    nodes = list(ast.walk(tree))
    if len(nodes) > 2_000:
        raise ValueError("Python source is too complex")
    for node in nodes:
        if isinstance(node, _FORBIDDEN_AST_NODES):
            raise ValueError(
                f"{type(node).__name__} is unavailable in scratch analysis"
            )
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ValueError(
                "Dunder names are unavailable in scratch analysis"
            )
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise ValueError(
                "Dunder attributes are unavailable in scratch analysis"
            )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _FORBIDDEN_CALLS
        ):
            raise ValueError(
                f"{node.func.id} is unavailable in scratch analysis"
            )
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, int)
            and abs(node.value) > 10_000_000
        ):
            raise ValueError(
                "Large integer constants are unavailable in scratch analysis"
            )
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            left_is_sequence = isinstance(
                node.left, (ast.List, ast.Tuple)
            ) or (
                isinstance(node.left, ast.Constant)
                and isinstance(node.left.value, (str, bytes))
            )
            right_is_sequence = isinstance(
                node.right, (ast.List, ast.Tuple)
            ) or (
                isinstance(node.right, ast.Constant)
                and isinstance(node.right.value, (str, bytes))
            )
            if left_is_sequence or right_is_sequence:
                raise ValueError(
                    "Sequence multiplication is unavailable in scratch analysis"
                )

    def safe_range(*args: int) -> range:
        value = range(*args)
        if len(value) > 10_000:
            raise ValueError("Scratch range is too large")
        return value

    safe_builtins = {
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "dict": dict,
        "enumerate": enumerate,
        "float": float,
        "int": int,
        "len": len,
        "list": list,
        "max": max,
        "min": min,
        "range": safe_range,
        "reversed": reversed,
        "round": round,
        "set": set,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "zip": zip,
    }
    namespace: dict[str, Any] = {
        "__builtins__": safe_builtins,
        "data": data,
        "json": json,
        "math": math,
        "statistics": statistics,
    }
    # The parsed tree is bounded and rejects imports, dunder access, dynamic
    # execution, file access, and other unsafe calls before this point.
    exec(  # nosec B102  # nosemgrep: python.lang.security.audit.exec-detected.exec-detected
        compile(tree, "<standalone-chat-scratch>", "exec"),
        namespace,
        namespace,
    )
    if "result" not in namespace:
        raise ValueError(
            "Set a JSON-serializable value in the variable 'result'"
        )
    serialized = json.dumps(namespace["result"], default=str)
    if len(serialized.encode("utf-8")) > 1_000_000:
        raise ValueError("Scratch result is too large")
    return {"result": json.loads(serialized)}


def build_standalone_chat_mcp_server(
    collector: StandaloneArtifactCollector,
    *,
    result_loader: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
    project_directory: Path | None = None,
    scratch_directory: Path | None = None,
    notebook_mcp_app: Any | None = None,
    analysis_notebook_path: Path | None = None,
    plan_checker: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
    event_sink: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    notebook_lifecycle: StandaloneNotebookLifecycle | None = None,
    runtime_redactions: tuple[str, ...] = (),
    notebook_starter: Callable[[Any, dict[str, Any]], list[Any]] | None = None,
    notebook_session_resolver: Callable[[str], Any] | None = None,
    report_catalog_loader: Callable[[str | None], Awaitable[dict[str, Any]]]
    | None = None,
    report_context_loader: Callable[[str], Awaitable[dict[str, Any]]]
    | None = None,
    published_artifact_checker: Callable[[str, str], Awaitable[dict[str, Any]]]
    | None = None,
    attached_report_id: str | None = None,
) -> Any:
    """Build the isolated artifact publication server used by one run."""
    from claude_agent_sdk import McpSdkServerConfig
    from mcp.server import Server
    from mcp.types import TextContent, Tool

    server = Server("standalone-chat", version="1.0.0")
    common_properties = {
        "filename": {"type": "string"},
        "freshness_at": {"type": ["string", "null"]},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "exclusions": {"type": "array", "items": {"type": "string"}},
        "caveats": {"type": "array", "items": {"type": "string"}},
        "provenance": {"type": "object"},
        "parent_artifact_id": {"type": ["string", "null"]},
    }
    tools = [
        Tool(
            name="start_analysis_notebook",
            description=(
                "Start the run-bound analysis notebook only after plan_query selects notebook_sdk or dataset_ref. "
                "The notebook path is fixed by the runtime and cannot be supplied by the caller."
            ),
            inputSchema={
                "type": "object",
                "properties": {"plan_id": {"type": "string"}},
                "required": ["plan_id"],
            },
        ),
        Tool(
            name="inspect_dbt",
            description=(
                "Inspect the frozen dbt project with a read-only command. Only dbt parse, ls, and compile are available."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "enum": ["parse", "ls", "compile"],
                    },
                    "select": {"type": ["string", "null"], "maxLength": 500},
                },
                "required": ["command"],
            },
        ),
        Tool(
            name="run_scratch_python",
            description=(
                "Run restricted, in-memory Python for calculations. Imports, files, networking, "
                "environment access, shell commands, and dynamic code are unavailable. Put the "
                "JSON-serializable output in a variable named result."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "data": {},
                },
                "required": ["source"],
            },
        ),
        Tool(
            name="publish_table",
            description="Publish an immutable table snapshot attached to the answer.",
            inputSchema={
                "type": "object",
                "properties": {
                    **common_properties,
                    "result_id": {"type": "string"},
                    "columns": {"type": "array", "items": {"type": "object"}},
                    "rows": {"type": "array", "items": {"type": "object"}},
                    "column_descriptions": {"type": "object"},
                    "truncated": {"type": "boolean"},
                },
                "required": ["filename", "result_id"],
            },
        ),
        Tool(
            name="publish_chart",
            description=(
                "Publish a static chart using a Vega-Lite-compatible spec and the exact source-row snapshot."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **common_properties,
                    "result_id": {"type": "string"},
                    "spec": {"type": "object"},
                    "rows": {"type": "array", "items": {"type": "object"}},
                    "truncated": {"type": "boolean"},
                },
                "required": ["filename", "result_id", "spec"],
            },
        ),
        Tool(
            name="publish_report",
            description="Publish a self-contained static HTML/CSS report. JavaScript and remote resources are forbidden.",
            inputSchema={
                "type": "object",
                "properties": {
                    **common_properties,
                    "html": {"type": "string"},
                    "result_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "artifact_references": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["filename", "html"],
            },
        ),
        Tool(
            name="list_saved_report_catalog",
            description=(
                "List one 50-report page of compact saved-report semantic cards for this run's owner and project. "
                "Start without a cursor, then call every returned next_cursor before proposing a new report."
            ),
            inputSchema={
                "type": "object",
                "properties": {"cursor": {"type": ["string", "null"]}},
            },
        ),
        Tool(
            name="load_report_context",
            description=(
                "Load prompts, version lineage, output shape, governed SQL purposes, freshness, assumptions, "
                "and caveats for a report selected from the catalog. Historical SQL is context only."
            ),
            inputSchema={
                "type": "object",
                "properties": {"report_id": {"type": "string"}},
                "required": ["report_id"],
            },
        ),
        Tool(
            name="propose_report_action",
            description=(
                "Record the single catalog-backed report decision for this completed run. Use open for exact saved "
                "content, update for a semantically equivalent report, create when no catalog match exists, or "
                "no_suggestion when the artifact should not be promoted. Scan every catalog page first."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "create",
                            "update",
                            "open",
                            "no_suggestion",
                        ],
                    },
                    "artifact_kind": {
                        "type": "string",
                        "enum": ["table", "chart", "report"],
                    },
                    "artifact_filename": {"type": "string"},
                    "title": {"type": "string", "maxLength": 200},
                    "reason": {"type": "string", "maxLength": 2000},
                    "existing_report_id": {"type": ["string", "null"]},
                },
                "required": [
                    "action",
                    "artifact_kind",
                    "artifact_filename",
                    "title",
                    "reason",
                ],
            },
        ),
    ]
    if notebook_mcp_app is None:
        tools = [
            tool for tool in tools if tool.name != "start_analysis_notebook"
        ]

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return tools

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict[str, Any]
    ) -> list[TextContent]:
        try:
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
                plan_id = str(arguments.get("plan_id") or "").strip()
                if (
                    not plan_id
                    or plan_checker is None
                    or notebook_mcp_app is None
                    or analysis_notebook_path is None
                ):
                    raise ValueError(
                        "The run-bound analysis notebook is unavailable"
                    )
                plan = await plan_checker(plan_id)
                if plan.get("route") not in {"notebook_sdk", "dataset_ref"}:
                    raise ValueError(
                        "The selected plan does not permit a notebook kernel"
                    )
                if (
                    notebook_lifecycle is not None
                    and notebook_lifecycle.session_id
                ):
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                {
                                    "session_id": notebook_lifecycle.session_id,
                                    "status": "already_running",
                                    "plan_id": notebook_lifecycle.plan_id,
                                }
                            ),
                        )
                    ]
                if notebook_starter is None:
                    from signalpilot._server.ai.notebook_mcp import (
                        _handle_start_notebook_session,
                    )
                    from signalpilot._server.ai.tools.base import ToolContext

                    result = _handle_start_notebook_session(
                        ToolContext(app=notebook_mcp_app),
                        {
                            "file_path": str(analysis_notebook_path),
                            "auto_run": True,
                        },
                    )
                else:
                    result = notebook_starter(
                        notebook_mcp_app,
                        {
                            "file_path": str(analysis_notebook_path),
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
                    notebook_lifecycle.session_id = session_id
                    notebook_lifecycle.plan_id = plan_id
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
                    await event_sink("notebook_started", {"plan_id": plan_id})
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "session_id": session_id,
                                "status": "started",
                                "plan_id": plan_id,
                                "cell_ids": started.get("cell_ids") or [],
                            }
                        ),
                    )
                ]
            if name == "inspect_dbt":
                if project_directory is None or scratch_directory is None:
                    raise ValueError("The frozen dbt project is unavailable")
                command = str(arguments.get("command") or "")
                if command not in {"parse", "ls", "compile"}:
                    raise ValueError(
                        "Only dbt parse, ls, and compile are allowed"
                    )
                target_path = scratch_directory / "dbt-target"
                target_path.mkdir(parents=True, exist_ok=True)
                argv = [
                    "dbt",
                    "--no-use-colors",
                    "--log-path",
                    str(scratch_directory / "dbt-logs"),
                    command,
                    "--project-dir",
                    str(project_directory),
                    "--target-path",
                    str(target_path),
                ]
                selection = str(arguments.get("select") or "").strip()
                if selection:
                    argv.extend(["--select", selection])
                process = await asyncio.create_subprocess_exec(
                    *argv,
                    cwd=project_directory,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                try:
                    output, _ = await asyncio.wait_for(
                        process.communicate(), timeout=120
                    )
                except TimeoutError:
                    process.kill()
                    await process.wait()
                    raise ValueError("dbt inspection timed out") from None
                text_output = output.decode(errors="replace")[-50_000:]
                if process.returncode != 0:
                    raise ValueError(
                        f"dbt {command} failed: {text_output[-2_000:]}"
                    )
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {"command": command, "output": text_output}
                        ),
                    )
                ]
            if name == "run_scratch_python":
                result = _run_restricted_python(
                    str(arguments.get("source") or ""),
                    arguments.get("data"),
                )
                return [TextContent(type="text", text=json.dumps(result))]

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
