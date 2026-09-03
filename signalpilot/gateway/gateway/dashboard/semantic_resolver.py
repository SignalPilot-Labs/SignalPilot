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
from gateway.connectors.registry import get_connector_registration
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
from gateway.workspace_store.dbt_detect import resolve_dbt_project_dir
from gateway.workspace_store.objects import workspace_object_storage

from .project_snapshot import hydrate_github_mirror, materialize_workspace_snapshot

SUPPORTED_METRIC_FORMATS = {"integer", "decimal", "compact", "percentage"}


class DashboardSemanticError(ValueError):
    def __init__(self, message: str, *, code: str = "semantic_context_unavailable"):
        super().__init__(message)
        self.code = code


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


def _metric_aggregation(column: str, logical_type: str, semantic_column: dict[str, Any]) -> tuple[str, bool] | None:
    """Derive a useful aggregation from dbt/semantic metadata without an approval registry."""
    explicit = str(semantic_column.get("aggregation") or "").lower()
    if explicit in {"sum", "count", "count_distinct", "average", "min", "max"}:
        return explicit, False
    if logical_type != "number":
        return None
    normalized = column.lower()
    identifier_suffixes = ("_id", "_key", "_number", "_year", "_month", "_day")
    if normalized in {"id", "year", "month", "day"} or normalized.endswith(identifier_suffixes):
        return None
    if any(token in normalized for token in ("_pct", "percent", "_rate", "_ratio", "average", "avg_")):
        return "average", True
    return "sum", True


def _metric_format(column: str, semantic_column: dict[str, Any]) -> str | None:
    explicit = str(semantic_column.get("format") or "")
    if explicit == "number":
        return "decimal"
    if explicit in SUPPORTED_METRIC_FORMATS or (
        explicit.startswith("currency:") and len(explicit) == 12 and explicit[9:].isupper()
    ):
        return explicit
    normalized = column.lower()
    if any(token in normalized for token in ("_pct", "percent", "_rate", "_ratio")):
        return "percentage"
    return "decimal"


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
                        "meta": col.meta,
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
    connection_type: str,
    project_map: ProjectMap,
    physical_schema: dict[str, Any],
    semantic_model: dict[str, Any],
) -> DashboardSemanticContext:
    physical_fingerprint = _schema_fingerprint(physical_schema)
    fingerprint = _canonical_hash(
        {
            "project_commit_sha": commit_sha,
            "project_map": _project_projection(project_map),
            "physical_schema_fingerprint": physical_fingerprint,
            "connection_semantic_model": semantic_model,
            "connection_type": connection_type,
        }
    )

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
        dbt_columns = {column.name: column for column in model.columns}
        for column in dimensions:
            dbt_meta = dbt_columns[column.column].meta
            dbt_semantic = dbt_meta.get("signalpilot", dbt_meta)
            semantic_column = {
                **(dbt_semantic if isinstance(dbt_semantic, dict) else {}),
                **(semantic_columns.get(column.column) or {}),
            }
            aggregation = _metric_aggregation(column.column, column.logical_type, semantic_column)
            if aggregation is None:
                continue
            aggregation_name, inferred = aggregation
            metrics.append(
                DashboardSemanticMetric(
                    **column.model_dump(exclude={"label"}),
                    aggregation=aggregation_name,
                    label=column.label or column.column.replace("_", " ").title(),
                    format=_metric_format(column.column, semantic_column),
                    semantic_source="dbt_project",
                    aggregation_inferred=inferred,
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
        connection_type=connection_type,
        physical_schema_fingerprint=physical_fingerprint,
        semantic_fingerprint=fingerprint,
        explores=explores,
        verification_refs=verification_refs,
    )


def _scan_materialized_project(checkout_path: Path, settings: dict | None) -> ProjectMap:
    """Scan the manifest-resolved dbt root inside one materialized workspace."""
    files = [path.relative_to(checkout_path).as_posix() for path in checkout_path.rglob("*") if path.is_file()]
    dbt_project_dir = resolve_dbt_project_dir(settings, files)
    if dbt_project_dir is None:
        raise DashboardSemanticError("The pinned project contains no dbt_project.yml")
    resolved = checkout_path / dbt_project_dir if dbt_project_dir else checkout_path
    project_map = scan_project(resolved)
    if not project_map.models and not project_map.sources:
        raise DashboardSemanticError("The pinned dbt project contains no models or sources")
    return project_map


def _scan_commit(project_id: str, commit_sha: str, settings: dict | None = None) -> ProjectMap:
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
        return _scan_materialized_project(checkout_path, settings)


async def _scan_pinned_project(
    store: Store,
    *,
    org_id: str,
    project_id: str,
    commit_sha: str,
    settings: dict | None = None,
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
            return _scan_materialized_project(checkout_path, settings)
    try:
        return _scan_commit(project_id, commit_sha, settings)
    except DashboardSemanticError as original:
        # Older dashboard versions store a real Git commit rather than a
        # workspace snapshot reference. Rehydrate the replaceable GitHub
        # mirror lazily so those versions survive gateway replacement too.
        if await hydrate_github_mirror(
            store.session,
            org_id=org_id,
            project_id=project_id,
        ):
            return _scan_commit(project_id, commit_sha, settings)
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
        if connection is None:
            raise DashboardSemanticError(
                "The project connection is unavailable",
                code="connection_missing",
            )
        try:
            get_connector_registration(connection.db_type)
        except ValueError as exc:
            raise DashboardSemanticError(
                "The project uses an unknown database connection type",
                code="connection_type_unknown",
            ) from exc
        # Credential readiness must be rechecked even when schema metadata is
        # cached; an open authoring session cannot outlive credential removal.
        connection_string = await store.get_connection_string(connection_name)
        if not connection_string:
            raise DashboardSemanticError(
                "The project connection credentials are unavailable",
                code="credentials_missing",
            )
        physical_schema = schema_cache.get(connection_name)
        if physical_schema is None:
            extras = await store.get_credential_extras(connection_name)
            try:
                async with pool_manager.connection(
                    connection.db_type,
                    connection_string,
                    credential_extras=extras,
                    connection_name=connection_name,
                ) as connector:
                    physical_schema = await connector.get_schema()
            except Exception as exc:
                raise DashboardSemanticError(
                    "The project database schema is unavailable",
                    code="schema_unavailable",
                ) from exc
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
            settings=project.settings,
        )
        from gateway.api.schema._semantic_store import _load_semantic_model

        context = resolve_from_authorities(
            project_id=project.id,
            commit_sha=commit_sha,
            connection_name=connection_name,
            connection_type=connection.db_type,
            project_map=project_map,
            physical_schema=physical_schema,
            semantic_model=_load_semantic_model(connection_name),
        )
        if not context.explores:
            raise DashboardSemanticError("The pinned dbt project has no governed explores for this connection")
        return context
