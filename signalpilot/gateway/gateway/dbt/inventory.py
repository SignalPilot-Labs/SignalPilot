"""
Project inventory assembly.

Takes the raw dict from scanner.scan_filesystem() and produces a ProjectMap.
The key job of this module is *reconciliation*: matching yml-defined models
to sql files by name, classifying each one, flagging orphans (sql with no
yml), and populating the ref graph.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .scanner import scan_filesystem
from .types import (
    ModelInfo,
    ModelStatus,
    ProjectMap,
    SourceInfo,
)
from .work_order import compute_work_order


def scan_project(project_dir: Path | str) -> ProjectMap:
    """Scan a dbt project directory and return a fully-assembled ProjectMap.

    This is the public entry point for the discovery layer. It composes
    scanner + inventory + work_order. Safe to call on broken, partial, or
    non-dbt directories — returns an empty map instead of raising.
    """
    project_dir = Path(project_dir)
    raw = scan_filesystem(project_dir)

    project_map = ProjectMap(
        project_name=raw["project_name"],
        project_dir=str(project_dir),
        project_yml_present=raw["project_yml_present"],
        profiles_yml_present=raw["profiles_yml_present"],
        packages_yml_present=raw["packages_yml_present"],
        packages=raw["packages"],
        parse_errors=raw["parse_errors"],
        scan_time_ms=raw["scan_ms"],
    )

    # Build index of sql records by model name for fast lookup during merge.
    sql_by_name: dict[str, dict[str, Any]] = {rec["name"]: rec for rec in raw["sql_records"]}
    sql_names_seen: set[str] = set()

    # Phase 1: for every yml-defined model, either pair it with its sql file
    # (if one exists) or mark it as MISSING.
    for yml_model in raw["yml_models"]:
        _merge_yml_with_sql(yml_model, sql_by_name, sql_names_seen)
        # If two yml entries declare the same name (rare but possible),
        # the second one wins — but we keep the earlier refs/columns if the
        # second one is sparser. Simple policy: last-write-wins on name collision.
        project_map.models[yml_model.name] = yml_model

    # Phase 2: any sql file whose stem did NOT appear in any yml is an orphan.
    for sql_name, sql_rec in sql_by_name.items():
        if sql_name in sql_names_seen:
            continue
        orphan = ModelInfo(
            name=sql_name,
            sql_path=sql_rec["path"],
            status=ModelStatus.ORPHAN,
            materialization=sql_rec.get("materialization"),
            unique_key=sql_rec.get("unique_key"),
            refs_sql=list(sql_rec.get("refs", [])),
            sources_sql=list(sql_rec.get("sources", [])),
            sql_size=sql_rec.get("size", 0),
            directory=sql_rec.get("directory", ""),
        )
        # If an orphan's sql was classified as a stub, downgrade ORPHAN → STUB
        # since the agent still has work to do on it. If it was complete, keep
        # the ORPHAN status as a flag that there's no yml contract.
        if sql_rec.get("status") == ModelStatus.STUB:
            orphan.status = ModelStatus.STUB
        project_map.models[sql_name] = orphan

    # Phase 3: sources
    for src in raw["yml_sources"]:
        _merge_source(src, project_map.sources)

    # Phase 4: macros (index by name, last write wins on duplicate names)
    for macro in raw["macros"]:
        project_map.macros[macro.name] = macro

    # Phase 5: work order + unresolved refs + cycle detection.
    known_models = set(project_map.models.keys())
    work_result = compute_work_order(project_map.models, known_models)
    project_map.work_order = work_result["order"]
    project_map.cycles = work_result["cycles"]
    project_map.unresolved_refs = work_result["unresolved"]

    project_map.date_hazards = raw.get("date_hazards", [])
    project_map.nondeterminism_warnings = raw.get("nondeterminism_warnings", [])

    return project_map


def _merge_yml_with_sql(
    yml_model: ModelInfo,
    sql_by_name: dict[str, dict[str, Any]],
    sql_names_seen: set[str],
) -> None:
    """In-place update of yml_model with matching sql data (if any).

    On a match:
    - yml_model.sql_path, sql_size, refs_sql, sources_sql, status filled in
    - materialization preferred from sql config if present, else yml config
    - unique_key preferred from yml tests (already set by scanner), else sql config
    """
    sql_rec = sql_by_name.get(yml_model.name)
    if sql_rec is None:
        yml_model.status = ModelStatus.MISSING
        return

    sql_names_seen.add(yml_model.name)
    yml_model.sql_path = sql_rec["path"]
    yml_model.sql_size = sql_rec.get("size", 0)
    yml_model.refs_sql = list(sql_rec.get("refs", []))
    yml_model.sources_sql = list(sql_rec.get("sources", []))
    yml_model.status = sql_rec.get("status", ModelStatus.COMPLETE)

    # Prefer the yml's directory for grouping so a staging yml groups with staging sql.
    if not yml_model.directory:
        yml_model.directory = sql_rec.get("directory", "")

    # Config precedence: sql `{{ config(...) }}` wins over yml config,
    # because dbt evaluates sql config at parse time and it's the authoritative value.
    sql_mat = sql_rec.get("materialization")
    if sql_mat:
        yml_model.materialization = sql_mat
    sql_uk = sql_rec.get("unique_key")
    if sql_uk and not yml_model.unique_key:
        yml_model.unique_key = sql_uk


def _merge_source(src: SourceInfo, sources: dict[str, SourceInfo]) -> None:
    """Merge a SourceInfo into the collection, handling duplicate source names.

    dbt allows the same source name to be split across multiple yml files,
    with each file contributing different tables. We union table lists.
    """
    existing = sources.get(src.name)
    if existing is None:
        sources[src.name] = src
        return
    # Union tables, prefer earlier metadata fields.
    for t in src.tables:
        if t not in existing.tables:
            existing.tables.append(t)
    for t, desc in src.table_descriptions.items():
        existing.table_descriptions.setdefault(t, desc)
    if not existing.schema and src.schema:
        existing.schema = src.schema
    if not existing.database and src.database:
        existing.database = src.database
    if not existing.description and src.description:
        existing.description = src.description
