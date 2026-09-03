"""Database-derived hints for `analyze_project_db`.

Three hint families, all computed from one `get_schema()` result:

- staging gaps: `stg_*` models with fewer rows than the raw table they wrap
- driving tables: parent/child pairs where some parents have no children
- (lookup joins live in model_map.py; they are pure name matching)

The driving-table step is the only one that can touch the warehouse. It uses
catalog distinct counts first and falls back to bounded `COUNT(DISTINCT)` scans.
Every scan is aliased so dict-row drivers (SQL Server) accept it, and the whole
step runs under a wall-clock and scan-count budget. A run that hits the budget
returns the hints found so far plus one note line.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

# Parent-child orphan detection uses catalog distinct-counts (pigeonhole), so it never
# scans a large table. Exact COUNT(DISTINCT) is only used as a fallback on small tables
# whose stats the catalog doesn't carry (e.g. DuckDB, SQL Server non-unique columns).
_DISTINCT_EXACT_CAP = 200_000

# Columnar engines do exact COUNT(DISTINCT) cheaply at any size; MPP engines have a
# fast approximate-distinct function. Everything else is exact only on small tables.
_COLUMNAR_DISTINCT = {"duckdb", "clickhouse"}
_APPROX_DISTINCT_FN = {
    "snowflake": "APPROX_COUNT_DISTINCT",
    "bigquery": "APPROX_COUNT_DISTINCT",
    "databricks": "APPROX_COUNT_DISTINCT",
    "trino": "approx_distinct",
}


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


@dataclass
class ScanBudget:
    """Bound the driving-table step. Zero disables that limit."""

    seconds: float = field(default_factory=lambda: float(_env_int("SP_DB_HINTS_SCAN_BUDGET_SECONDS", 20)))
    max_scans: int = field(default_factory=lambda: _env_int("SP_DB_HINTS_MAX_SCANS", 40))
    started_at: float = field(default_factory=time.monotonic)
    scans: int = 0
    exhausted: bool = False

    def allow_scan(self) -> bool:
        if self.exhausted:
            return False
        if self.seconds and time.monotonic() - self.started_at > self.seconds:
            self.exhausted = True
        elif self.max_scans and self.scans >= self.max_scans:
            self.exhausted = True
        return not self.exhausted

    def note(self) -> str:
        elapsed = time.monotonic() - self.started_at
        return (
            f"  (driving-table scan stopped after {self.scans} table scans and "
            f"{elapsed:.0f}s; hints above are partial)"
        )


async def _q(connector, sql: str) -> list[tuple]:
    """Run a query and return rows as tuples in select order."""
    rows = await connector.execute(sql)
    return [tuple(r.values()) for r in rows]


async def _staging_gaps(schema: Any) -> list[str]:
    """stg_* models that have fewer rows than the raw table they wrap.

    Uses row-count estimates from the catalog. No scans.
    """
    hints: list[str] = []
    tables = schema.tables()
    for tbl in sorted(tables):
        if not tbl.lower().startswith("stg_"):
            continue
        raw_name = tbl[4:].rstrip("s").lower()
        raw_match = next(
            (c for c in tables if c.lower() in (raw_name, raw_name + "s", tbl[4:].lower())),
            None,
        )
        if not raw_match:
            continue
        sc, rc = schema.row_count(tbl), schema.row_count(raw_match)
        if rc and sc and sc < rc:
            hints.append(
                f"  {tbl}: ~{sc} rows (raw {raw_match}: ~{rc} — staging filters "
                f"~{rc - sc}). Use ref('{tbl}') not source()."
            )
    return hints


def _scan_expr(dialect: str, qc: str, row_count: int) -> str | None:
    """Distinct-count expression for a column the catalog has no stat for.

    None when a scan would be too expensive: a large row-store table on an engine
    with no approximate function.
    """
    if dialect in _COLUMNAR_DISTINCT:
        return f"COUNT(DISTINCT {qc})"
    if dialect in _APPROX_DISTINCT_FN:
        return f"{_APPROX_DISTINCT_FN[dialect]}({qc})"
    if row_count and row_count <= _DISTINCT_EXACT_CAP:
        return f"COUNT(DISTINCT {qc})"
    return None


def _can_scan(schema: Any, table: str) -> bool:
    """True when a fallback scan of this table is allowed by size on this engine."""
    return _scan_expr(schema.dialect, "x", schema.row_count(table)) is not None


async def _distinct(connector, schema: Any, table: str, col: str) -> int | None:
    """Distinct-count for one column: catalog first, then one bounded scan."""
    values = await _distinct_batch(connector, schema, table, [col])
    return values.get(col)


async def _distinct_batch(connector, schema: Any, table: str, cols: list[str]) -> dict[str, int | None]:
    """Distinct-counts for several columns of ONE table, reading the table at most once.

    Catalog stats answer what they can with no scan. Every remaining column is folded
    into a single `SELECT <agg>(c0) AS d0, ... FROM table`. Aliases keep dict-row
    drivers (SQL Server) happy; a bare aggregate has no column name there.
    """
    out: dict[str, int | None] = {col: schema.distinct(table, col) for col in cols}
    scan_cols = [col for col in cols if out[col] is None]
    if not scan_cols:
        return out
    rc = schema.row_count(table)
    exprs: list[str] = []
    scanned: list[str] = []
    for index, col in enumerate(scan_cols):
        expr = _scan_expr(schema.dialect, connector._quote_identifier(col), rc)
        if expr is not None:
            exprs.append(f"{expr} AS d{index}")
            scanned.append(col)
    if not exprs:
        return out
    try:
        q = connector._quote_table(schema.resolve(table))
        row = (await _q(connector, f"SELECT {', '.join(exprs)} FROM {q}"))[0]
        for col, val in zip(scanned, row, strict=False):
            out[col] = int(val) if val is not None else None
    except Exception:
        pass
    return out


def _candidate_pairs(schema: Any) -> tuple[list[tuple[str, str, str, str]], dict[str, set[str]]]:
    """Enumerate (parent, pid, child, fk) pairs and the columns each table needs.

    Pure string work, no I/O. The pair order is the table order of the schema, so
    the hints are deterministic.
    """
    tables = {t: [c for c, _ in schema.columns(t)] for t in schema.tables()}
    parents = {t: next((c for c in cols if c.lower() == "id"), None) for t, cols in tables.items()}
    parents = {t: c for t, c in parents.items() if c}
    checked: set[tuple[str, str, str]] = set()
    pairs: list[tuple[str, str, str, str]] = []
    needed: dict[str, set[str]] = {}
    for child, ccols in tables.items():
        for fk in [c for c in ccols if c.lower().endswith("_id") and c.lower() != "id"]:
            prefix = fk.lower().replace("_id", "")
            for parent, pid in parents.items():
                if parent == child or (parent, child, fk) in checked:
                    continue
                checked.add((parent, child, fk))
                if prefix not in parent.lower():
                    continue
                pairs.append((parent, pid, child, fk))
                needed.setdefault(parent, set()).add(pid)
                needed.setdefault(child, set()).add(fk)
    return pairs, needed


async def _driving_table_gaps(
    connector,
    schema: Any,
    cap: int = 10,
    budget: ScanBudget | None = None,
) -> list[str]:
    """Parent-child pairs where some parents have NO children (drive FROM parent).

    Pigeonhole on distinct counts: a child can reference at most distinct(child.fk)
    distinct parents, so distinct(parent.id) > distinct(child.fk) proves orphans.
    Catalog stats answer most columns for free. Fallback scans are aliased, one per
    table, and stop at the budget. Pairs whose tables cannot be scanned (views, huge
    tables without stats) are skipped without I/O.
    """
    budget = budget or ScanBudget()
    hints: list[str] = []
    pairs, needed = _candidate_pairs(schema)
    dcache: dict[tuple[str, str], int | None] = {}
    scanned: set[str] = set()

    def catalog_or_scannable(table: str, col: str) -> bool:
        return schema.distinct(table, col) is not None or _can_scan(schema, table)

    async def dist(table: str, col: str) -> int | None:
        if (table, col) in dcache:
            return dcache[(table, col)]
        value = schema.distinct(table, col)
        if value is not None:
            dcache[(table, col)] = value
            return value
        if table in scanned or not budget.allow_scan():
            return None
        scanned.add(table)
        budget.scans += 1
        values = await _distinct_batch(connector, schema, table, sorted(needed.get(table, {col})))
        for c, v in values.items():
            dcache[(table, c)] = v
        return dcache.get((table, col))

    for parent, pid, child, fk in pairs:
        # Skip pairs that can never be answered before spending any budget.
        if not (catalog_or_scannable(parent, pid) and catalog_or_scannable(child, fk)):
            continue
        pd = await dist(parent, pid)
        cd = await dist(child, fk)
        if pd is None or cd is None or pd <= cd:
            if budget.exhausted:
                break
            continue
        hints.append(
            f"  {parent}.{pid} ↔ {child}.{fk}: ~{pd - cd} of {pd} parent keys are not "
            f"referenced by {child} (some parents have no children). "
            f"Drive FROM {parent} LEFT JOIN {child}."
        )
        if len(hints) >= cap:
            return hints
    if budget.exhausted:
        hints.append(budget.note())
    return hints
