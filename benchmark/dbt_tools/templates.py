"""Create starter SQL files and ephemeral stubs for missing ref() targets."""

from __future__ import annotations

import re
from pathlib import Path

from ..core.logging import log
from .scanner import SKIP_DIRS, classify_sql_models, extract_model_columns


def create_sql_templates(work_dir: Path, _eval_critical_models: set[str] | None = None) -> list[str]:
    """Pre-populate starter SQL files for YML-defined models with no existing SQL file.

    Only creates files for models with no SQL file at all — does not overwrite
    stubs or complete models. Returns a list of model names for which templates
    were created.
    """
    from .scanner import scan_yml_models
    complete_sql_models, stub_sql_models = classify_sql_models(work_dir)
    column_map = extract_model_columns(work_dir)
    already_have_sql = complete_sql_models | stub_sql_models

    yml_models = scan_yml_models(work_dir)
    models_to_template = yml_models - already_have_sql

    models_dir = work_dir / "models"
    target_dir = models_dir if models_dir.exists() else work_dir

    created: list[str] = []
    for model_name in models_to_template:
        if model_name in already_have_sql:
            continue
        try:
            columns = column_map.get(model_name, [])
            col_comment = ", ".join(columns) if columns else "(check schema.yml)"
            # Template must NOT compile — forces agent to rewrite the entire file
            template = (
                "{{ config(materialized='table') }}\n\n"
                f"-- REQUIRED OUTPUT COLUMNS: {col_comment}\n"
                "-- TODO: Write the complete SQL query for this model.\n"
                "-- Explore source tables with SignalPilot tools before writing.\n"
                "-- This file intentionally fails compilation until you replace it.\n"
                "SELECT_REPLACE_THIS_ENTIRE_FILE\n"
            )
            sql_path = target_dir / f"{model_name}.sql"
            sql_path.write_text(template)
            created.append(model_name)
        except Exception as exc:
            log(f"Warning: could not create SQL template for {model_name!r}: {exc}", "WARN")

    if created:
        log(f"Created {len(created)} SQL template(s): {sorted(created)}")
    return created


def detect_precomputed_tables(work_dir: Path) -> list[str]:
    """List tables already present in the task's .duckdb file."""
    try:
        import duckdb
    except ImportError:
        return []

    from ..evaluation.db_utils import find_result_db

    db_path_obj = find_result_db(work_dir)
    if not db_path_obj:
        return []

    try:
        con = duckdb.connect(database=str(db_path_obj), read_only=True)
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        con.close()
        return tables
    except Exception:
        return []


def create_ephemeral_stubs(work_dir: Path) -> list[str]:
    """Auto-create ephemeral stub SQL files for ref() targets that are raw DuckDB tables.

    Scans all .sql files under models/ for {{ ref('...') }} calls, then for any
    ref target that has no corresponding .sql file but does exist as a raw DuckDB
    table, writes a minimal ephemeral stub so dbt compilation succeeds without
    wasting agent turns on avoidable errors.
    """
    existing_sql_stems: set[str] = set()
    for sql_file in work_dir.rglob("*.sql"):
        if any(skip in str(sql_file) for skip in SKIP_DIRS):
            continue
        existing_sql_stems.add(sql_file.stem)

    ref_pattern = re.compile(r'\{\{\s*ref\(\s*[\'\"]([\w]+)[\'\"]\s*\)\s*\}\}')
    ref_targets: set[str] = set()
    models_dir = work_dir / "models"
    scan_root = models_dir if models_dir.exists() else work_dir
    for sql_file in scan_root.rglob("*.sql"):
        if any(skip in str(sql_file) for skip in SKIP_DIRS):
            continue
        try:
            content = sql_file.read_text()
            ref_targets.update(ref_pattern.findall(content))
        except Exception:
            pass

    unresolved = ref_targets - existing_sql_stems
    if not unresolved:
        return []

    duckdb_tables: set[str] = set(detect_precomputed_tables(work_dir))

    target_dir = models_dir if models_dir.exists() else work_dir
    created: list[str] = []
    for name in unresolved:
        if name not in duckdb_tables:
            continue
        target_path = target_dir / f"{name}.sql"
        if target_path.exists():
            continue
        stub_content = "{{ config(materialized='ephemeral') }}\n" + f"select * from main.{name}\n"
        try:
            target_path.write_text(stub_content)
            created.append(name)
        except Exception as exc:
            log(f"Warning: could not create ephemeral stub for {name!r}: {exc}", "WARN")

    return created
