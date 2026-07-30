"""In-process publication and restricted scratch-analysis tools for data chat."""

from __future__ import annotations

import ast
import base64
import io
import json
import math
import statistics
from dataclasses import dataclass, field
from typing import Any

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

MAX_SNAPSHOT_ROWS = 1_000
MAX_PYTHON_SOURCE_CHARS = 12_000


@dataclass
class StandaloneArtifactCollector:
    artifacts: list[dict[str, Any]] = field(default_factory=list)


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
    exec(
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
                    "columns": {"type": "array", "items": {"type": "object"}},
                    "rows": {"type": "array", "items": {"type": "object"}},
                    "column_descriptions": {"type": "object"},
                    "truncated": {"type": "boolean"},
                },
                "required": ["filename", "columns", "rows"],
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
                    "spec": {"type": "object"},
                    "rows": {"type": "array", "items": {"type": "object"}},
                    "truncated": {"type": "boolean"},
                },
                "required": ["filename", "spec", "rows"],
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
                },
                "required": ["filename", "html"],
            },
        ),
    ]

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return tools

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict[str, Any]
    ) -> list[TextContent]:
        try:
            if name == "run_scratch_python":
                result = _run_restricted_python(
                    str(arguments.get("source") or ""),
                    arguments.get("data"),
                )
                return [TextContent(type="text", text=json.dumps(result))]

            metadata = _clean_metadata(arguments)
            if name == "publish_table":
                rows = list(arguments.get("rows") or [])[:MAX_SNAPSHOT_ROWS]
                artifact = {
                    **metadata,
                    "kind": "table",
                    "mime_type": "text/csv",
                    "payload": {
                        "columns": list(arguments.get("columns") or []),
                        "rows": rows,
                        "column_descriptions": dict(
                            arguments.get("column_descriptions") or {}
                        ),
                        "truncated": bool(arguments.get("truncated"))
                        or len(arguments.get("rows") or []) > len(rows),
                    },
                }
            elif name == "publish_chart":
                rows = list(arguments.get("rows") or [])[:MAX_SNAPSHOT_ROWS]
                spec, display_rows, display = prepare_signalpilot_chart(
                    dict(arguments.get("spec") or {}),
                    rows,
                )
                columns = [
                    {"name": str(name), "type": "unknown"}
                    for name in (rows[0].keys() if rows else [])
                ]
                truncated = bool(arguments.get("truncated")) or len(
                    arguments.get("rows") or []
                ) > len(rows)
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
                        },
                        "display": display,
                        "truncated": truncated,
                    },
                    "binary_base64": binary_base64,
                }
            elif name == "publish_report":
                artifact = {
                    **metadata,
                    "kind": "report",
                    "mime_type": "text/html",
                    "payload": {"html": str(arguments.get("html") or "")},
                }
            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]
            collector.artifacts.append(artifact)
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "published": True,
                            "artifact_index": len(collector.artifacts) - 1,
                            "kind": artifact["kind"],
                            "filename": artifact["filename"],
                        }
                    ),
                )
            ]
        except Exception as exc:
            return [
                TextContent(type="text", text=json.dumps({"error": str(exc)}))
            ]

    return McpSdkServerConfig(
        type="sdk", name="standalone-chat", instance=server
    )
