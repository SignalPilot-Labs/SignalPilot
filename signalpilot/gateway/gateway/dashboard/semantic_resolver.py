"""Read-only projection of existing dbt, schema, and semantic authorities."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import select

from gateway.connectors.pool_manager import pool_manager
from gateway.connectors.schema_cache import _schema_fingerprint, schema_cache
from gateway.db.models import GatewayConnection, GatewayWorkspaceProject
from gateway.dbt.inventory import scan_project
from gateway.dbt.types import ModelInfo, ProjectMap
from gateway.git.repos import repo_path
from gateway.models.dashboards import (
    DashboardSemanticContext,
    DashboardSemanticExplore,
    DashboardSemanticField,
    DashboardSemanticMetric,
)
from gateway.store import Store
from gateway.verification import compare_columns
from gateway.workspace_store.objects import workspace_object_storage

from .project_snapshot import hydrate_github_mirror, materialize_workspace_snapshot

SUPPORTED_AGGREGATIONS = {"sum", "count", "count_distinct", "average", "min", "max"}
SUPPORTED_METRIC_FORMATS = {"integer", "decimal", "compact", "percentage"}


class DashboardSemanticError(ValueError):
    pass


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _logical_type(value: str | None) -> str:
    lowered = (value or "").lower()
    if any(part in lowered for part in ("int", "decimal", "numeric", "float", "money", "real")):
        return "number"
    if "date" in lowered and "time" not in lowered:
        return "date"
    if any(part in lowered for part in ("time", "datetime")):
        return "timestamp"
    if any(part in lowered for part in ("bit", "bool")):
        return "boolean"
    return "string"


def parse_approved_metrics(settings: dict | None) -> list[dict[str, Any]]:
    """Parse only explicit human-approved metric bindings from project settings."""
    bindings = (settings or {}).get("dashboard_metrics") or []
    parsed: list[dict[str, Any]] = []
    for raw in bindings:
        if not isinstance(raw, dict) or raw.get("approved") is not True:
            continue
        required = ("model", "column", "aggregation", "label")
        if any(not str(raw.get(key) or "").strip() for key in required):
            raise DashboardSemanticError(
                "Approved dashboard metric bindings require model, column, aggregation, and label"
            )
        aggregation = str(raw["aggregation"]).lower()
        if aggregation not in SUPPORTED_AGGREGATIONS:
            raise DashboardSemanticError(f"Unsupported approved metric aggregation: {aggregation}")
        metric_format = str(raw["format"]) if raw.get("format") else None
        if metric_format == "number":
            metric_format = "decimal"
        if metric_format and metric_format not in SUPPORTED_METRIC_FORMATS:
            if not (
                metric_format.startswith("currency:")
                and len(metric_format) == 12
                and metric_format[9:].isupper()
            ):
                raise DashboardSemanticError(f"Unsupported approved metric format: {metric_format}")
        parsed.append(
            {
                "model": str(raw["model"]),
                "column": str(raw["column"]),
                "aggregation": aggregation,
                "label": str(raw["label"]),
                "format": metric_format,
                "field_id": str(raw.get("field_id") or f"{raw['model']}.{raw['column']}"),
                "approval_source": str(raw.get("approval_source") or "project_settings"),
            }
        )
    return parsed


def _project_projection(project_map: ProjectMap) -> dict[str, Any]:
    return {
        "project_name": project_map.project_name,
        "models": {
            name: {
                "description": model.description,
                "materialization": model.materialization,
                "columns": [
                    {
                        "name": col.name,
                        "type": col.data_type,
                        "description": col.description,
                        "tests": sorted(col.tests),
                    }
                    for col in sorted(model.columns, key=lambda item: item.name)
                ],
                "refs": sorted(model.all_refs),
                "tags": sorted(model.tags),
            }
            for name, model in sorted(project_map.models.items())
        },
    }


def _relation_for_model(model: ModelInfo, schema: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    alias = str((model.config or {}).get("alias") or model.name)
    configured_schema = str((model.config or {}).get("schema") or "").lower()
    matches: list[tuple[str, dict[str, Any]]] = []
    for key, table in schema.items():
        table_name = str(table.get("name") or key.split(".")[-1])
        table_schema = str(table.get("schema") or "")
        if table_name.lower() != alias.lower():
            continue
        if configured_schema and table_schema.lower() != configured_schema:
            continue
        matches.append((key, table))
    if len(matches) == 1:
        key, table = matches[0]
        database = str(table.get("database") or "")
        relation = ".".join(
            part for part in (database, str(table.get("schema") or ""), str(table.get("name") or alias)) if part
        )
        return relation or key, table
    return None


def resolve_from_authorities(
    *,
    project_id: str,
    commit_sha: str,
    connection_name: str,
    project_map: ProjectMap,
    physical_schema: dict[str, Any],
    semantic_model: dict[str, Any],
    approved_metrics: list[dict[str, Any]],
) -> DashboardSemanticContext:
    physical_fingerprint = _schema_fingerprint(physical_schema)
    fingerprint = _canonical_hash(
        {
            "project_commit_sha": commit_sha,
            "project_map": _project_projection(project_map),
            "physical_schema_fingerprint": physical_fingerprint,
            "connection_semantic_model": semantic_model,
            "approved_metrics": approved_metrics,
        }
    )
    metrics_by_model: dict[str, list[dict[str, Any]]] = {}
    for binding in approved_metrics:
        metrics_by_model.setdefault(str(binding["model"]), []).append(binding)

    explores: list[DashboardSemanticExplore] = []
    verification_refs: list[str] = []
    semantic_tables = semantic_model.get("tables") or {}
    for model_name, model in sorted(project_map.models.items()):
        resolved = _relation_for_model(model, physical_schema)
        if resolved is None:
            continue
        relation, table = resolved
        physical_columns = {str(col.get("name")): col for col in table.get("columns") or []}
        schema_check = compare_columns([column.name for column in model.columns], list(physical_columns))
        verification_refs.append(f"schema:{model_name}:{'verified' if schema_check.valid else 'changes_detected'}")
        semantic_table = (
            semantic_tables.get(relation)
            or semantic_tables.get(
                next((key for key in semantic_tables if key.endswith(f".{relation.split('.')[-1]}")), "")
            )
            or {}
        )
        semantic_columns = semantic_table.get("columns") or {}
        dimensions: list[DashboardSemanticField] = []
        for column in model.columns:
            physical = physical_columns.get(column.name)
            if physical is None:
                continue
            semantic_column = semantic_columns.get(column.name) or {}
            dimensions.append(
                DashboardSemanticField(
                    field_id=f"{model_name}.{column.name}",
                    column=column.name,
                    logical_type=_logical_type(str(physical.get("type") or column.data_type or "")),
                    label=str(semantic_column.get("label") or column.name.replace("_", " ").title()),
                    description=semantic_column.get("description") or column.description,
                    tests=list(column.tests),
                    tags=list(model.tags),
                )
            )
        metrics: list[DashboardSemanticMetric] = []
        for binding in metrics_by_model.get(model_name, []):
            column = next((item for item in dimensions if item.column == binding["column"]), None)
            if column is None:
                raise DashboardSemanticError(
                    f"Approved metric column does not resolve: {model_name}.{binding['column']}"
                )
            metrics.append(
                DashboardSemanticMetric(
                    **column.model_dump(exclude={"field_id", "label"}),
                    field_id=str(binding["field_id"]),
                    aggregation=str(binding["aggregation"]),
                    label=str(binding["label"]),
                    format=binding.get("format"),
                    approval_source=str(binding["approval_source"]),
                    human_verified=True,
                )
            )
        joins = [
            join for join in semantic_model.get("joins") or [] if str(join.get("from") or "").startswith(f"{relation}.")
        ]
        explores.append(
            DashboardSemanticExplore(
                name=model_name,
                label=model_name.replace("_", " ").title(),
                relation=relation,
                description=semantic_table.get("description") or model.description,
                dimensions=dimensions,
                metrics=metrics,
                joins=joins,
            )
        )
    return DashboardSemanticContext(
        project_id=project_id,
        commit_sha=commit_sha,
        connection_name=connection_name,
        connection_type="mssql",
        physical_schema_fingerprint=physical_fingerprint,
        semantic_fingerprint=fingerprint,
        explores=explores,
        verification_refs=verification_refs,
    )


def _scan_commit(project_id: str, commit_sha: str) -> ProjectMap:
    """Materialize one immutable bare-repo commit into a temporary scanner root."""
    if len(commit_sha) != 40 or any(ch not in "0123456789abcdef" for ch in commit_sha.lower()):
        raise DashboardSemanticError("A full immutable commit SHA is required")
    with tempfile.TemporaryDirectory(prefix="sp-dashboard-") as temp_dir:
        archive_path = Path(temp_dir) / "project.tar"
        checkout_path = Path(temp_dir) / "project"
        checkout_path.mkdir()
        with archive_path.open("wb") as output:
            completed = subprocess.run(
                ["git", "--git-dir", str(repo_path(project_id)), "archive", commit_sha],
                stdout=output,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
        if completed.returncode != 0:
            raise DashboardSemanticError("The pinned project commit is unavailable")
        with tarfile.open(archive_path) as archive:
            archive.extractall(checkout_path, filter="data")
        return scan_project(checkout_path)


async def _scan_pinned_project(
    store: Store,
    *,
    org_id: str,
    project_id: str,
    commit_sha: str,
) -> ProjectMap:
    """Scan a durable workspace snapshot, with git commits kept for compatibility."""
    with tempfile.TemporaryDirectory(prefix="sp-dashboard-workspace-") as temp_dir:
        checkout_path = Path(temp_dir) / "project"
        if await materialize_workspace_snapshot(
            store.session,
            workspace_object_storage(),
            org_id=org_id,
            project_id=project_id,
            snapshot_ref=commit_sha,
            destination=checkout_path,
        ):
            return scan_project(checkout_path)
    try:
        return _scan_commit(project_id, commit_sha)
    except DashboardSemanticError as original:
        # Older dashboard versions store a real Git commit rather than a
        # workspace snapshot reference. Rehydrate the replaceable GitHub
        # mirror lazily so those versions survive gateway replacement too.
        if await hydrate_github_mirror(
            store.session,
            org_id=org_id,
            project_id=project_id,
        ):
            return _scan_commit(project_id, commit_sha)
        raise original


class DashboardSemanticResolver:
    async def resolve(self, store: Store, *, project_id: str, commit_sha: str) -> DashboardSemanticContext:
        org_id = store._require_org_id()
        project = (
            await store.session.execute(
                select(GatewayWorkspaceProject).where(
                    GatewayWorkspaceProject.id == project_id,
                    GatewayWorkspaceProject.org_id == org_id,
                    GatewayWorkspaceProject.status == "active",
                )
            )
        ).scalar_one_or_none()
        if project is None:
            raise DashboardSemanticError("Project not found")
        connection_name = str(project.connection_name or "")
        connection = (
            await store.session.execute(
                select(GatewayConnection).where(
                    GatewayConnection.org_id == org_id,
                    GatewayConnection.name == connection_name,
                )
            )
        ).scalar_one_or_none()
        if connection is None or connection.db_type != "mssql":
            raise DashboardSemanticError("Dashboard Phase 1 requires the project's MSSQL connection")
        physical_schema = schema_cache.get(connection_name)
        if physical_schema is None:
            connection_string = await store.get_connection_string(connection_name)
            if not connection_string:
                raise DashboardSemanticError("MSSQL connection credentials are unavailable")
            extras = await store.get_credential_extras(connection_name)
            async with pool_manager.connection(
                connection.db_type,
                connection_string,
                credential_extras=extras,
                connection_name=connection_name,
            ) as connector:
                physical_schema = await connector.get_schema()
            schema_cache.put(connection_name, physical_schema)
        physical_schema = await store.apply_endorsement_filter(connection_name, physical_schema)
        includes = connection.schema_filter_include or []
        excludes = connection.schema_filter_exclude or []
        physical_schema = {
            key: value
            for key, value in physical_schema.items()
            if (
                not includes
                or any(fnmatch.fnmatch(str(value.get("schema") or "").lower(), item.lower()) for item in includes)
            )
            and not any(fnmatch.fnmatch(str(value.get("schema") or "").lower(), item.lower()) for item in excludes)
        }
        project_map = await _scan_pinned_project(
            store,
            org_id=org_id,
            project_id=project_id,
            commit_sha=commit_sha,
        )
        from gateway.api.schema._semantic_store import _load_semantic_model

        return resolve_from_authorities(
            project_id=project.id,
            commit_sha=commit_sha,
            connection_name=connection_name,
            project_map=project_map,
            physical_schema=physical_schema,
            semantic_model=_load_semantic_model(connection_name),
            approved_metrics=parse_approved_metrics(project.settings),
        )
