"""Build a SQLite database from Spider2-Lite DDL.csv + JSON data files.

Spider2-Lite stores SQLite database schemas as:
- resource/databases/sqlite/{db_name}/DDL.csv  — CSV with columns `table_name,DDL`
- resource/databases/sqlite/{db_name}/{table_name}.json — JSON with `sample_rows`, etc.

There are no pre-built .sqlite files; this module creates them on demand.
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from pathlib import Path

from .logging import log

# SQLite reserved keywords that are legal column names in other databases but
# cause syntax errors in SQLite DDL without quoting.
_SQLITE_RESERVED_KEYWORDS: frozenset[str] = frozenset({
    "abort", "action", "add", "after", "all", "alter", "always", "analyze",
    "and", "as", "asc", "attach", "autoincrement", "before", "begin",
    "between", "by", "cascade", "case", "cast", "check", "collate", "column",
    "commit", "conflict", "constraint", "create", "cross", "current",
    "current_date", "current_time", "current_timestamp", "database", "default",
    "deferrable", "deferred", "delete", "desc", "detach", "distinct", "do",
    "drop", "each", "else", "end", "escape", "except", "exclude", "exists",
    "explain", "fail", "filter", "first", "following", "for", "foreign",
    "from", "full", "generated", "glob", "group", "groups", "having", "if",
    "ignore", "immediate", "in", "index", "indexed", "initially", "inner",
    "insert", "instead", "intersect", "into", "is", "isnull", "join", "key",
    "last", "left", "like", "limit", "match", "materialized", "natural", "no",
    "not", "nothing", "notnull", "null", "nulls", "of", "offset", "on", "or",
    "order", "others", "outer", "over", "partition", "plan", "pragma",
    "preceding", "primary", "query", "raise", "range", "recursive", "references",
    "regexp", "reindex", "release", "rename", "replace", "restrict", "returning",
    "right", "rollback", "row", "rows", "savepoint", "select", "set", "table",
    "temp", "temporary", "then", "ties", "to", "transaction", "trigger",
    "unbounded", "union", "unique", "update", "using", "vacuum", "values",
    "view", "virtual", "when", "where", "window", "with", "without",
})

# Matches a column definition line: leading whitespace, identifier, then type/constraint.
_COLUMN_DEF_RE = re.compile(r"^(\s+)(\w+)(\s+\S.*)", re.MULTILINE)

# SQLite internal tables that must never be created explicitly.
_SQLITE_INTERNAL_TABLES: frozenset[str] = frozenset({
    "sqlite_sequence",
    "sqlite_stat1",
    "sqlite_stat2",
    "sqlite_stat3",
    "sqlite_stat4",
    "sqlite_master",
})


def build_sqlite_db(db_name: str, resource_dir: Path, output_path: Path) -> Path:
    """Build a SQLite database from DDL.csv and JSON data files.

    Args:
        db_name: Name of the database (matches a subdirectory under resource_dir).
        resource_dir: Path to the resource/databases/sqlite/ directory.
        output_path: Destination path for the .sqlite file.

    Returns:
        Path to the created .sqlite file.

    Raises:
        FileNotFoundError: If DDL.csv is missing for db_name.
        RuntimeError: If any CREATE TABLE or INSERT fails.
    """
    db_dir = resource_dir / db_name
    ddl_csv_path = db_dir / "DDL.csv"

    if not ddl_csv_path.exists():
        raise FileNotFoundError(f"DDL.csv not found for database '{db_name}': {ddl_csv_path}")

    # Remove stale database if it exists
    if output_path.exists():
        output_path.unlink()

    conn = sqlite3.connect(str(output_path))
    try:
        _create_tables(conn, ddl_csv_path, db_name)
        _insert_sample_rows(conn, db_dir, db_name)
        conn.commit()
    except Exception:
        conn.close()
        if output_path.exists():
            output_path.unlink()
        raise
    else:
        conn.close()

    log(f"Built SQLite database '{db_name}' -> {output_path}")
    return output_path


def _quote_reserved_column_names(ddl: str) -> str:
    """Double-quote column names that are SQLite reserved keywords.

    Only affects column definition lines (indented identifier followed by a type).
    Does not touch table names, constraint keywords, or type names.
    """

    def _quote_if_reserved(match: re.Match[str]) -> str:
        indent = match.group(1)
        identifier = match.group(2)
        rest = match.group(3)
        if identifier.lower() in _SQLITE_RESERVED_KEYWORDS:
            return f'{indent}"{identifier}"{rest}'
        return match.group(0)

    return _COLUMN_DEF_RE.sub(_quote_if_reserved, ddl)


def _create_tables(conn: sqlite3.Connection, ddl_csv_path: Path, db_name: str) -> None:
    """Execute all CREATE TABLE statements from DDL.csv."""
    with ddl_csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            table_name: str = row["table_name"]
            if table_name.lower() in _SQLITE_INTERNAL_TABLES:
                log(f"[{db_name}] Skipping internal table '{table_name}'")
                continue
            ddl: str = _quote_reserved_column_names(row["DDL"])
            try:
                conn.execute(ddl)
                log(f"[{db_name}] Created table '{table_name}'")
            except sqlite3.Error as exc:
                raise RuntimeError(
                    f"CREATE TABLE failed for '{table_name}' in db '{db_name}': {exc}\nDDL: {ddl}"
                ) from exc


def _insert_sample_rows(conn: sqlite3.Connection, db_dir: Path, db_name: str) -> None:
    """Insert sample rows from {table_name}.json files into the database."""
    for json_path in sorted(db_dir.glob("*.json")):
        table_name = json_path.stem
        if table_name.lower() in _SQLITE_INTERNAL_TABLES:
            log(f"[{db_name}] Skipping internal table '{table_name}' (no insert)")
            continue
        _insert_table_rows(conn, json_path, table_name, db_name)


def _insert_table_rows(
    conn: sqlite3.Connection,
    json_path: Path,
    table_name: str,
    db_name: str,
) -> None:
    """Insert rows from a single JSON file into the named table."""
    with json_path.open(encoding="utf-8") as fh:
        data = json.load(fh)

    sample_rows = data.get("sample_rows")
    if not sample_rows:
        log(f"[{db_name}] No sample_rows for table '{table_name}' — skipping")
        return

    columns = list(sample_rows[0].keys())
    placeholders = ", ".join("?" for _ in columns)
    col_list = ", ".join(f'"{col}"' for col in columns)
    sql = f'INSERT INTO "{table_name}" ({col_list}) VALUES ({placeholders})'

    rows_inserted = 0
    for row_dict in sample_rows:
        values = tuple(row_dict.get(col) for col in columns)
        try:
            conn.execute(sql, values)
            rows_inserted += 1
        except sqlite3.Error as exc:
            raise RuntimeError(
                f"INSERT failed for table '{table_name}' in db '{db_name}': {exc}\nRow: {row_dict}"
            ) from exc

    log(f"[{db_name}] Inserted {rows_inserted} rows into '{table_name}'")
