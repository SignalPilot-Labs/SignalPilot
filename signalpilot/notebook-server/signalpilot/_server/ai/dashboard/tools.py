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
    LoadedDataset,
    load_datasets,
    resolve_scratch_path,
)
from signalpilot._server.ai.dashboard.prepare import (
    infer_column_types,
    prepare_chart_rows,
)
from signalpilot._server.ai.dashboard.schema import (
    DashboardSchemaUnavailable,
    validate_spec,
)

DASHBOARD_PATH_RE = re.compile(
    r"^artifacts/[A-Za-z0-9_./-]+\.dashboard\.json$"
)
DEFAULT_RENDER_CLI = "/opt/sp-dashboard/render-cli.js"
PREVIEW_DIRECTORY = ".dashboard-previews"
SCREENSHOT_TIMEOUT_SECONDS = 20.0
MAX_CHART_IDS = 20
MAX_LIMIT = 200
MAX_SPEC_BYTES = 5 * 1024 * 1024


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
    stem = Path(path).name
    stem = (
        stem[: -len(".dashboard.json")]
        if stem.endswith(".dashboard.json")
        else Path(stem).stem
    )
    return f"{stem}-{int(time.time())}.png"


async def _run_renderer(
    command: list[str],
    *,
    stdin_payload: dict[str, Any],
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
            process.communicate(json.dumps(stdin_payload).encode("utf-8")),
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
    ids = [str(item) for item in chart_ids or [] if str(item)] or None
    unknown = [chart_id for chart_id in ids or [] if chart_id not in charts]
    if unknown:
        return [
            _text(
                _invalid(
                    [
                        f"Unknown chart ids: {', '.join(unknown)}. Valid ids: "
                        f"{', '.join(charts)}."
                    ],
                    rendered=[],
                    failed=[],
                )
            )
        ]
    valid_block = {"valid": True, "errors": []}
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
    loaded = load_datasets(scratch_directory, spec)
    dataset_rows, unreadable = _split_loaded(loaded)
    preview_dir = scratch_directory / PREVIEW_DIRECTORY
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_name = _preview_name(path)
    out_path = preview_dir / preview_name
    status, error = await _run_renderer(
        command,
        stdin_payload={
            "spec": spec,
            "datasets": dataset_rows,
            "chart_ids": ids,
        },
        out_path=out_path,
        width=width,
        theme=theme,
    )
    failed = _unreadable_failures(charts, ids, unreadable)
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


def _split_loaded(
    loaded: dict[str, LoadedDataset],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    unreadable: dict[str, str] = {}
    for name, dataset in loaded.items():
        if dataset.error:
            unreadable[name] = dataset.error
        else:
            rows[name] = dataset.rows
    return rows, unreadable


def _unreadable_failures(
    charts: dict[str, dict[str, Any]],
    ids: list[str] | None,
    unreadable: dict[str, str],
) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for chart_id, chart in charts.items():
        if ids is not None and chart_id not in ids:
            continue
        dataset = str(chart.get("dataset"))
        if dataset in unreadable:
            failures.append(
                {
                    "id": chart_id,
                    "code": "dataset_unreadable",
                    "message": (
                        f"Chart '{chart_id}' dataset '{dataset}' is "
                        f"unreadable: {unreadable[dataset]}"
                    ),
                }
            )
    return failures
