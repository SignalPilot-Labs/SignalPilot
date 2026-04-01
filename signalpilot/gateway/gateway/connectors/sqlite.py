"""SQLite connector — aiosqlite-backed, for Spider2 benchmarking and local files."""

from __future__ import annotations

import sqlite3
from typing import Any

from .base import BaseConnector


class SQLiteConnector(BaseConnector):
    def __init__(self):
        self._conn: sqlite3.Connection | None = None
        self._db_path: str = ""

    async def connect(self, connection_string: str) -> None:
        # connection_string is the file path (or :memory:)
        self._db_path = connection_string
        self._conn = sqlite3.connect(connection_string)
        self._conn.row_factory = sqlite3.Row

    async def execute(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        if self._conn is None:
            raise RuntimeError("Not connected")
        cursor = self._conn.execute(sql, params or [])
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        return [{col: row[i] for i, col in enumerate(columns)} for row in rows]

    async def get_schema(self) -> dict[str, Any]:
        if self._conn is None:
            raise RuntimeError("Not connected")
        cursor = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        tables = [row[0] for row in cursor.fetchall()]

        schema: dict[str, Any] = {}
        for table in tables:
            # Column info
            cursor = self._conn.execute(f"PRAGMA table_info([{table}])")
            columns = []
            for row in cursor.fetchall():
                columns.append({
                    "name": row[1],
                    "type": row[2],
                    "nullable": not row[3],
                    "primary_key": bool(row[5]),
                    "default": row[4],
                })

            # Foreign keys — critical for Spider2.0-Lite join path discovery
            foreign_keys = []
            try:
                cursor = self._conn.execute(f"PRAGMA foreign_key_list([{table}])")
                for fk_row in cursor.fetchall():
                    foreign_keys.append({
                        "column": fk_row[3],  # from column
                        "references_table": fk_row[2],  # table
                        "references_column": fk_row[4],  # to column
                    })
            except Exception:
                pass

            # Row count estimate
            row_count = 0
            try:
                cursor = self._conn.execute(f"SELECT COUNT(*) FROM [{table}]")
                row_count = cursor.fetchone()[0]
            except Exception:
                pass

            schema[table] = {
                "schema": "main",
                "name": table,
                "columns": columns,
                "foreign_keys": foreign_keys,
                "row_count": row_count,
            }
        return schema

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
