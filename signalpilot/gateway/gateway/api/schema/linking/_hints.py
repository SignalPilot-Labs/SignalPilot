"""Query hint generation for schema linking — produces SQL pattern guidance based on question type."""

from __future__ import annotations


def build_query_hints(
    question_lower: str,
    db_type: str,
    is_aggregation: bool,
    is_temporal: bool,
) -> list[str]:
    """Build query-type-aware hints (ReFoRCE "format restriction" pattern).

    Detects question type and provides SQL pattern guidance to reduce errors.
    """
    query_hints: list[str] = []
    _q = question_lower
    if is_aggregation:
        query_hints.append("Use GROUP BY for aggregations; include all non-aggregated SELECT columns")
    if any(w in _q for w in ("top", "highest", "lowest", "rank", "first", "best", "worst")):
        if db_type == "mssql":
            query_hints.append("Use TOP N instead of LIMIT; for ranking use ROW_NUMBER() OVER(...)")
        else:
            query_hints.append("Use ORDER BY ... LIMIT N for top-N queries; consider RANK()/ROW_NUMBER() for ties")
    if any(w in _q for w in ("percentage", "percent", "ratio", "share", "proportion")):
        query_hints.append("Use 100.0 * COUNT/SUM to avoid integer division; cast to DECIMAL if needed")
    if is_temporal:
        if db_type in ("postgres", "redshift"):
            query_hints.append("Use DATE_TRUNC('month', col) for time grouping; EXTRACT(YEAR FROM col) for year")
        elif db_type == "mysql":
            query_hints.append("Use DATE_FORMAT(col, '%Y-%m') for month grouping; YEAR(col), MONTH(col) for parts")
        elif db_type == "mssql":
            query_hints.append("Use FORMAT(col, 'yyyy-MM') or DATEPART(YEAR, col) for time grouping")
        elif db_type == "bigquery":
            query_hints.append("Use FORMAT_DATE('%Y-%m', col) or EXTRACT(YEAR FROM col) for time grouping")
        elif db_type == "snowflake":
            query_hints.append("Use DATE_TRUNC('MONTH', col) for time grouping; TO_CHAR(col, 'YYYY-MM')")
    if any(w in _q for w in ("distinct", "unique", "different")):
        query_hints.append("Use COUNT(DISTINCT col) for unique counts; SELECT DISTINCT for unique rows")
    if any(w in _q for w in ("compare", "versus", "vs", "difference", "change")):
        query_hints.append("Consider self-joins or window functions (LAG/LEAD) for comparisons")
    if any(w in _q for w in ("running", "cumulative", "rolling")):
        query_hints.append("Use SUM(...) OVER (ORDER BY ...) for running totals; ROWS BETWEEN for rolling windows")
    return query_hints
