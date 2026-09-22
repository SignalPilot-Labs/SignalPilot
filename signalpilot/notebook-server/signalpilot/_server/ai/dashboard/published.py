"""Find and load published dashboards from the gateway.

``list_published`` answers "which dashboards exist" from ``GET
/api/dashboards``. ``load_published`` pulls one dashboard's current version
bundle and restores it into the chat scratch directory as the same files the
agent writes when it builds a dashboard: the spec at
``artifacts/<slug>.dashboard.json``, one snapshot per SQL dataset at
``artifacts/datasets/<name>.csv``, and one sidecar per SQL dataset that
records the SQL and the published version the rows came from. The check
tools then see the snapshots as current, so the agent can edit the file and
the user can publish the result as a new version of the same dashboard.

Both functions return a JSON-ready dict and never raise. Every failure is
``{"error": "not_found" | "gateway_error", "message": ...}``; a
``gateway_error`` carries the HTTP ``status`` when the gateway answered.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import httpx

from signalpilot._dashboard_sql import (
    is_dataset_name,
    row_columns,
    sidecar_path,
    snapshot_path,
    write_sidecar,
    write_snapshot,
)
from signalpilot._server.ai.dashboard.schema import dataset_sql

if TYPE_CHECKING:
    from pathlib import Path

# Ids and slugs as the gateway mints them; also keeps the URL path clean.
DASHBOARD_REF_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,80}$"
_DASHBOARD_REF_RE = re.compile(DASHBOARD_REF_PATTERN)
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_TIMEOUT = httpx.Timeout(30.0)

LIST_FIELDS = (
    "id",
    "slug",
    "name",
    "description",
    "chart_count",
    "visibility",
    "updated_at",
    "last_refresh_at",
    "can_edit",
)

NEXT_STEP = (
    "Edit the file. If you change a dataset's SQL, call sp.dashboard_dataset "
    "for it again. The user publishes the new version from the chat panel."
)


class GatewayAnswer(Exception):
    """A gateway response that ends the tool call; carries the payload."""

    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__(str(payload.get("message") or payload.get("error")))
        self.payload = payload


def _not_found(message: str) -> GatewayAnswer:
    return GatewayAnswer({"error": "not_found", "message": message})


def _gateway_error(message: str, status: int | None = None) -> GatewayAnswer:
    return GatewayAnswer(
        {"error": "gateway_error", "status": status, "message": message}
    )


def _client(
    gateway_url: str,
    gateway_token: str,
    transport: httpx.AsyncBaseTransport | None,
) -> httpx.AsyncClient:
    if not gateway_url or not gateway_token:
        raise _gateway_error(
            "This run has no gateway identity, so published dashboards "
            "cannot be read."
        )
    return httpx.AsyncClient(
        base_url=gateway_url.rstrip("/"),
        headers={
            "Authorization": f"Bearer {gateway_token}",
            "Accept": "application/json",
        },
        timeout=_TIMEOUT,
        transport=transport,
    )


async def _get_json(client: httpx.AsyncClient, path: str) -> dict[str, Any]:
    """GET one gateway path; map every failure to a ``GatewayAnswer``."""
    try:
        response = await client.get(path)
    except httpx.HTTPError as exc:
        raise _gateway_error(
            f"The gateway could not be reached for {path}: {exc}"
        ) from exc
    if response.status_code == 404:
        raise _not_found(f"No dashboard was found at {path}.")
    if response.status_code >= 400:
        raise _gateway_error(
            f"The gateway answered {response.status_code} for {path}: "
            f"{_error_text(response)}",
            response.status_code,
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise _gateway_error(
            f"The gateway answer for {path} is not JSON.",
            response.status_code,
        ) from exc
    if not isinstance(payload, dict):
        raise _gateway_error(
            f"The gateway answer for {path} is not an object.",
            response.status_code,
        )
    return payload


def _error_text(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, dict):
        detail = detail.get("message") or json.dumps(detail)
    text = str(detail or response.text or "").strip()
    return text[:300] or "no detail"


def _list_entry(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict) or not item.get("id"):
        return None
    entry = {field: item.get(field) for field in LIST_FIELDS}
    entry["chart_count"] = int(entry.get("chart_count") or 0)
    entry["can_edit"] = bool(entry.get("can_edit"))
    return entry


async def list_published(
    *,
    gateway_url: str,
    gateway_token: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """``{"dashboards": [...]}`` from ``GET /api/dashboards``."""
    try:
        async with _client(gateway_url, gateway_token, transport) as client:
            payload = await _get_json(client, "/api/dashboards")
    except GatewayAnswer as answer:
        return answer.payload
    items = payload.get("dashboards")
    items = items if isinstance(items, list) else []
    entries = [entry for entry in map(_list_entry, items) if entry]
    return {"dashboards": entries}


def _file_slug(dashboard: dict[str, Any]) -> str:
    slug = str(dashboard.get("slug") or "")
    if _SLUG_RE.match(slug):
        return slug
    return str(dashboard.get("id") or "").lower()


def _write_datasets(
    scratch_directory: Path,
    spec: dict[str, Any],
    bundle_rows: Any,
    origin: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    rows_by_name = bundle_rows if isinstance(bundle_rows, dict) else {}
    written: dict[str, dict[str, Any]] = {}
    for name, (connection, sql) in dataset_sql(spec).items():
        if not is_dataset_name(name):
            continue
        raw = rows_by_name.get(name)
        rows = [
            dict(row)
            for row in (raw if isinstance(raw, list) else [])
            if isinstance(row, dict)
        ]
        columns = row_columns(rows)
        snapshot = snapshot_path(name)
        write_snapshot(scratch_directory / snapshot, columns, rows)
        write_sidecar(
            sidecar_path(scratch_directory, name),
            connection=connection,
            sql=sql,
            columns=columns,
            row_count=len(rows),
            origin=origin,
        )
        written[name] = {"rows": len(rows), "snapshot": snapshot}
    return written


async def load_published(
    *,
    scratch_directory: Path,
    gateway_url: str,
    gateway_token: str,
    dashboard: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Restore one published dashboard's current version into the scratch.

    ``dashboard`` is the id or the slug. An existing file with the same slug
    is overwritten: the user asked to edit that dashboard.
    """
    reference = str(dashboard or "").strip()
    if not _DASHBOARD_REF_RE.match(reference):
        return _not_found(
            "Pass the dashboard id or slug from dashboard_list_published."
        ).payload
    try:
        async with _client(gateway_url, gateway_token, transport) as client:
            detail = await _get_json(client, f"/api/dashboards/{reference}")
            summary = detail.get("dashboard")
            if not isinstance(summary, dict) or not summary.get("id"):
                raise _gateway_error(
                    "The gateway answer has no dashboard.", 200
                )
            dashboard_id = str(summary["id"])
            version_id = str(summary.get("current_version_id") or "")
            if not version_id:
                raise _not_found(
                    f"Dashboard '{reference}' has no published version."
                )
            bundle = await _get_json(
                client,
                f"/api/dashboards/{dashboard_id}/versions/{version_id}/bundle",
            )
    except GatewayAnswer as answer:
        return answer.payload

    spec = bundle.get("spec")
    if not isinstance(spec, dict):
        return _gateway_error("The bundle has no dashboard spec.", 200).payload
    version = bundle.get("version")
    version = version if isinstance(version, dict) else {}
    version_no = int(version.get("version_no") or 0)
    origin = {
        "dashboard_id": dashboard_id,
        "version_id": version_id,
        "version_no": version_no,
    }

    slug = _file_slug(summary)
    path = f"artifacts/{slug}.dashboard.json"
    try:
        target = scratch_directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
        datasets = _write_datasets(
            scratch_directory, spec, bundle.get("datasets"), origin
        )
    except OSError as exc:
        return _gateway_error(
            f"The dashboard could not be written to the scratch: {exc}"
        ).payload

    charts = spec.get("charts")
    return {
        "path": path,
        "dashboard": {
            "id": dashboard_id,
            "slug": slug,
            "name": str(summary.get("name") or spec.get("title") or slug),
            "version_no": version_no,
            "chart_count": len(charts) if isinstance(charts, list) else 0,
        },
        "datasets": datasets,
        "next": NEXT_STEP,
    }
