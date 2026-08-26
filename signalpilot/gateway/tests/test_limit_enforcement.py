"""LIMIT-cap enforcement: the unbounded-limit regression suite.

Covers the SP-SEC-012 fix in ``gateway/engine/transforms.py``.

Before the fix ``inject_limit`` read the existing limit with a narrow
``int(limit.expression.this)`` style lookup and, whenever that failed, left the
query's limit UNCHANGED. Every form below therefore reached the database
unbounded:

* ``LIMIT ALL``            — no row count at all
* ``LIMIT $1`` / ``LIMIT :n`` — bind parameter, unresolvable at inject time
* ``FETCH FIRST n ROWS ONLY`` — an ``exp.Fetch`` node, not ``exp.Limit``
* ``TOP n PERCENT``        — a percentage, not a row count

``_resolve_limit_value`` now understands both ``exp.Limit`` and ``exp.Fetch``,
returns ``None`` for anything that does not pin a concrete row count, and the
caller overwrites the limit with ``max_rows`` whenever it is missing,
unresolvable, or above the cap. A resolvable limit at or below the cap keeps its
original value AND its original syntax.

These are UNIT tests over the transform. End-to-end proof that the cap actually
truncates a real result set is in ``tests/test_sql_governance_live.py``.
"""

from __future__ import annotations

import pytest

from gateway.engine import inject_limit
from gateway.engine._sqlglot import sqlglot

CAP = 10


def _limit(sql: str, dialect: str, cap: int = CAP) -> str:
    return inject_limit(sql, max_rows=cap, dialect=dialect)


def _effective_row_cap(sql: str, dialect: str) -> int | None:
    """Re-parse governed SQL and return the concrete row count it pins.

    Returns ``None`` when the SQL is still unbounded — which is exactly the bug.
    Implemented independently of ``_resolve_limit_value`` so the test does not
    inherit the function under test's own notion of "resolvable".
    """
    parsed = sqlglot.parse_one(sql, dialect=dialect)
    assert parsed is not None
    node = parsed.args.get("limit")
    if node is None:
        return None
    options = node.args.get("limit_options")
    if options is not None and options.args.get("percent"):
        return None
    count = node.args.get("count") if node.args.get("count") is not None else (node.expression or node.this)
    if count is None:
        return None
    try:
        text = count.this
    except AttributeError:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


# ───────────────────────────────────────────────────────────────────────────────
# Probe rows from security/automated-results.md ("SQL governance probes")
# ───────────────────────────────────────────────────────────────────────────────


class TestAutomatedResultsProbeRows:
    def test_probe_postgres_limit_all_with_cap_10(self) -> None:
        """Audit recorded: "Remained LIMIT ALL"."""
        governed = _limit("SELECT * FROM t LIMIT ALL", "postgres")
        assert "ALL" not in governed.upper().replace("SELECT", "")
        assert _effective_row_cap(governed, "postgres") == CAP

    def test_probe_postgres_fetch_first_100_with_cap_10(self) -> None:
        """Audit recorded: "Remained at 100"."""
        governed = _limit("SELECT * FROM t FETCH FIRST 100 ROWS ONLY", "postgres")
        assert _effective_row_cap(governed, "postgres") == CAP

    def test_probe_tsql_top_100_percent_with_cap_10(self) -> None:
        """Audit recorded this one as already correct — it must stay correct."""
        governed = _limit("SELECT TOP 100 PERCENT * FROM t", "tsql")
        assert "PERCENT" not in governed.upper()
        assert governed == "SELECT TOP 10 * FROM t"


# ───────────────────────────────────────────────────────────────────────────────
# Every unbounded / unresolvable form is clamped to the cap
# ───────────────────────────────────────────────────────────────────────────────


class TestUnboundedFormsAreClamped:
    UNBOUNDED = [
        # (dialect, sql)
        ("postgres", "SELECT * FROM t"),
        ("postgres", "SELECT * FROM t LIMIT ALL"),
        ("postgres", "SELECT * FROM t LIMIT NULL"),
        ("postgres", "SELECT * FROM t LIMIT $1"),
        ("postgres", "SELECT * FROM t LIMIT :row_count"),
        ("postgres", "SELECT * FROM t FETCH FIRST 100 ROWS ONLY"),
        ("postgres", "SELECT * FROM t FETCH NEXT 100 ROWS ONLY"),
        ("postgres", "SELECT * FROM t OFFSET 5"),
        ("postgres", "SELECT * FROM t LIMIT 99999"),
        ("postgres", "SELECT * FROM t LIMIT ALL OFFSET 5"),
        ("duckdb", "SELECT * FROM t LIMIT ALL"),
        ("duckdb", "SELECT * FROM t"),
        ("duckdb", "SELECT * FROM t LIMIT 50000"),
        ("mysql", "SELECT * FROM t"),
        ("mysql", "SELECT * FROM t LIMIT 12345"),
        ("tsql", "SELECT * FROM t"),
        ("tsql", "SELECT TOP 100 PERCENT * FROM t"),
        ("tsql", "SELECT TOP 50000 * FROM t"),
        ("trino", "SELECT * FROM t"),
        ("trino", "SELECT * FROM t LIMIT ALL"),
        ("snowflake", "SELECT * FROM t LIMIT NULL"),
        ("redshift", "SELECT * FROM t LIMIT ALL"),
        ("clickhouse", "SELECT * FROM t"),
        ("sqlite", "SELECT * FROM t"),
    ]

    @pytest.mark.parametrize("dialect,sql", UNBOUNDED, ids=[f"{d}:{s}" for d, s in UNBOUNDED])
    def test_clamped_to_cap(self, dialect: str, sql: str) -> None:
        governed = _limit(sql, dialect)
        assert _effective_row_cap(governed, dialect) == CAP, f"[{dialect}] UNBOUNDED after inject_limit: {governed!r}"

    def test_offset_is_preserved_when_limit_is_injected(self) -> None:
        governed = _limit("SELECT * FROM t OFFSET 5 FETCH NEXT 100 ROWS ONLY", "postgres")
        assert _effective_row_cap(governed, "postgres") == CAP
        assert "OFFSET 5" in governed.upper()

    def test_offset_preserved_with_limit_all(self) -> None:
        governed = _limit("SELECT * FROM t ORDER BY id OFFSET 5 ROWS", "postgres")
        assert _effective_row_cap(governed, "postgres") == CAP
        assert "OFFSET 5" in governed.upper()

    def test_bare_offset_only_query_gets_a_limit(self) -> None:
        governed = _limit("SELECT * FROM t OFFSET 5", "postgres")
        assert _effective_row_cap(governed, "postgres") == CAP
        assert "OFFSET 5" in governed.upper()


# ───────────────────────────────────────────────────────────────────────────────
# REGRESSION: a resolvable limit at or below the cap is left completely alone
# ───────────────────────────────────────────────────────────────────────────────


class TestSmallerLimitsPreserved:
    PRESERVED = [
        # (dialect, sql, expected_output)
        ("postgres", "SELECT * FROM t LIMIT 5", "SELECT * FROM t LIMIT 5"),
        ("postgres", "SELECT * FROM t LIMIT 10", "SELECT * FROM t LIMIT 10"),
        ("postgres", "SELECT * FROM t LIMIT 3 OFFSET 5", "SELECT * FROM t LIMIT 3 OFFSET 5"),
        (
            "postgres",
            "SELECT * FROM t FETCH FIRST 3 ROWS ONLY",
            "SELECT * FROM t FETCH FIRST 3 ROWS ONLY",
        ),
        ("tsql", "SELECT TOP 5 * FROM t", "SELECT TOP 5 * FROM t"),
        ("tsql", "SELECT TOP 10 * FROM t", "SELECT TOP 10 * FROM t"),
        ("duckdb", "SELECT * FROM t LIMIT 5", "SELECT * FROM t LIMIT 5"),
        ("mysql", "SELECT * FROM t LIMIT 5", "SELECT * FROM t LIMIT 5"),
    ]

    @pytest.mark.parametrize("dialect,sql,expected", PRESERVED, ids=[f"{d}:{s}" for d, s, _ in PRESERVED])
    def test_original_value_and_syntax_preserved(self, dialect: str, sql: str, expected: str) -> None:
        assert _limit(sql, dialect) == expected

    def test_fetch_first_syntax_is_not_rewritten_to_limit(self) -> None:
        """A small FETCH FIRST must keep the FETCH syntax, not be turned into LIMIT."""
        governed = _limit("SELECT * FROM t FETCH FIRST 3 ROWS ONLY", "postgres")
        assert "FETCH FIRST 3" in governed.upper()
        assert "LIMIT" not in governed.upper()

    def test_boundary_limit_equal_to_cap_is_untouched(self) -> None:
        assert _limit("SELECT * FROM t LIMIT 10", "postgres", cap=10) == "SELECT * FROM t LIMIT 10"

    def test_boundary_limit_one_over_cap_is_clamped(self) -> None:
        assert _limit("SELECT * FROM t LIMIT 11", "postgres", cap=10) == "SELECT * FROM t LIMIT 10"


# ───────────────────────────────────────────────────────────────────────────────
# Direct unit coverage of _resolve_limit_value
# ───────────────────────────────────────────────────────────────────────────────


class TestResolveLimitValue:
    def _resolve(self, sql: str, dialect: str) -> int | None:
        from gateway.engine.transforms import _resolve_limit_value

        parsed = sqlglot.parse_one(sql, dialect=dialect)
        assert parsed is not None
        return _resolve_limit_value(parsed.args["limit"])

    @pytest.mark.parametrize(
        "dialect,sql,expected",
        [
            ("postgres", "SELECT * FROM t LIMIT 7", 7),
            ("postgres", "SELECT * FROM t FETCH FIRST 7 ROWS ONLY", 7),
            ("postgres", "SELECT * FROM t FETCH FIRST ROW ONLY", 1),
            ("tsql", "SELECT TOP 7 * FROM t", 7),
        ],
    )
    def test_resolvable_counts(self, dialect: str, sql: str, expected: int) -> None:
        assert self._resolve(sql, dialect) == expected

    @pytest.mark.parametrize(
        "dialect,sql",
        [
            ("postgres", "SELECT * FROM t LIMIT ALL"),
            ("postgres", "SELECT * FROM t LIMIT $1"),
            ("postgres", "SELECT * FROM t LIMIT :n"),
            ("tsql", "SELECT TOP 50 PERCENT * FROM t"),
        ],
    )
    def test_unresolvable_returns_none(self, dialect: str, sql: str) -> None:
        assert self._resolve(sql, dialect) is None, f"{sql!r} must be treated as unbounded"


# ───────────────────────────────────────────────────────────────────────────────
# Fail-closed behaviour of the transform itself
# ───────────────────────────────────────────────────────────────────────────────


class TestInjectLimitFailsClosed:
    def test_unparseable_sql_raises_instead_of_concatenating(self) -> None:
        with pytest.raises(ValueError, match="could not be parsed"):
            inject_limit("SELECT * FROM (((", max_rows=CAP, dialect="postgres")

    def test_trailing_semicolon_stripped(self) -> None:
        assert _limit("SELECT * FROM t;", "postgres") == "SELECT * FROM t LIMIT 10"

    def test_cte_query_gets_outer_limit(self) -> None:
        governed = _limit("WITH x AS (SELECT 1 AS a) SELECT * FROM x", "postgres")
        assert _effective_row_cap(governed, "postgres") == CAP

    def test_union_query_gets_limit(self) -> None:
        governed = _limit("SELECT a FROM t1 UNION ALL SELECT a FROM t2", "postgres")
        assert _effective_row_cap(governed, "postgres") == CAP
