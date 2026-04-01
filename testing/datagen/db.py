"""
Database connection helpers and COPY-based bulk loading.
Uses psycopg (v3) with COPY for maximum insert throughput.
"""

import io
import sys
import time
from contextlib import contextmanager

import psycopg
from psycopg import sql


def connect(db_config: dict) -> psycopg.Connection:
    """Open a psycopg3 connection from a config dict."""
    return psycopg.connect(
        host=db_config["host"],
        port=db_config["port"],
        dbname=db_config["dbname"],
        user=db_config["user"],
        password=db_config["password"],
        autocommit=True,
    )


def copy_rows(conn: psycopg.Connection, table: str, columns: list[str], rows: list[tuple]):
    """Bulk-load rows into a table using COPY FROM STDIN (CSV)."""
    if not rows:
        return
    col_list = ", ".join(columns)
    buf = io.StringIO()
    for row in rows:
        line = "\t".join(_escape_copy(v) for v in row)
        buf.write(line + "\n")
    buf.seek(0)

    with conn.cursor() as cur:
        with cur.copy(f"COPY {table} ({col_list}) FROM STDIN") as copy:
            while chunk := buf.read(65536):
                copy.write(chunk.encode("utf-8"))


def _escape_copy(val) -> str:
    """Escape a value for PostgreSQL COPY text format."""
    if val is None:
        return "\\N"
    s = str(val)
    return s.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def truncate_table(conn: psycopg.Connection, table: str):
    """Truncate a table with CASCADE."""
    with conn.cursor() as cur:
        cur.execute(sql.SQL("TRUNCATE TABLE {} CASCADE").format(sql.Identifier(*table.split("."))))


class ProgressTracker:
    """Simple progress tracker that prints status updates."""

    def __init__(self, label: str, total: int, every: int = 250_000):
        self.label = label
        self.total = total
        self.every = every
        self.count = 0
        self.start = time.time()
        self._last_print = 0

    def advance(self, n: int = 1):
        self.count += n
        if self.count - self._last_print >= self.every or self.count >= self.total:
            elapsed = time.time() - self.start
            rate = self.count / elapsed if elapsed > 0 else 0
            pct = min(100, self.count / self.total * 100)
            sys.stdout.write(
                f"\r  {self.label}: {self.count:,}/{self.total:,} ({pct:.0f}%) "
                f"[{rate:,.0f} rows/s]"
            )
            sys.stdout.flush()
            self._last_print = self.count

    def done(self):
        elapsed = time.time() - self.start
        rate = self.count / elapsed if elapsed > 0 else 0
        print(f"\r  {self.label}: {self.count:,} rows in {elapsed:.1f}s ({rate:,.0f} rows/s)")
