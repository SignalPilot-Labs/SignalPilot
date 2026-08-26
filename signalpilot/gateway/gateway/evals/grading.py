"""Grade evaluation tasks.

The ``checks`` grade compares extracted numbers with target values and a relative tolerance.
It returns CORRECT, PARTIAL, OFF, UNKNOWN, or UNGRADED.

The ``model_rebuilt`` grade checks a rebuilt mart on the task branch.
It checks table existence, row count, grain uniqueness, and required columns.
A caller-supplied query function keeps the grade independent of the database provider.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

QueryFn = Callable[[str], Awaitable[list[tuple]]]

_NUM_RE = re.compile(r"[-+]?\$?\d[\d,]*\.?\d*\s*(?:billion|million|thousand|[bmk])?", re.IGNORECASE)
_SUFFIX = {"b": 1e9, "billion": 1e9, "m": 1e6, "million": 1e6, "k": 1e3, "thousand": 1e3}

# Table identifiers from the evaluation manifest are interpolated into SQL.
# Accept only plain dotted names.
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,2}$")


def extract_numbers(text: str) -> list[float]:
    nums: list[float] = []
    for m in _NUM_RE.finditer(text):
        raw = m.group(0).lower().replace("$", "").replace(",", "").strip()
        mult = 1.0
        for suffix, factor in _SUFFIX.items():
            if raw.endswith(suffix):
                raw = raw[: -len(suffix)].strip()
                mult = factor
                break
        try:
            nums.append(float(raw) * mult)
        except ValueError:
            continue
    return nums


def _check_passes(check: dict, numbers: list[float]) -> bool:
    target = check["value"]
    tol = check.get("tolerance", 0.15)
    for n in numbers:
        if target == 0:
            if abs(n) < 1e-9:
                return True
        elif abs(n - target) / abs(target) <= tol:
            return True
    return False


def grade_checks(checks: list[dict], answer: str) -> tuple[str, list[dict]]:
    """Verdicts: CORRECT / PARTIAL / OFF / UNKNOWN / UNGRADED."""
    if not checks:
        return "UNGRADED", []
    numbers = extract_numbers(answer)
    results = [
        {
            "name": c["name"],
            "value": c["value"],
            "tolerance": c.get("tolerance", 0.15),
            "passed": _check_passes(c, numbers),
        }
        for c in checks
    ]
    if not numbers:
        return "UNKNOWN", results
    passed = sum(1 for r in results if r["passed"])
    if passed == len(results):
        return "CORRECT", results
    if passed > 0:
        return "PARTIAL", results
    return "OFF", results


def quote_table(name: str) -> str:
    """Validate + quote a dotted identifier from the manifest for SQL use."""
    if not _IDENT_RE.match(name or ""):
        raise ValueError(f"invalid table identifier: {name!r}")
    return ".".join(f'"{part}"' for part in name.split("."))


async def _table_exists(query: QueryFn, table: str) -> bool:
    parts = table.split(".")
    if len(parts) == 3:
        parts = parts[1:]  # database.schema.table -> schema.table for information_schema
    if len(parts) == 2:
        schema, name = parts
        rows = await query(
            "SELECT 1 FROM information_schema.tables "
            f"WHERE table_schema = '{schema}' AND table_name = '{name}' LIMIT 1"
        )
    else:
        rows = await query(
            "SELECT 1 FROM information_schema.tables "
            f"WHERE table_name = '{parts[0]}' LIMIT 1"
        )
    return bool(rows)


async def _columns(query: QueryFn, table: str) -> list[str]:
    parts = table.split(".")
    if len(parts) == 3:
        parts = parts[1:]
    if len(parts) == 2:
        schema, name = parts
        rows = await query(
            "SELECT column_name FROM information_schema.columns "
            f"WHERE table_schema = '{schema}' AND table_name = '{name}' ORDER BY ordinal_position"
        )
    else:
        rows = await query(
            "SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{parts[0]}' ORDER BY ordinal_position"
        )
    return [str(r[0]) for r in rows]


async def grade_model_rebuilt(
    grade: dict[str, Any], query: QueryFn
) -> tuple[str, list[dict]]:
    """Grade a rebuilt model on its branch.

    expect supports: row_count (+ row_count_tolerance, default 0.01),
    grain: [cols...] (count(*) == count(distinct cols)), columns: [names...].
    Table existence is always checked. Verdict CORRECT only if every
    expectation holds; any failure is OFF; a query error is ERROR.
    """
    model = grade["model"]
    expect = grade.get("expect") or {}
    results: list[dict] = []

    def note(name: str, passed: bool, detail: str = "") -> None:
        results.append({"name": name, "passed": passed, "detail": detail})

    try:
        table_sql = quote_table(model)
    except ValueError as exc:
        note("identifier", False, str(exc))
        return "ERROR", results

    try:
        if not await _table_exists(query, model):
            note("exists", False, f"{model} not found")
            return "OFF", results
        note("exists", True)

        row_count = None
        if "row_count" in expect or "grain" in expect:
            rows = await query(f"SELECT count(*) FROM {table_sql}")
            row_count = int(rows[0][0]) if rows else 0

        if "row_count" in expect:
            target = float(expect["row_count"])
            tol = float(expect.get("row_count_tolerance", 0.01))
            ok = (
                abs(row_count) < 1e-9
                if target == 0
                else abs(row_count - target) / abs(target) <= tol
            )
            note("row_count", ok, f"{row_count} vs {int(target)} ±{tol:.0%}")

        grain = [str(g) for g in expect.get("grain") or []]
        if grain:
            for col in grain:
                if not _IDENT_RE.match(col):
                    raise ValueError(f"invalid grain column: {col!r}")
            cols_sql = ", ".join(f'"{c}"' for c in grain)
            rows = await query(
                f"SELECT count(*) - count(*) FILTER (WHERE d.rn = 1) FROM "
                f"(SELECT row_number() OVER (PARTITION BY {cols_sql}) AS rn FROM {table_sql}) d"
            )
            dupes = int(rows[0][0]) if rows else 0
            note("grain", dupes == 0, f"{dupes} duplicate rows on ({', '.join(grain)})")

        want_cols = [str(c) for c in expect.get("columns") or []]
        if want_cols:
            have = {c.lower() for c in await _columns(query, model)}
            missing = [c for c in want_cols if c.lower() not in have]
            note("columns", not missing, f"missing: {', '.join(missing)}" if missing else "")
    except Exception as exc:
        logger.warning("model_rebuilt grading failed for %s: %s", model, exc)
        note("query", False, str(exc)[:300])
        return "ERROR", results

    return ("CORRECT" if all(r["passed"] for r in results) else "OFF"), results
