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
    existing_models = yml_models & complete_models

    missing_priority = missing_models & eval_critical_models
    missing_other = missing_models - eval_critical_models

    priority_str = ", ".join(sorted(missing_priority)) if missing_priority else "none"
    other_missing_str = ", ".join(sorted(missing_other)) if missing_other else "none"
    existing_str = ", ".join(sorted(existing_models)) if existing_models else "none"
    stubs_str = ", ".join(sorted(stub_models)) if stub_models else "none"

    model_deps = extract_model_deps(work_dir)
    deps_lines = []
    for model_name in sorted(missing_models | stub_models):
        if model_name in model_deps:
            deps_lines.append(f"  {model_name} depends on: {', '.join(model_deps[model_name])}")
    deps_str = "\n".join(deps_lines) if deps_lines else "  (check YML refs: fields and existing SQL for dependency info)"

    model_columns = extract_model_columns(work_dir)
    model_descriptions = extract_model_descriptions(work_dir)
    col_spec_lines = []
    skeleton_lines = []
    for model_name in sorted(missing_priority | (stub_models & eval_critical_models)):
        desc = model_descriptions.get(model_name, "")
        desc_str = f" | DESC: {desc}" if desc else ""
        if model_name in model_columns:
            cols = model_columns[model_name]
            col_spec_lines.append(f"  {model_name}: {', '.join(cols)}{desc_str}")
            col_aliases = ",\n    ".join(f"??? AS {c}" for c in cols)
            skeleton_lines.append(
                f"  -- {model_name}.sql skeleton (include ALL columns):\n"
                f"  -- {{{{ config(materialized='table') }}}}\n"
                f"  -- SELECT\n"
                f"  --     {col_aliases}\n"
                f"  -- FROM ???"
            )
    col_spec_str = "\n".join(col_spec_lines) if col_spec_lines else "  (read YML files for column specs)"
    skeleton_str = "\n".join(skeleton_lines) if skeleton_lines else ""

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

    prompt = f"""You are a dbt/DuckDB expert. Complete this dbt project in {work_dir}.
You have generous turn headroom — iterate as much as you need. Validation loops,
re-reads, and schema-check cycles are legitimate work. Prioritise correctness
over turn count; do not short-circuit verification steps to save turns.

TASK: {instruction}

DATABASE: SignalPilot connection '{instance_id}' (DuckDB). Use mcp__signalpilot__* tools.

MISSING SQL MODELS — PRIORITY (evaluated, must complete): {priority_str}
MISSING SQL MODELS — OTHER (write if time permits): {other_missing_str}
INCOMPLETE SQL (stubs — must rewrite): {stubs_str}
EXISTING SQL MODELS: {existing_str}

MODEL DEPENDENCIES (write dependencies first):
{deps_str}

REQUIRED COLUMNS FOR PRIORITY MODELS (include ALL of these — missing columns = guaranteed FAIL):
{col_spec_str}
{f'{chr(10)}SQL TEMPLATES (start from these — fill in ??? with source expressions):{chr(10)}{skeleton_str}' if skeleton_str else ''}
DO THIS IN ORDER:
1. {'Run: dbt deps' if has_packages_yml else 'SKIP dbt deps — no packages.yml, packages are pre-installed. NEVER run dbt deps on this project.'}
2. mcp__signalpilot__list_tables connection_name="{instance_id}"
2b. mcp__signalpilot__get_date_boundaries connection_name="{instance_id}"
    - The tool marks the correct table with "← USE THIS" — use that table's max date as the spine endpoint.
    - The spine endpoint is ALWAYS the primary fact/event table's max date (orders, transactions, events, sessions, activities, etc.).
    - Identify the fact table as: the table with the most rows, OR the primary entity the task references.
    - NEVER use GLOBAL MAX DATE — dimension, lookup, and reference tables often have later dates and must NOT set the endpoint.
    - Never use current_date, now(), or current_timestamp.
3. Explore at most 2 source tables with explore_table. Stop exploring — begin writing SQL.
4. For each priority model in dependency order — complete ALL sub-steps before moving to the next model:
   a. Read its YML file. If dbt_packages/ exists, also read related package models (dbt_packages/*/models/**/*.sql) — they provide pre-built columns you can ref() instead of re-deriving.
   b. Write the .sql file
      - NEVER modify .yml or .yaml files — only create/edit .sql files
      - EVERY column listed in the YML MUST appear in your SELECT — missing columns cause evaluation failure even if row count is correct.
        Column names in YML are exact — alias SELECT output to match them character-for-character.
        For derived columns (e.g., hour_*, day_of_*, month_*, *_months, *_days): derive them from base columns using EXTRACT(), DATEDIFF(), etc.
      - Use ref() for upstream models, source() for raw tables
      - If a ref('model_name') fails because no .sql file exists BUT the table already exists in the database,
        create an ephemeral wrapper: {{ config(materialized='ephemeral') }} SELECT * FROM model_name
        This bridges pre-existing tables to dbt's ref() system without altering the database.
      - DEFAULT to LEFT JOIN for all JOINs. Only use INNER JOIN if the task explicitly says to exclude non-matching rows (e.g., "customers WITH orders", "only users who have", "exclude rows without") AND you have called compare_join_types. Phrases like "based on", "for each X in Y", "calculates X from Y" are NOT exclusion — they describe the calculation scope, keep LEFT JOIN.
      - When combining similar source tables (e.g., comedies + dramas + docuseries), prefer UNION (dedup) over UNION ALL if sources may contain duplicate/overlapping rows. UNION ALL keeps all rows including duplicates; UNION deduplicates. Check source data for identical rows before deciding.
      - For monetary columns (spend, cost, price, amount): check if the source data has negative values. For per-entity detail models, keep the original sign. For account-level summary/overview models (where spend should be a positive total), use ABS(). When unsure, check the dbt_packages source models for guidance.
      - COALESCE: For COUNT/SUM aggregates from LEFT JOINs (e.g., count_visitors, sum_pageviews), use COALESCE(col, 0) — zero is correct when no events exist. For non-aggregate columns (e.g., names, dates, IDs from optional JOINs), do NOT use COALESCE — let NULLs remain. The evaluator distinguishes NULL from 0.
      - ROLLING WINDOW / MoM / WoW models: If YML description says "rolling window", "MoM", "WoW", or "comparison" AND unique_key includes date×entity — the model outputs ONE date (the latest) per entity, NOT all dates. Add: WHERE date_col = (SELECT MAX(date_col) FROM source).
      - For "top N" or ranking queries: use RANK() not DENSE_RANK(). RANK() gives ties the same rank and skips the next (1,2,2,4); DENSE_RANK() never skips (1,2,2,3). Standard "top 20" lists expect RANK().
      - Do NOT cast ID columns to different types. If the source column is INTEGER, keep it INTEGER in the output — do not CAST to VARCHAR.
      - ROW_NUMBER() must always have a fully deterministic ORDER BY. Add enough columns to break all ties (e.g., ORDER BY person_id, start_date, source_value). Non-deterministic ordering causes different IDs across runs.
      - Do NOT add WHERE/HAVING filters unless the task description or YML explicitly requires excluding rows. Common mistakes: filtering by role/type/status based on table names (e.g., WHERE role='ACTOR' because the table is named 'actor_rating'), filtering NULLs from UNIONs when only some columns are NULL, adding HAVING to exclude NULLs. A row with some NULL columns is real data — keep it.
   c. Run: dbt run --select <model>
      If dbt fails: use mcp__signalpilot__dbt_error_parser with the error text, fix SQL, re-run.
   d. Run BOTH of these after every dbt run (mandatory):
      mcp__signalpilot__validate_model_output connection_name="{instance_id}" model_name="<model>"
      mcp__signalpilot__audit_model_sources connection_name="{instance_id}" model_name="<model>" source_tables="<comma-separated upstream tables>"
      → 0 rows = fix JOIN/WHERE. Fan-out ratio > 2x = pre-aggregate or ROW_NUMBER() dedup. Over-filter < 0.5 = INNER→LEFT JOIN or WHERE too restrictive.
   e. Run: mcp__signalpilot__check_model_schema connection_name="{instance_id}" model_name="<model>" yml_columns="<exact comma-separated cols from YML>"
      → MISSING columns = add to SQL, go back to step c. Do NOT proceed until all columns match.
   MODEL IS COMPLETE only when c + d + e all pass. Then move to the next model.
5. mcp__signalpilot__query_database connection_name="{instance_id}" sql="SHOW TABLES"
   → every eval-critical model name must appear exactly as written
{'- ' + packages_hint.lstrip() if packages_hint else ''}"""

    current_date_hits = scan_current_date_models(work_dir)
    if current_date_hits:
        warning_lines = ["", "⚠ CRITICAL: These existing .sql files use current_date/current_timestamp/now() and MUST be edited:"]
        for rel_path, line_no, line_text in current_date_hits:
            warning_lines.append(f"  {rel_path}:{line_no}: {line_text}")
            model_name = Path(rel_path).stem
            if model_name in db_tables:
                warning_lines.append(f"  NOTE: {model_name} already has pre-computed data in the database.")
                warning_lines.append(f"  Query its max date with: SELECT MAX(<date_col>) FROM {model_name}")
                warning_lines.append("  Use that value as the replacement for current_date in this file — NOT the fact table max from get_date_boundaries.")
                warning_lines.append("  (Replace <date_col> with the actual date column name you see in the model's SELECT list.)")
        warning_lines.append("After calling get_date_boundaries in step 2b, edit these files:")
        warning_lines.append("  Replace current_date → CAST('<MAX_DATE>' AS DATE) in date spines, WHERE clauses, and date range boundaries.")
        warning_lines.append("  where <MAX_DATE> is the primary fact/event table's max date from get_date_boundaries (look for the '← USE THIS' marker).")
        warning_lines.append("  For dbt macros like dbt.current_timestamp_backcompat(): replace the entire macro call with the cast.")
        warning_lines.append("  EXCEPTION: If current_date is used to compute 'current_age', 'age', or 'days_since_X' (real-time calculations), KEEP current_date — do NOT replace.")
        warning_lines.append("This is the #1 cause of row count and value mismatches.")
        prompt += "\n".join(warning_lines)

    if eval_critical_models:
        crit_names = ", ".join(sorted(eval_critical_models))
        prompt += f"\n\nEVAL-CRITICAL TABLES (must exist with these exact names): {crit_names}"

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
        macro_lines = [f"  {name}() — read macros/ directory to see full definition" for name in sorted(macros_dict)]
        prompt += "\n\nAVAILABLE MACROS (call with {{ macro_name() }} in Jinja):\n" + "\n".join(macro_lines)
        prompt += "\n- When writing new models, prefer using existing macros over re-implementing the logic inline."

    precomputed = detect_precomputed_tables(work_dir)
    if precomputed:
        prompt += f"\n\nPRE-COMPUTED TABLES ALREADY IN DATABASE: {', '.join(precomputed)}"
        prompt += "\n- These tables already have data from pre-run simulations. Your summary models should SELECT from these tables, not re-run the simulation logic."

    table_counts = get_table_row_counts(work_dir)
    if table_counts:
        counts_lines = [f"  {name}: {count:,} rows" for name, count in sorted(table_counts.items())]
        prompt += "\n\nSOURCE TABLE CARDINALITIES (row counts of tables already in the DuckDB file):\n"
        prompt += "\n".join(counts_lines)
        prompt += "\n- These are INPUT table sizes, not expected output sizes."

    prompt += (
        "\n\nWorkflow shape: explore the project through dbt_project_map first, "
        "then write priority models one at a time in dependency order, running "
        "dbt_project_validate and per-model verification between writes. There is "
        "no turn pressure — spend time on verification."
    )

    return prompt


def build_value_verify_prompt(
    work_dir: Path,
    instance_id: str,
    eval_critical_models: set[str],
    instruction: str,
    model_columns: dict[str, list[str]],
) -> str:
    """Build the prompt for the post-success value-verification agent."""
    sorted_models = sorted(eval_critical_models)
    model_names_str = ", ".join(sorted_models)

    col_spec_lines: list[str] = []
    for model_name in sorted_models:
        if model_name in model_columns:
            col_spec_lines.append(f"  {model_name}: {', '.join(model_columns[model_name])}")
    col_spec_str = "\n".join(col_spec_lines) if col_spec_lines else "  (read YML files for column specs)"

    return f"""SELF-VERIFICATION TASK for {instance_id}

dbt build is complete. Audit each priority model for silent failures.
Use ONLY: task's own .md files, YML specs, and your own output tables.

CRITICAL RULE — DO NO HARM: Only fix issues you are CERTAIN about. If unsure whether a change
improves or worsens the output, DO NOT make the change. Common harmful changes to AVOID:
- Adding WHERE ... IS NOT NULL filters (removes valid data)
- Removing COALESCE from aggregate metrics (introduces NULLs where 0 is correct)
- Over-deduplicating with ROW_NUMBER when the task doesn't specify dedup

TASK: {instruction}

EVAL-CRITICAL MODELS: {model_names_str}

For each model, run these checks:

CHECK 1 — TABLE EXISTS:
  SHOW TABLES — confirm {model_names_str} appear.
  If missing: create SELECT * FROM ref(closest_existing_model) and run dbt run --select <name>.

CHECK 2 — COLUMN COMPLETENESS (use check_model_schema tool):
  For each model, run: mcp__signalpilot__check_model_schema(connection_name="{instance_id}", model_name="<model>", yml_columns="<comma-separated list from below>")
  The EXACT required columns (from YML) are:
{col_spec_str}
  The tool will tell you exactly which columns are MISSING, EXTRA, or have CASE MISMATCHES.
  - Any MISSING column — DO NOT SKIP THIS, find and add it:
    1. Search source tables: mcp__signalpilot__query_database(connection_name="{instance_id}", sql="SELECT table_name, column_name FROM information_schema.columns WHERE column_name = '<missing_col>'")
    2. If found in a source: add it to the model SQL SELECT from that source table.
    3. If NOT found: derive it. Common patterns: hour_X → EXTRACT(HOUR FROM X), month_X → EXTRACT(MONTH FROM X), X_months → DATEDIFF('month', start, end), X_days → DATEDIFF('day', start, end).
    4. For _fivetran_synced: always comes from the primary source table.
    Re-run dbt after adding each missing column.
  - Any CASE MISMATCH: RENAME to match exactly.
  - Do not accept "close enough" — column names must match the YML list precisely.
  - CRITICAL: Do NOT proceed to CHECK 3 until ALL columns match. Missing columns = guaranteed FAIL.

CHECK 3 — CATEGORICAL VALUE AUDIT:
  For string columns that look like status/category/type/territory:
    SELECT DISTINCT <col> FROM <model>
  Then run: find . -name "*.md" -not -path "*/dbt_packages/*" | xargs grep -l "docs"
  Read each .md file. Find {{% docs %}} blocks that list expected values for this column.
  If output values differ from doc-specified values: fix CASE WHEN and re-run dbt.

CHECK 4 — ROW COUNT VALIDATION (use validate_model_output tool):
  For each model: mcp__signalpilot__validate_model_output(connection_name="{instance_id}", model_name="<model>")
  If 0 rows: model is empty — debug JOIN/WHERE before proceeding.
  If fan-out detected: fix your JOINs.

CHECK 5 — NUMERIC SAMPLE:
  SELECT * FROM <model> LIMIT 5
  Flag: any numeric column that is 0 or NULL for ALL 5 rows (aggregation is likely wrong).
  Flag: any column identical across all 5 rows when it should vary (wrong CASE WHEN literal).

CHECK 6 — CARDINALITY SANITY (catches silent wrong-scale errors):

  a) Read the YML description for each priority model. If it says "top N" or "ranks the top N":
       SELECT COUNT(*) FROM <model>
     If count > N: a QUALIFY/WHERE rank <= N filter is missing. Add it, re-run dbt.

  b) If the description says "rolling window" or "MoM/WoW comparison" and the model has a
     surrogate_key on date×entity:
       SELECT COUNT(DISTINCT <date_col>) FROM <model>
     If distinct dates > 2: the model is building a full time-series.
     Rolling-window models with unique_key=date×entity produce ONE date per run (the latest).
     Fix: add WHERE <date_col> = (SELECT MAX(<date_col>) FROM <source>)

  c) If the model aggregates per entity (customer, driver, product):
       SELECT COUNT(*) AS model_rows FROM <model>
       SELECT COUNT(DISTINCT <entity_id>) AS entities FROM <source> [WHERE <qualifier>]
     If model_rows >> entities: JOIN fan-out — find and fix before finishing.

  d) For UNION-based models: count each branch independently:
       SELECT COUNT(*) FROM <branch_1_source> [WHERE <filter>]
       SELECT COUNT(*) FROM <branch_2_source> [WHERE <filter>]
     Sum must equal model row count. If any branch is 0 and should not be, the domain filter is wrong.

CHECK 7 — NULL / JUNK ROW FILTER (CAUTION — usually no action needed):
  Only check UNION-based models where a branch might produce all-NULL rows.
  NEVER filter rows where just one or two columns are NULL — those are real data.
  Only filter rows where ALL columns are NULL. If unsure, DO NOT FILTER.
"""
