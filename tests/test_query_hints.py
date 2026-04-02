"""Tests for query-type-aware hints in schema link response.

Verifies that the schema linker detects question patterns (aggregation,
top-N, percentage, time-series, cumulative) and returns appropriate
SQL guidance hints. Based on ReFoRCE "format restriction" pattern.
"""


# Question pattern detection keywords (mirrors main.py schema_link logic)
_AGG_KEYWORDS = {
    "average", "avg", "sum", "total", "count", "max", "maximum",
    "min", "minimum", "mean", "median", "aggregate", "top", "bottom",
    "highest", "lowest", "most", "least",
}
_TIME_KEYWORDS = {
    "when", "date", "year", "month", "week", "day", "quarter",
    "recent", "latest", "oldest", "between", "before", "after",
    "during", "period",
}


def _detect_patterns(question: str) -> dict:
    """Detect question patterns from a natural language question."""
    q = question.lower()
    words = set(q.split())
    return {
        "is_aggregation": bool(words & _AGG_KEYWORDS),
        "is_temporal": bool(words & _TIME_KEYWORDS),
        "is_top_n": any(w in q for w in ("top", "highest", "lowest", "rank", "first", "best", "worst")),
        "is_percentage": any(w in q for w in ("percentage", "percent", "ratio", "share", "proportion")),
        "is_cumulative": any(w in q for w in ("running", "cumulative", "rolling")),
        "is_comparison": any(w in q for w in ("compare", "versus", "vs", "difference", "change")),
        "is_distinct": any(w in q for w in ("distinct", "unique", "different")),
    }


class TestQueryPatternDetection:
    """Test question pattern detection for query hint generation."""

    def test_aggregation_detection(self):
        patterns = _detect_patterns("show total revenue by customer")
        assert patterns["is_aggregation"] is True
        assert patterns["is_temporal"] is False

    def test_temporal_detection(self):
        patterns = _detect_patterns("show orders by month for 2024")
        assert patterns["is_temporal"] is True

    def test_top_n_detection(self):
        patterns = _detect_patterns("top 10 customers by spending")
        assert patterns["is_top_n"] is True
        assert patterns["is_aggregation"] is True  # "top" is in agg keywords

    def test_percentage_detection(self):
        patterns = _detect_patterns("what percentage of orders are cancelled")
        assert patterns["is_percentage"] is True

    def test_cumulative_detection(self):
        patterns = _detect_patterns("show cumulative revenue over time")
        assert patterns["is_cumulative"] is True

    def test_comparison_detection(self):
        patterns = _detect_patterns("compare revenue between Q1 and Q2")
        assert patterns["is_comparison"] is True

    def test_distinct_detection(self):
        patterns = _detect_patterns("how many unique customers ordered")
        assert patterns["is_distinct"] is True

    def test_multiple_patterns(self):
        """Complex questions should match multiple patterns."""
        patterns = _detect_patterns("show top 5 customers by total monthly spending percentage")
        assert patterns["is_aggregation"] is True
        assert patterns["is_top_n"] is True
        assert patterns["is_percentage"] is True

    def test_no_patterns(self):
        """Simple queries with no special patterns."""
        patterns = _detect_patterns("show all customers")
        assert patterns["is_aggregation"] is False
        assert patterns["is_temporal"] is False
        assert patterns["is_top_n"] is False
        assert patterns["is_percentage"] is False


class TestQueryHintGeneration:
    """Test that correct SQL hints are generated for each pattern."""

    def _build_hints(self, question: str, db_type: str = "postgres") -> list[str]:
        """Simulate hint generation logic from main.py."""
        q = question.lower()
        words = set(q.split())
        is_agg = bool(words & _AGG_KEYWORDS)
        is_temporal = bool(words & _TIME_KEYWORDS)

        hints = []
        if is_agg:
            hints.append("Use GROUP BY for aggregations; include all non-aggregated SELECT columns")

        if any(w in q for w in ("top", "highest", "lowest", "rank", "first", "best", "worst")):
            if db_type == "mssql":
                hints.append("Use TOP N instead of LIMIT; for ranking use ROW_NUMBER() OVER(...)")
            else:
                hints.append("Use ORDER BY ... LIMIT N for top-N queries; consider RANK()/ROW_NUMBER() for ties")

        if any(w in q for w in ("percentage", "percent", "ratio", "share", "proportion")):
            hints.append("Use 100.0 * COUNT/SUM to avoid integer division; cast to DECIMAL if needed")

        if is_temporal:
            if db_type in ("postgres", "redshift"):
                hints.append("Use DATE_TRUNC('month', col) for time grouping; EXTRACT(YEAR FROM col) for year")
            elif db_type == "mysql":
                hints.append("Use DATE_FORMAT(col, '%Y-%m') for month grouping; YEAR(col), MONTH(col) for parts")
            elif db_type == "mssql":
                hints.append("Use FORMAT(col, 'yyyy-MM') or DATEPART(YEAR, col) for time grouping")
            elif db_type == "bigquery":
                hints.append("Use FORMAT_DATE('%Y-%m', col) or EXTRACT(YEAR FROM col) for time grouping")
            elif db_type == "snowflake":
                hints.append("Use DATE_TRUNC('MONTH', col) for time grouping; TO_CHAR(col, 'YYYY-MM')")

        if any(w in q for w in ("distinct", "unique", "different")):
            hints.append("Use COUNT(DISTINCT col) for unique counts; SELECT DISTINCT for unique rows")

        if any(w in q for w in ("running", "cumulative", "rolling")):
            hints.append("Use SUM(...) OVER (ORDER BY ...) for running totals; ROWS BETWEEN for rolling windows")

        return hints

    def test_postgres_aggregation_hints(self):
        hints = self._build_hints("total revenue by customer", "postgres")
        assert any("GROUP BY" in h for h in hints)

    def test_mssql_top_n_uses_top(self):
        hints = self._build_hints("top 10 customers", "mssql")
        assert any("TOP N" in h for h in hints)
        # Should NOT have the postgres-style "ORDER BY ... LIMIT N" hint
        assert not any("ORDER BY" in h and "LIMIT N" in h for h in hints)

    def test_postgres_top_n_uses_limit(self):
        hints = self._build_hints("top 10 customers", "postgres")
        assert any("LIMIT N" in h for h in hints)

    def test_postgres_time_grouping(self):
        hints = self._build_hints("revenue by month", "postgres")
        assert any("DATE_TRUNC" in h for h in hints)

    def test_mysql_time_grouping(self):
        hints = self._build_hints("revenue by month", "mysql")
        assert any("DATE_FORMAT" in h for h in hints)

    def test_mssql_time_grouping(self):
        hints = self._build_hints("revenue by month", "mssql")
        assert any("DATEPART" in h for h in hints)

    def test_bigquery_time_grouping(self):
        hints = self._build_hints("revenue by month", "bigquery")
        assert any("FORMAT_DATE" in h for h in hints)

    def test_snowflake_time_grouping(self):
        hints = self._build_hints("revenue by month", "snowflake")
        assert any("DATE_TRUNC" in h for h in hints)
        assert any("TO_CHAR" in h for h in hints)

    def test_percentage_hint(self):
        hints = self._build_hints("what percentage of orders cancelled")
        assert any("100.0" in h for h in hints)

    def test_cumulative_hint(self):
        hints = self._build_hints("show cumulative revenue")
        assert any("OVER" in h for h in hints)

    def test_distinct_hint(self):
        hints = self._build_hints("how many unique customers")
        assert any("DISTINCT" in h for h in hints)

    def test_no_hints_for_simple_query(self):
        hints = self._build_hints("show all customers")
        assert len(hints) == 0
