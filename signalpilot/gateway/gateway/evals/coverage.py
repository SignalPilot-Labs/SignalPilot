"""Measure the dbt project coverage of an evaluation set.

Declared coverage contains each task's ``covers`` entries.
Observed coverage contains tables that the agent reads through MCP tools.
Stored key bindings add the run and task identifiers to the audit metadata.

Coverage is the union of declared and observed models divided by all models.
The result includes coverage for each project layer.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_LAYERS = ("staging", "intermediate", "marts")

# This pattern extracts identifiers after FROM or JOIN.
# It does not parse identifiers inside subqueries.
_TABLE_RE = re.compile(
    r"\b(?:from|join)\s+([a-zA-Z_][\w$]*(?:\.[a-zA-Z_][\w$]*){0,2})", re.IGNORECASE
)


def enumerate_models(project_dir: Path) -> list[dict[str, Any]]:
    """Models in a dbt project checkout.

    Prefers target/manifest.json when the repo ships one; falls back to the
    models/ tree. Layer is inferred from the path (dbt convention).
    """
    manifest = project_dir / "target" / "manifest.json"
    models: list[dict[str, Any]] = []
    if manifest.is_file():
        try:
            nodes = json.loads(manifest.read_text(encoding="utf-8")).get("nodes", {})
            for node in nodes.values():
                if node.get("resource_type") != "model":
                    continue
                path = str(node.get("path", ""))
                models.append({"name": node.get("name", ""), "layer": _layer_of(path)})
            if models:
                return models
        except (ValueError, OSError):
            logger.warning("unreadable manifest.json in %s — falling back to the model tree", project_dir)
    for sql in sorted((project_dir / "models").rglob("*.sql")):
        rel = sql.relative_to(project_dir / "models").as_posix()
        models.append({"name": sql.stem, "layer": _layer_of(rel)})
    return models


def _layer_of(path: str) -> str:
    lowered = path.lower()
    for layer in _LAYERS:
        if layer in lowered:
            return layer
    if "stg" in lowered:
        return "staging"
    if lowered.startswith("int_") or "/int_" in lowered:
        return "intermediate"
    if lowered.startswith(("fct_", "dim_")):
        return "marts"
    return "other"


def tables_from_sql(sql: str) -> set[str]:
    return {m.group(1).lower() for m in _TABLE_RE.finditer(sql or "")}


def _model_key(name: str) -> str:
    """Return the lowercase final path segment for model name matching."""
    return name.rsplit(".", 1)[-1].lower()


# This limit prevents an unbounded audit query for one run.
_OBSERVED_ROW_CAP = 50_000


async def observed_tables_for_run(org_id: str, run_id: str) -> dict[str, set[str]]:
    """Return the table names that each task read from the audit trail.

    The SQL query filters ``metadata_json`` by run identifier.
    Organization activity cannot displace events for the selected run.
    SQLite does not provide the required JSON operators.
    SQLite tests therefore filter these events in Python.
    """
    from sqlalchemy import select

    from ..db.engine import get_session_factory
    from ..db.models import GatewayAuditLog

    factory = get_session_factory()
    out: dict[str, set[str]] = {}
    async with factory() as session:
        try:
            dialect = session.bind.dialect.name  # type: ignore[union-attr]
        except Exception:
            dialect = ""
        stmt = (
            select(
                GatewayAuditLog.sql_text,
                GatewayAuditLog.tables,
                GatewayAuditLog.metadata_json,
            )
            .where(
                GatewayAuditLog.org_id == org_id,
                GatewayAuditLog.event_type == "mcp_tool",
            )
            .order_by(GatewayAuditLog.timestamp.desc())
            .limit(_OBSERVED_ROW_CAP)
        )
        if dialect != "sqlite":
            stmt = stmt.where(
                GatewayAuditLog.metadata_json["eval_run"].as_string() == run_id
            )
        rows = (await session.execute(stmt)).all()
    for sql_text, tables, metadata in rows:
        meta = metadata or {}
        if meta.get("eval_run") != run_id:
            continue
        task_id = str(meta.get("eval_task", "") or "")
        touched = out.setdefault(task_id, set())
        if tables:
            touched.update(str(t).lower() for t in tables)
        if sql_text:
            touched.update(tables_from_sql(sql_text))
    return out


async def compute_coverage(
    org_id: str,
    run_id: str,
    eval_set,
    project_models: list[dict[str, Any]],
    executed_task_ids: set[str] | None = None,
) -> dict[str, Any]:
    declared: set[str] = set()
    declared_by_task: dict[str, set[str]] = {}
    for task in eval_set.tasks:
        if executed_task_ids is not None and task.id not in executed_task_ids:
            continue  # partial run: an unexecuted task's covers aren't coverage
        task_models = {_model_key(c) for c in task.covers} | {
            _model_key(b) for b in task.builds
        }
        declared.update(task_models)
        declared_by_task[task.id] = task_models

    observed_by_task = await observed_tables_for_run(org_id, run_id)
    observed: set[str] = set()
    for touched in observed_by_task.values():
        observed.update(_model_key(t) for t in touched)

    covered = declared | observed
    result: dict[str, Any] = {
        "declared": sorted(declared),
        "observed": sorted(observed),
        "observed_not_declared": sorted(observed - declared),
        "declared_but_not_observed": sorted(declared - observed),
        "per_task_observed": {k: sorted(v) for k, v in observed_by_task.items() if k},
    }

    if project_models:
        by_layer: dict[str, dict[str, int]] = {}
        model_names = {str(m["name"]).lower() for m in project_models}
        hit = covered & model_names
        for m in project_models:
            layer = m.get("layer", "other")
            bucket = by_layer.setdefault(layer, {"total": 0, "covered": 0})
            bucket["total"] += 1
            if str(m["name"]).lower() in hit:
                bucket["covered"] += 1
        result["models"] = [
            {
                "name": str(model["name"]),
                "layer": str(model.get("layer", "other")),
                "covered": _model_key(str(model["name"])) in covered,
                "declared_by": sorted(
                    task_id
                    for task_id, models in declared_by_task.items()
                    if _model_key(str(model["name"])) in models
                ),
                "observed_by": sorted(
                    task_id
                    for task_id, models in observed_by_task.items()
                    if _model_key(str(model["name"]))
                    in {_model_key(name) for name in models}
                ),
            }
            for model in sorted(project_models, key=lambda item: str(item["name"]))
        ]
        result["models_total"] = len(project_models)
        result["models_covered"] = len(hit)
        result["pct"] = round(len(hit) / len(project_models) * 100.0, 1)
        result["by_layer"] = by_layer
        marts = by_layer.get("marts")
        result["marts_pct"] = (
            round(marts["covered"] / marts["total"] * 100.0, 1)
            if marts and marts["total"]
            else None
        )
    else:
        result["models_total"] = None
        result["pct"] = None
        result["marts_pct"] = None
    return result
