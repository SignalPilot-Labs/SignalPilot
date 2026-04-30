"""DuckDB utility helpers used by the evaluator and post-processors."""

from __future__ import annotations

from pathlib import Path

_EXCLUDE_SUFFIXES = ("_locked", "_bak", "_backup")


def find_result_db(project_dir: Path, expected_name: str | None = None) -> Path | None:
    """Return the best candidate result DuckDB file in project_dir.

    Filters out locked/backup files, then prefers the file matching expected_name
    (if given), otherwise returns the largest file by size.
    """
    candidates = [
        p for p in project_dir.glob("*.duckdb")
        if not any(s in p.name.lower() for s in _EXCLUDE_SUFFIXES)
    ]
    if not candidates:
        return None
    if expected_name is not None:
        for p in candidates:
            if p.name == expected_name:
                return p
    return max(candidates, key=lambda p: p.stat().st_size)


def get_table_row_count(db_path: str, table_name: str) -> int | None:
    """Return SELECT COUNT(*) for table_name, or None on error."""
    import duckdb

    try:
        con = duckdb.connect(database=db_path, read_only=True)
        try:
            result = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
            return int(result[0]) if result is not None else None
        finally:
            con.close()
    except Exception:
        return None


def sample_table_values(db_path: str, table_name: str, n: int = 5) -> list[dict] | None:
    """Return up to n rows from table as list of dicts, or None on error."""
    import duckdb

    try:
        con = duckdb.connect(database=db_path, read_only=True)
        try:
            rows = con.execute(f"SELECT * FROM {table_name} LIMIT {n}").fetchdf()
            return rows.to_dict(orient="records")
        finally:
            con.close()
    except Exception:
        return None


def get_table_row_counts(work_dir: Path) -> dict[str, int]:
    """Return {table_name: row_count} for every table in the workdir's DuckDB."""
    try:
        import duckdb
    except ImportError:
        return {}

    db_path_obj = find_result_db(work_dir)
    if not db_path_obj:
        return {}

    try:
        con = duckdb.connect(database=str(db_path_obj), read_only=True)
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        counts: dict[str, int] = {}
        for table in tables:
            row = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            if row is not None:
                counts[table] = int(row[0])
        con.close()
        return counts
    except Exception:
        return {}
