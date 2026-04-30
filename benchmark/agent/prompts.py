"""Prompt builders for the main dbt agent and the post-run verification agent."""

from __future__ import annotations

from pathlib import Path

from ..dbt_tools.scanner import (
    classify_sql_models,
    extract_model_columns,
    extract_model_deps,
    extract_model_descriptions,
    scan_current_date_models,
    scan_macros,
    scan_yml_models,
)
from ..dbt_tools.templates import detect_precomputed_tables
from ..evaluation.db_utils import get_table_row_counts


def build_agent_prompt(
    instance_id: str,
    instruction: str,
    work_dir: Path,
    eval_critical_models: set[str],
    max_turns: int = 20,
) -> str:
    """Build a focused, action-oriented prompt for the Claude CLI agent."""
    yml_models = scan_yml_models(work_dir)
    complete_models, stub_models = classify_sql_models(work_dir)

    db_tables = set(detect_precomputed_tables(work_dir))

    sql_models = complete_models | stub_models
    missing_models = yml_models - sql_models
    # Split complete models: those materialized in DB vs those with SQL but no table
    materialized_models = (yml_models & complete_models) & db_tables
    unmaterialized_complete = (yml_models & complete_models) - db_tables

    missing_str = ", ".join(sorted(missing_models)) if missing_models else "none"
    existing_str = ", ".join(sorted(materialized_models)) if materialized_models else "none"
    stubs_str = ", ".join(sorted(stub_models)) if stub_models else "none"
    unmaterialized_str = ", ".join(sorted(unmaterialized_complete)) if unmaterialized_complete else ""

    model_deps = extract_model_deps(work_dir)
    deps_lines = []
    for model_name in sorted(missing_models | stub_models):
        if model_name in model_deps:
            deps_lines.append(f"  {model_name} depends on: {', '.join(model_deps[model_name])}")
    deps_str = "\n".join(deps_lines) if deps_lines else "  (check YML refs: fields and existing SQL for dependency info)"

    model_columns = extract_model_columns(work_dir)
    model_descriptions = extract_model_descriptions(work_dir)
    col_spec_lines = []
    for model_name in sorted(missing_models | stub_models):
        desc = model_descriptions.get(model_name, "")
        desc_str = f" | DESC: {desc}" if desc else ""
        if model_name in model_columns:
            cols = model_columns[model_name]
            col_spec_lines.append(f"  {model_name}: {', '.join(cols)}{desc_str}")
    col_spec_str = "\n".join(col_spec_lines) if col_spec_lines else "  (read YML files for column specs)"

    has_packages_yml = (work_dir / "packages.yml").exists()
    packages_hint = ""
    if has_packages_yml:
        pkg_stg_models = set()
        dbt_pkg_dir = work_dir / "dbt_packages"
        if dbt_pkg_dir.exists():
            for sql_file in dbt_pkg_dir.rglob("*.sql"):
                if sql_file.stem.startswith("stg_") or sql_file.stem.startswith("int_"):
                    pkg_stg_models.add(sql_file.stem)
        pkg_models_str = ", ".join(sorted(pkg_stg_models)[:20]) if pkg_stg_models else "check dbt_packages/"
        packages_hint = (
            f"\n- This project uses dbt packages with staging/intermediate models you can ref(): {pkg_models_str}"
            "\n- Run `dbt deps` first, then use ref('stg_model_name') for these package models"
        )

        existing_sql_uses_dbt_ns = False
        for sql_file in work_dir.rglob("*.sql"):
            if any(skip in str(sql_file) for skip in (".claude", "dbt_packages", "target")):
                continue
            try:
                if "dbt." in sql_file.read_text():
                    existing_sql_uses_dbt_ns = True
                    break
            except Exception:
                pass

        if existing_sql_uses_dbt_ns:
            packages_hint += (
                "\n- dbt.* cross-adapter macros ARE available (from dbt-core): dbt.date_trunc(), dbt.length(), dbt.replace(), etc."
                "\n- These are different from package macros — use them freely in SQL: {{ dbt.date_trunc('month', 'date_col') }}"
            )

    dbt_deps_note = "Run `dbt deps` first — this project has a packages.yml." if has_packages_yml else "Do NOT run `dbt deps` — packages are pre-installed."

    prompt = f"""TASK: {instruction}

{dbt_deps_note}

MODELS TO BUILD:
{missing_str}

STUBS TO REWRITE:
{stubs_str}

EXISTING COMPLETE MODELS (do not modify unless needed):
{existing_str}
{f'{chr(10)}COMPLETE BUT NOT MATERIALIZED (have SQL but no table — run dbt run --select to materialize):{chr(10)}{unmaterialized_str}{chr(10)}' if unmaterialized_str else ''}
DEPENDENCIES (build in this order):
{deps_str}

REQUIRED COLUMNS (must match exactly — missing columns = guaranteed fail):
{col_spec_str}

Follow the workflow in the system prompt. Load skills as directed.
{packages_hint}"""

    current_date_hits = scan_current_date_models(work_dir)
    if current_date_hits:
        warning_lines = ["", "⚠ FILES USING current_date (must fix — use fix_date_spine_hazards tool):"]
        for rel_path, line_no, line_text in current_date_hits:
            warning_lines.append(f"  {rel_path}:{line_no}: {line_text}")
            model_name = Path(rel_path).stem
            if model_name in db_tables:
                warning_lines.append(f"    (has pre-computed data — check its max date)")
        prompt += "\n".join(warning_lines)

    import yaml
    source_hints: list[str] = []
    for ext in ("*.yml", "*.yaml"):
        for yml_file in work_dir.rglob(ext):
            if any(skip in str(yml_file) for skip in (".claude", "dbt_packages", "target")):
                continue
            try:
                data = yaml.safe_load(yml_file.read_text())
                if data and "sources" in data:
                    for src in data["sources"]:
                        src_name = src.get("name", "")
                        tables = src.get("tables", [])
                        table_names = [t.get("name", "") for t in tables if isinstance(t, dict)]
                        if src_name and table_names:
                            source_hints.append(f"  source('{src_name}', '<table>') — tables: {', '.join(table_names)}")
            except Exception:
                pass

    source_str = "\n".join(source_hints) if source_hints else ""
    if source_str:
        prompt += f"\n\nAVAILABLE SOURCES:\n{source_str}"

    macros_dict = scan_macros(work_dir)
    if macros_dict:
        macro_lines = [f"  {name}()" for name in sorted(macros_dict)]
        prompt += "\n\nAVAILABLE MACROS:\n" + "\n".join(macro_lines)

    return prompt
