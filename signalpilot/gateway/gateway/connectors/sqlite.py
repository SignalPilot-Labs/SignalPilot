"""SQLite connector — aiosqlite-backed, for Spider2 benchmarking and local files."""

from __future__ import annotations

import sqlite3
from typing import Any

from .base import BaseConnector


class SQLiteConnector(BaseConnector):
    def __init__(self):
        super().__init__()
        self._conn: sqlite3.Connection | None = None
        self._db_path: str = ""

    @property
    def _identifier_quote(self) -> str:
        return "["

    async def connect(self, connection_string: str) -> None:
        # connection_string is the file path (or :memory:)
        self._db_path = connection_string
        try:
            self._conn = sqlite3.connect(connection_string)
            self._conn.row_factory = sqlite3.Row
            # Enable foreign keys (required for FK-related schema queries)
            self._conn.execute("PRAGMA foreign_keys = ON")
        except sqlite3.OperationalError as e:
            err_str = str(e).lower()
            if "unable to open" in err_str:
                raise RuntimeError(f"Cannot open database file: {connection_string}") from e
            if "not a database" in err_str or "file is not a database" in err_str:
                raise RuntimeError(f"File is not a valid SQLite database: {connection_string}") from e
            if "readonly" in err_str or "read-only" in err_str:
                raise RuntimeError(f"Database is read-only: {connection_string}") from e
            raise RuntimeError(f"SQLite connection error: {e}") from e
        except Exception as e:
            raise RuntimeError(f"SQLite connection error: {e}") from e

    def _ensure_connected(self) -> None:
        """Verify SQLite connection is alive; raise RuntimeError if lost."""
        if self._conn is None:
            raise RuntimeError("Not connected")
        try:
            self._conn.execute("SELECT 1")
        except Exception:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
            raise RuntimeError("Connection lost — please reconnect")

    async def _execute_impl(
        self, sql: str, params: list | None = None, timeout: int | None = None
    ) -> list[dict[str, Any]]:
        if self._conn is None:
            raise RuntimeError("Not connected")

        # SQLite timeout via progress handler — cancels after N seconds
        if timeout:
            import time

            start = time.monotonic()

            def _timeout_handler():
                if time.monotonic() - start > timeout:
                    return 1  # Non-zero cancels the operation
                return 0

            self._conn.set_progress_handler(_timeout_handler, 1000)

        try:
            cursor = self._conn.execute(sql, params or [])
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
            return [{col: row[i] for i, col in enumerate(columns)} for row in rows]
        except sqlite3.OperationalError as e:
            if "interrupted" in str(e).lower():
                raise RuntimeError(f"SQLite query timed out after {timeout}s") from e
            raise RuntimeError(f"SQLite query error: {e}") from e
        finally:
            if timeout:
                self._conn.set_progress_handler(None, 0)

    async def _get_schema_impl(self) -> dict[str, Any]:
        import time as _time

        if self._conn is None:
            raise RuntimeError("Not connected")
        _master_sql = (
            "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'"
        )
        t0 = _time.monotonic()
        cursor = self._conn.execute(_master_sql)
        table_rows = cursor.fetchall()
        await self._audit_sql(_master_sql.strip(), len(table_rows), (_time.monotonic() - t0) * 1000)
        tables = [row[0] for row in table_rows]
        table_type_map = {row[0]: row[1] for row in table_rows}

        # Batch row counts in a single query (avoids N per-table COUNT(*) queries)
        row_counts: dict[str, int] = {}
        if tables:
            # Build a UNION ALL query for all table counts at once
            count_parts = [
                f"SELECT '{t.replace(chr(39), chr(39) + chr(39))}' AS t, COUNT(*) AS c FROM [{t}]" for t in tables
            ]
            try:
                count_sql = " UNION ALL ".join(count_parts)
                t0 = _time.monotonic()
                count_rows = self._conn.execute(count_sql).fetchall()
                await self._audit_sql(count_sql.strip(), len(count_rows), (_time.monotonic() - t0) * 1000)
                for row in count_rows:
                    row_counts[row[0]] = row[1]
            except Exception:
                pass  # Fall back to 0 counts if UNION fails

        schema: dict[str, Any] = {}
        for table in tables:
            # Column info
            cursor = self._conn.execute(f"PRAGMA table_info([{table}])")
            columns = []
            for row in cursor.fetchall():
                columns.append(
                    {
                        "name": row[1],
                        "type": row[2],
                        "nullable": not row[3],
                        "primary_key": bool(row[5]),
                        "default": row[4],
                        "comment": "",
                    }
                )

            # Foreign keys — critical for Spider2.0-Lite join path discovery
            foreign_keys = []
            try:
                cursor = self._conn.execute(f"PRAGMA foreign_key_list([{table}])")
                for fk_row in cursor.fetchall():
                    foreign_keys.append(
                        {
                            "column": fk_row[3],  # from column
                            "references_table": fk_row[2],  # table
                            "references_column": fk_row[4],  # to column
                        }
                    )
            except Exception:
                pass

            schema[table] = {
                "schema": "main",
                "name": table,
                "type": table_type_map.get(table, "table"),
                "columns": columns,
                "foreign_keys": foreign_keys,
                "row_count": row_counts.get(table, 0),
            }
        return schema

    async def _get_sample_values_impl(self, table: str, columns: list[str], limit: int = 5) -> dict[str, list]:
        """Get sample distinct values via single UNION ALL query (1 round trip)."""
        import time as _time

        if self._conn is None or not columns:
            return {}
        try:
            sql = self._build_sample_union_sql(table, columns, limit, quote="[")
            t0 = _time.monotonic()
            cursor = self._conn.execute(sql)
            rows = cursor.fetchall()
            await self._audit_sql(sql.strip(), len(rows), (_time.monotonic() - t0) * 1000)
            return self._parse_sample_union_result(rows)
        except Exception:
            # Fallback to per-column queries
            result: dict[str, list] = {}
            safe_table = self._quote_table(table)
            for col in columns[:20]:
                try:
                    safe_col = self._quote_identifier(col)
                    cursor = self._conn.execute(
                        f"SELECT DISTINCT {safe_col} FROM {safe_table} WHERE {safe_col} IS NOT NULL LIMIT {limit}"
                    )
                    values = [str(row[0]) for row in cursor.fetchall()]
                    if values:
                        result[col] = values
                except Exception:
                    continue
            return result

    async def health_check(self) -> bool:
        if self._conn is None:
            return False
        try:
            self._conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
