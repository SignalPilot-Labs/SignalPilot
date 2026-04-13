"""Post-dbt-run DuckDB-level fixups: dedup tables on unique keys, add missing columns."""

from __future__ import annotations

from pathlib import Path

from ..core.logging import log, log_separator
from .scanner import extract_model_columns, extract_unique_keys


def dedup_eval_tables(
    work_dir: Path,
    eval_critical_models: set[str],
    result_db: "Path | None",
) -> None:
    """Deduplicate eval-critical tables that have a unique key defined in YML."""
    import duckdb

    if result_db is None:
        return

    unique_keys = extract_unique_keys(work_dir)
    log_separator("Dedup eval-critical tables on unique keys")

    con = duckdb.connect(str(result_db), read_only=False)
    try:
        for model in sorted(eval_critical_models):
            if model not in unique_keys:
                continue
            key_col = unique_keys[model]
            try:
                existing = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
                if model not in existing:
                    log(f"  {model}: table not found in result DB, skipping")
                    continue
                total = con.execute(f'SELECT COUNT(*) FROM "{model}"').fetchone()[0]
                distinct = con.execute(f'SELECT COUNT(DISTINCT "{key_col}") FROM "{model}"').fetchone()[0]
                if total == distinct:
                    log(f"  {model}: no duplicates on {key_col} ({total} rows)")
                else:
                    log(f"  DEDUP {model}: {total} rows -> {distinct} rows on key {key_col}")
                    con.execute(
                        f'CREATE OR REPLACE TABLE "{model}" AS '
                        f'SELECT * EXCLUDE(__rn) FROM ('
                        f'SELECT *, ROW_NUMBER() OVER (PARTITION BY "{key_col}" ORDER BY "{key_col}") AS __rn '
                        f'FROM "{model}") t WHERE __rn = 1'
                    )
            except Exception as e:
                log(f"  WARN: dedup failed for {model}: {e}", "WARN")
    finally:
        con.close()


_DERIVATION_PATTERNS = [
    ("hour_", "", "EXTRACT(HOUR FROM \"{base}\")::INTEGER"),
    ("", "_hour", "EXTRACT(HOUR FROM \"{base}\")::INTEGER"),
    ("day_of_week_", "", "EXTRACT(DOW FROM \"{base}\")::INTEGER"),
    ("day_of_", "", "EXTRACT(DOW FROM \"{base}\")::INTEGER"),
    ("", "_day_of_week", "EXTRACT(DOW FROM \"{base}\")::INTEGER"),
    ("week_", "", "EXTRACT(WEEK FROM \"{base}\")::INTEGER"),
    ("month_", "", "EXTRACT(MONTH FROM \"{base}\")::INTEGER"),
    ("year_", "", "EXTRACT(YEAR FROM \"{base}\")::INTEGER"),
    ("", "_date", "\"{base}\"::DATE"),
    ("date_", "", "\"{base}\"::DATE"),
]


def _try_derivation(
    con,
    model: str,
    missing_col: str,
    actual_cols: set[str],
) -> bool:
    """Try to derive missing_col from an existing column via common date/time patterns."""
    col_lower = missing_col.lower()
    for prefix, suffix, expr_template in _DERIVATION_PATTERNS:
        if prefix and col_lower.startswith(prefix):
            base_candidate = col_lower[len(prefix):]
        elif suffix and col_lower.endswith(suffix):
            base_candidate = col_lower[: -len(suffix)]
        else:
            continue

        if base_candidate not in actual_cols:
            continue

        base_actual_row = con.execute(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{model}' AND lower(column_name) = '{base_candidate}'"
        ).fetchone()
        base_col_name = base_actual_row[0] if base_actual_row else base_candidate

        derivation_expr = expr_template.replace("{base}", base_col_name)
        derivation_type = "DATE" if "_date" in expr_template else "INTEGER"

        con.execute(f'ALTER TABLE "{model}" ADD COLUMN "{missing_col}" {derivation_type}')
        con.execute(f'UPDATE "{model}" SET "{missing_col}" = {derivation_expr}')
        log(f'  ADD (derived) {model}.{missing_col} = {derivation_expr}')
        return True
    return False


def _try_cross_table_copy(
    con,
    model: str,
    missing_col: str,
    actual_cols: set[str],
) -> bool:
    """Try to copy missing_col from a sibling table via a shared join key."""
    col_lower = missing_col.lower()

    candidate_sources = con.execute(
        f"SELECT DISTINCT table_name FROM information_schema.columns "
        f"WHERE column_name = '{missing_col}' AND table_name != '{model}' "
        f"AND table_schema = 'main'"
    ).fetchall()

    def _source_score(name: str) -> tuple:
        n = name.lower()
        has_pk_mapping = 1 if f"{n}_id" in actual_cols else 0
        model_words = set(model.lower().replace("__", "_").split("_")) - {"", "stg", "int", "fct", "dim", "rpt"}
        source_words = set(n.replace("__", "_").split("_")) - {"", "stg", "int", "fct", "dim", "rpt", "tmp"}
        overlap = len(model_words & source_words)
        return (-has_pk_mapping, -overlap, len(n), n)

    candidate_list = sorted([r[0] for r in candidate_sources], key=_source_score)
    for source_table in candidate_list:
        if source_table.startswith("__dbt_"):
            continue

        source_cols_rows = con.execute(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{source_table}' AND table_schema = 'main'"
        ).fetchall()
        source_cols = {r[0].lower() for r in source_cols_rows}

        shared_keys = (actual_cols & source_cols) - {col_lower}
        join_key_src = None
        join_key_model = None
        if "id" in source_cols:
            candidate_model_key = f"{source_table.lower()}_id"
            if candidate_model_key in actual_cols:
                join_key_src = "id"
                join_key_model = candidate_model_key
        if join_key_src is None:
            id_keys = {k for k in shared_keys if k == "id" or k.endswith("_id") or k.endswith("_key")}
            if id_keys:
                join_key_src = join_key_model = min(id_keys)
        if join_key_src is None:
            continue

        col_type_row = con.execute(
            f"SELECT data_type FROM information_schema.columns "
            f"WHERE table_name = '{source_table}' AND column_name = '{missing_col}'"
        ).fetchone()
        if col_type_row is None:
            continue
        col_type = col_type_row[0]

        con.execute(f'ALTER TABLE "{model}" ADD COLUMN "{missing_col}" {col_type}')
        con.execute(
            f'UPDATE "{model}" SET "{missing_col}" = ('
            f'SELECT src."{missing_col}" FROM "{source_table}" src '
            f'WHERE src."{join_key_src}" = "{model}"."{join_key_model}" LIMIT 1)'
        )
        log(f'  ADD (joined from {source_table} on {join_key_src}={join_key_model}) {model}.{missing_col}')
        return True
    return False


def add_missing_columns(
    work_dir: Path,
    eval_critical_models: set[str],
    result_db: "Path | None",
) -> None:
    """Add columns listed in YML but absent from the result DB table.

    Strategies: derivation from date/time fields, cross-table join copy, or NULL
    placeholder for Fivetran sentinel columns.
    """
    import duckdb

    if result_db is None:
        return

    model_columns = extract_model_columns(work_dir)
    log_separator("Add missing YML columns to eval-critical tables")

    con = duckdb.connect(str(result_db), read_only=False)
    try:
        for model in sorted(eval_critical_models):
            try:
                if model not in model_columns:
                    log(f"  {model}: not found in YML column map, skipping")
                    continue

                existing_tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
                if model not in existing_tables:
                    log(f"  {model}: table not found in result DB, skipping")
                    continue

                yml_cols = model_columns[model]
                actual_cols_rows = con.execute(
                    f"SELECT column_name FROM information_schema.columns WHERE table_name = '{model}'"
                ).fetchall()
                actual_cols = {r[0].lower() for r in actual_cols_rows}

                missing_cols = [c for c in yml_cols if c.lower() not in actual_cols]
                for meta_col in ("_fivetran_synced", "_fivetran_deleted"):
                    if meta_col not in actual_cols and meta_col not in [c.lower() for c in missing_cols]:
                        has_meta = con.execute(
                            f"SELECT COUNT(*) FROM information_schema.columns "
                            f"WHERE column_name = '{meta_col}' AND table_name != '{model}' "
                            f"AND table_schema = 'main'"
                        ).fetchone()[0]
                        if has_meta > 0:
                            missing_cols.append(meta_col)
                if not missing_cols:
                    log(f"  {model}: all YML columns present")
                    continue

                for missing_col in missing_cols:
                    col_lower = missing_col.lower()

                    if _try_derivation(con, model, missing_col, actual_cols):
                        continue

                    if _try_cross_table_copy(con, model, missing_col, actual_cols):
                        continue

                    if col_lower in ("_fivetran_synced", "_fivetran_deleted"):
                        con.execute(f'ALTER TABLE "{model}" ADD COLUMN "{missing_col}" TIMESTAMP')
                        con.execute(f'UPDATE "{model}" SET "{missing_col}" = NULL')
                        log(f'  ADD (null placeholder) {model}.{missing_col}')
                        continue

                    log(f'  SKIP {model}.{missing_col}: no derivation or source found')

            except Exception as e:
                log(f"  WARN: add_missing_columns failed for {model}: {e}", "WARN")
    finally:
        con.close()
