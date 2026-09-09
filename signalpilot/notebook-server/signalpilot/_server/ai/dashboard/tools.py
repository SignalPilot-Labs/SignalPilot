"""The two dashboard check tools: ``dashboard_sample_data`` and
``dashboard_screenshot``.

Both take a ``path`` relative to the scratch directory, validate the file
against the dashboard schema, and never raise into the agent: every failure
comes back as a structured JSON text block.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from signalpilot._server.ai.dashboard.datasets import (
    load_datasets,
    resolve_scratch_path,
)
from signalpilot._server.ai.dashboard.prepare import (
    FAILED_CODES,
    ROW_CAP,
    chart_is_failed,
    infer_column_types,
    prepare_chart_rows,
)
from signalpilot._server.ai.dashboard.schema import (
    DASHBOARD_PATH_PATTERN,
    DashboardSchemaUnavailable,
    validate_spec,
)

DASHBOARD_PATH_RE = re.compile(DASHBOARD_PATH_PATTERN)
DEFAULT_RENDER_CLI = "/opt/sp-dashboard/render-cli.js"
PREVIEW_DIRECTORY = ".dashboard-previews"
SCREENSHOT_TIMEOUT_SECONDS = 20.0
MAX_CHART_IDS = 20
MAX_LIMIT = 200
MAX_SPEC_BYTES = 5 * 1024 * 1024
# The renderer reads its whole input from stdin before drawing; past this the
# tool refuses instead of stalling the run.
MAX_STDIN_BYTES = 64 * 1024 * 1024


def _text(payload: dict[str, Any]) -> Any:
    from mcp.types import TextContent

    return TextContent(type="text", text=json.dumps(payload))


def _invalid(errors: list[str], **extra: Any) -> dict[str, Any]:
    return {"dashboard": {"valid": False, "errors": errors}, **extra}


def _load_spec(
    scratch_directory: Path, path: str
) -> tuple[dict[str, Any] | None, list[str]]:
    """Resolve, read, parse, and validate the dashboard file."""
    if not DASHBOARD_PATH_RE.match(str(path or "")):
        return None, [
            "path must match artifacts/<name>.dashboard.json (letters, "
            "digits, '_', '-', '.', '/')."
        ]
    try:
        target = resolve_scratch_path(scratch_directory, path)
    except ValueError as exc:
        return None, [str(exc)]
    if not target.is_file():
        return None, [f"Dashboard file not found: {path}"]
    try:
        if target.stat().st_size > MAX_SPEC_BYTES:
            return None, [f"Dashboard file is larger than 5 MB: {path}"]
        parsed = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return None, [f"Dashboard file is not valid JSON: {exc}"]
    try:
        errors = validate_spec(parsed)
    except DashboardSchemaUnavailable as exc:
        return None, [str(exc)]
    if errors:
        return None, errors
    return parsed, []


def _charts_by_id(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(chart.get("id")): chart
        for chart in spec.get("charts") or []
        if isinstance(chart, dict) and chart.get("id")
    }


async def dashboard_sample_data(
    *,
    scratch_directory: Path,
    path: str,
    chart_ids: list[str],
    limit: int = 10,
) -> list[Any]:
    """Return prepared sample rows and issues for the requested charts."""
    try:
        return [
            _text(
                _sample_data_payload(scratch_directory, path, chart_ids, limit)
            )
        ]
    except Exception as exc:
        return [
            _text(
                _invalid(
                    [f"internal_error: {exc}"],
                    charts=[],
                    error="internal_error",
                )
            )
        ]


def _sample_data_payload(
    scratch_directory: Path,
    path: str,
    chart_ids: list[str],
    limit: int,
) -> dict[str, Any]:
    ids = [str(item) for item in chart_ids if str(item)]
    if not ids or len(ids) > MAX_CHART_IDS:
        return _invalid(
            [f"chart_ids must contain 1 to {MAX_CHART_IDS} ids."], charts=[]
        )
    limit = max(1, min(int(limit or 10), MAX_LIMIT))
    spec, errors = _load_spec(scratch_directory, path)
    if spec is None:
        return _invalid(errors, charts=[])
    charts = _charts_by_id(spec)
    wanted = {
        str(charts[chart_id].get("dataset"))
        for chart_id in ids
        if chart_id in charts
    }
    datasets = load_datasets(scratch_directory, spec, wanted)
    entries: list[dict[str, Any]] = []
    for chart_id in ids:
        chart = charts.get(chart_id)
        if chart is None:
            entries.append(
                {
                    "id": chart_id,
                    "issues": [
                        {
                            "code": "unknown_chart",
                            "message": (
                                f"Chart '{chart_id}' is not in the dashboard. "
                                f"Valid ids: {', '.join(charts) or 'none'}."
                            ),
                        }
                    ],
                }
            )
            continue
        rows, issues = prepare_chart_rows(chart, spec, datasets)
        # resolved_file: the snapshot path of a SQL dataset; None for rows.
        loaded = datasets.get(str(chart.get("dataset")))
        entries.append(
            {
                "id": chart_id,
                "type": chart.get("type"),
                "dataset": chart.get("dataset"),
                "resolved_file": (
                    loaded.resolved_file if loaded is not None else None
                ),
                "columns": infer_column_types(rows),
                "row_count": len(rows),
                "rows": rows[:limit],
                "issues": issues,
            }
        )
    return {"dashboard": {"valid": True, "errors": []}, "charts": entries}


def _renderer_command() -> tuple[list[str] | None, str | None]:
    """Return the node command for the CLI or the reason it is unavailable."""
    cli = (
        os.getenv("SP_DASHBOARD_RENDER_CLI", "").strip() or DEFAULT_RENDER_CLI
    )
    node = os.getenv("SP_DASHBOARD_NODE", "").strip() or "node"
    if not Path(cli).is_file():
        return None, f"render CLI not found at {cli}"
    node_path = node if Path(node).is_file() else shutil.which(node)
    if node_path is None:
        return None, f"node binary '{node}' not found"
    return [node_path, cli], None


def _preview_name(path: str) -> str:
    """``<stem>-<unix ts>.png``; ``_load_spec`` already enforced the suffix."""
    stem = Path(path).name[: -len(".dashboard.json")]
    return f"{stem}-{int(time.time())}.png"


async def _run_renderer(
    command: list[str],
    *,
    stdin: bytes,
    out_path: Path,
    width: int,
    theme: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Run the CLI; return (status JSON, error string)."""
    process = await asyncio.create_subprocess_exec(
        *command,
        "--out",
        str(out_path),
        "--width",
        str(width),
        "--theme",
        theme,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(stdin),
            timeout=SCREENSHOT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return None, "timeout"
    status: dict[str, Any] | None = None
    for line in reversed(stdout.decode("utf-8", "replace").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            candidate = json.loads(line)
        except ValueError:
            continue
        if isinstance(candidate, dict):
            status = candidate
            break
    if status is None:
        tail = stderr.decode("utf-8", "replace").strip()[-800:]
        return None, (
            f"renderer exited with code {process.returncode}: "
            f"{tail or 'no output'}"
        )
    return status, None


async def dashboard_screenshot(
    *,
    scratch_directory: Path,
    path: str,
    chart_ids: list[str] | None = None,
    width: int = 1280,
    theme: str = "light",
) -> list[Any]:
    """Render the dashboard to PNG. Returns [ImageContent, TextContent]."""
    try:
        return await _screenshot(
            scratch_directory, path, chart_ids, width, theme
        )
    except Exception as exc:
        return [
            _text(_invalid([f"internal_error: {exc}"], error="internal_error"))
        ]


async def _screenshot(
    scratch_directory: Path,
    path: str,
    chart_ids: list[str] | None,
    width: int,
    theme: str,
) -> list[Any]:
    from mcp.types import ImageContent

    width = max(640, min(int(width or 1280), 1920))
    theme = theme if theme in {"light", "dark"} else "light"
    spec, errors = _load_spec(scratch_directory, path)
    if spec is None:
        return [_text(_invalid(errors, rendered=[], failed=[]))]
    charts = _charts_by_id(spec)
    valid_block = {"valid": True, "errors": []}
    ids = [str(item) for item in chart_ids or [] if str(item)] or None
    unknown = [chart_id for chart_id in ids or [] if chart_id not in charts]
    if unknown:
        # The file itself is valid; only the request named ids it lacks.
        return [
            _text(
                {
                    "dashboard": valid_block,
                    "error": "unknown_chart",
                    "message": (
                        f"Unknown chart ids: {', '.join(unknown)}. Valid ids: "
                        f"{', '.join(charts)}."
                    ),
                    "rendered": [],
                    "failed": [],
                }
            )
        ]
    command, reason = _renderer_command()
    if command is None:
        return [
            _text(
                {
                    "dashboard": valid_block,
                    "error": "renderer_unavailable",
                    "message": (
                        f"The dashboard renderer is unavailable ({reason}). "
                        "Use dashboard_sample_data to check the file."
                    ),
                    "rendered": [],
                    "failed": [],
                }
            )
        ]
    datasets, failed = _render_datasets(scratch_directory, spec, charts, ids)
    stdin = json.dumps(
        {"spec": spec, "datasets": datasets, "chart_ids": ids}
    ).encode("utf-8")
    if len(stdin) > MAX_STDIN_BYTES:
        return [
            _text(
                {
                    "dashboard": valid_block,
                    "error": "payload_too_large",
                    "message": (
                        f"The chart data is {len(stdin) >> 20} MB serialized; "
                        f"the renderer accepts at most "
                        f"{MAX_STDIN_BYTES >> 20} MB. Add a limit to the "
                        "charts or request fewer chart_ids."
                    ),
                    "rendered": [],
                    "failed": failed,
                }
            )
        ]
    preview_dir = scratch_directory / PREVIEW_DIRECTORY
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_name = _preview_name(path)
    out_path = preview_dir / preview_name
    status, error = await _run_renderer(
        command,
        stdin=stdin,
        out_path=out_path,
        width=width,
        theme=theme,
    )
    if status is None or not status.get("ok"):
        detail = error or ", ".join(
            str(item) for item in (status or {}).get("errors") or []
        )
        return [
            _text(
                {
                    "dashboard": valid_block,
                    "error": "render_failed",
                    "message": f"The renderer failed: {detail or 'unknown'}",
                    "rendered": [],
                    "failed": failed,
                }
            )
        ]
    failed_ids = {item["id"] for item in failed}
    for item in status.get("failed") or []:
        if isinstance(item, dict) and item.get("id") not in failed_ids:
            failed.append(
                {
                    "id": str(item.get("id")),
                    "code": str(item.get("code") or "render_error"),
                    "message": str(item.get("message") or ""),
                }
            )
    payload = {
        "dashboard": valid_block,
        "rendered": [
            str(item)
            for item in status.get("rendered") or []
            if str(item) not in failed_ids
        ],
        "failed": failed,
        "width": int(status.get("width") or width),
        "height": int(status.get("height") or 0),
        "preview_path": f"{PREVIEW_DIRECTORY}/{preview_name}",
    }
    try:
        png = out_path.read_bytes()
    except OSError as exc:
        payload["error"] = "render_failed"
        payload["message"] = f"The renderer wrote no image: {exc}"
        return [_text(payload)]
    image = ImageContent(
        type="image",
        data=base64.b64encode(png).decode("ascii"),
        mimeType="image/png",
    )
    return [image, _text(payload)]


def _render_datasets(
    scratch_directory: Path,
    spec: dict[str, Any],
    charts: dict[str, dict[str, Any]],
    ids: list[str] | None,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, str]]]:
    """The ``datasets`` map for the renderer and the charts already known to fail.

    Only the datasets the requested charts use are loaded. Each dataset is
    sent as the prepared rows (filters, sort, limit, cap) that
    ``dashboard_sample_data`` reports, so the renderer receives what the
    agent inspected and nothing larger. The renderer applies the same steps
    again, which is idempotent on prepared rows.

    The stdin contract keys datasets by name, so when two requested charts
    shape one dataset differently (a different sort or limit) the prepared
    rows of one would be wrong for the other. That dataset is sent as its raw
    rows, capped at ``ROW_CAP``, and the renderer sorts and slices per chart.
    """
    selected = {
        chart_id: charts[chart_id] for chart_id in (ids or list(charts))
    }
    loaded = load_datasets(
        scratch_directory,
        spec,
        {str(chart.get("dataset")) for chart in selected.values()},
    )
    datasets: dict[str, list[dict[str, Any]]] = {}
    shapes: dict[str, set[str]] = {}
    failed: list[dict[str, str]] = []
    for chart_id, chart in selected.items():
        rows, issues = prepare_chart_rows(chart, spec, loaded)
        if chart_is_failed(issues):
            first = next(
                issue for issue in issues if issue["code"] in FAILED_CODES
            )
            failed.append(
                {
                    "id": chart_id,
                    "code": first["code"],
                    "message": first["message"],
                }
            )
        name = str(chart.get("dataset"))
        dataset = loaded.get(name)
        if dataset is None or dataset.error:
            continue
        shape = json.dumps(
            [chart.get("sort"), chart.get("limit")], sort_keys=True
        )
        shapes.setdefault(name, set()).add(shape)
        if len(shapes[name]) > 1:
            datasets[name] = dataset.rows[:ROW_CAP]
        elif name not in datasets:
            datasets[name] = rows
    return datasets, failed
