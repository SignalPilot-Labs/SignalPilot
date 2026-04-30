"""Shared error handling utilities for gateway and MCP server."""

from __future__ import annotations


def query_error_hint(error: str, db_type: str) -> str | None:
    """Return actionable hint for common SQL query errors.

    Enables structured error feedback for agent self-correction (Spider2.0 SOTA pattern).
    """
    err_lower = error.lower()

    if "column" in err_lower and ("not found" in err_lower or "does not exist" in err_lower or "unknown" in err_lower):
        return "Column name may be misspelled or from the wrong table. Check the schema for exact column names."

    if ("table" in err_lower or "relation" in err_lower) and (
        "not found" in err_lower or "does not exist" in err_lower or "doesn't exist" in err_lower
    ):
        return "Table may not exist or needs a schema prefix (e.g., schema.table_name)."

    if "ambiguous" in err_lower:
        return "Column reference is ambiguous — qualify it with the table name or alias (e.g., t.column_name)."

    if "syntax error" in err_lower or "parse error" in err_lower:
        if db_type == "bigquery":
            return "BigQuery uses backticks for identifiers and has different function names (e.g., SAFE_DIVIDE, FORMAT_TIMESTAMP)."
        elif db_type == "snowflake":
            return "Snowflake uses double-quotes for case-sensitive identifiers. Column/table names are uppercase by default."
        elif db_type == "clickhouse":
            return "ClickHouse SQL differs from standard SQL — use toDate(), formatDateTime(), arrayJoin()."
        return "Check SQL syntax — consider quoting identifiers and verifying function names for this database dialect."

    if "type mismatch" in err_lower or "cannot be cast" in err_lower or "invalid input syntax" in err_lower:
        return "Data type mismatch. Use CAST(column AS type) or type-specific conversion functions."

    if "division by zero" in err_lower:
        if db_type == "bigquery":
            return "Use SAFE_DIVIDE(a, b) or NULLIF(b, 0) to handle division by zero."
        return "Use NULLIF(divisor, 0) to avoid division by zero: a / NULLIF(b, 0)."

    if "permission" in err_lower or "access denied" in err_lower or "not authorized" in err_lower:
        return "Insufficient permissions. Try a different table or contact the database administrator."

    if "timeout" in err_lower or "timed out" in err_lower:
        return "Query timed out. Try adding WHERE filters, reducing the date range, or using LIMIT."

    if "aggregate" in err_lower and ("group by" in err_lower or "not in group" in err_lower):
        return "Non-aggregated column in SELECT with GROUP BY. Add the column to GROUP BY or wrap it in an aggregate function (MAX, MIN, ANY_VALUE)."

    if "subquery" in err_lower and ("more than one" in err_lower or "multiple rows" in err_lower):
        return "Scalar subquery returned multiple rows. Use IN, ANY, or add LIMIT 1."

    if "join" in err_lower and "condition" in err_lower:
        return "Missing or invalid JOIN condition. Ensure ON clause references columns from both tables."

    if "distinct" in err_lower and ("order by" in err_lower or "sort" in err_lower):
        return "ORDER BY column must be in SELECT DISTINCT list, or use a subquery."

    if "limit" in err_lower and db_type == "mssql":
        return "SQL Server uses TOP N instead of LIMIT. Use: SELECT TOP 100 ... or OFFSET/FETCH."

    if "ilike" in err_lower and db_type in ("mysql", "mssql", "clickhouse"):
        return "ILIKE is not supported. Use LOWER(column) LIKE LOWER(pattern) instead."

    if "boolean" in err_lower or "invalid use of group function" in err_lower:
        return "Cannot use aggregate function in WHERE clause. Move the condition to HAVING."

    # Date/time function mismatches across dialects
    if "date" in err_lower and (
        "function" in err_lower or "not recognized" in err_lower or "does not exist" in err_lower
    ):
        dialect_hints = {
            "bigquery": "BigQuery uses DATE(), TIMESTAMP(), EXTRACT(), DATE_DIFF(), FORMAT_TIMESTAMP().",
            "snowflake": "Snowflake uses DATEADD(), DATEDIFF(), TO_DATE(), DATE_TRUNC().",
            "clickhouse": "ClickHouse uses toDate(), toDateTime(), dateDiff(), formatDateTime().",
            "mssql": "SQL Server uses DATEADD(), DATEDIFF(), CONVERT(), FORMAT().",
            "mysql": "MySQL uses DATE(), STR_TO_DATE(), DATEDIFF(), DATE_FORMAT().",
            "postgres": "PostgreSQL uses DATE_TRUNC(), TO_DATE(), AGE(), EXTRACT().",
            "redshift": "Redshift uses DATEADD(), DATEDIFF(), DATE_TRUNC(), GETDATE().",
        }
        hint = dialect_hints.get(db_type, "Check date function names for this database dialect.")
        return f"Date/time function not found. {hint}"

    # Window function errors
    if "window" in err_lower or ("over" in err_lower and "not allowed" in err_lower):
        return "Window function error. Ensure OVER() clause has valid PARTITION BY and ORDER BY. Cannot use window functions in WHERE/HAVING."

    # CTE / WITH clause errors
    if "recursive" in err_lower or ("with" in err_lower and "defined but not used" in err_lower):
        return "CTE (WITH clause) error. Ensure the CTE name is referenced in the main query and syntax matches the dialect."

    # String concatenation differences
    if "concat" in err_lower and ("operator" in err_lower or "function" in err_lower):
        dialect_hints = {
            "bigquery": "BigQuery uses CONCAT() function, not || operator.",
            "mssql": "SQL Server uses + for concatenation or CONCAT() function.",
            "mysql": "MySQL uses CONCAT() function. || is logical OR by default.",
        }
        hint = dialect_hints.get(db_type, "Use CONCAT() for portable string concatenation.")
        return hint

    # NULL handling
    if "null" in err_lower and ("operator" in err_lower or "comparison" in err_lower):
        return "Cannot compare with NULL using = or !=. Use IS NULL or IS NOT NULL instead."

    # HAVING without GROUP BY
    if "having" in err_lower and "group" in err_lower:
        return "HAVING requires GROUP BY. Add a GROUP BY clause or move the condition to WHERE."

    # Snowflake case sensitivity
    if db_type == "snowflake" and ("identifier" in err_lower and ("not exist" in err_lower or "invalid" in err_lower)):
        return "Snowflake identifiers are uppercase by default. Use double-quotes for case-sensitive names or convert to uppercase."

    # EXCEPT/INTERSECT column count mismatch
    if ("except" in err_lower or "intersect" in err_lower or "union" in err_lower) and (
        "column" in err_lower or "number" in err_lower
    ):
        return "UNION/EXCEPT/INTERSECT requires the same number and types of columns in all SELECT statements."

    # MEDIAN/PERCENTILE differences
    if "median" in err_lower or "percentile" in err_lower:
        dialect_hints = {
            "bigquery": "BigQuery uses PERCENTILE_CONT(column, 0.5) OVER() or APPROX_QUANTILES().",
            "snowflake": "Snowflake supports MEDIAN() and PERCENTILE_CONT() natively.",
            "postgres": "PostgreSQL uses PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY column).",
            "redshift": "Redshift uses MEDIAN() or PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY column).",
            "clickhouse": "ClickHouse uses median() or quantile(0.5)(column).",
            "mssql": "SQL Server uses PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY column) OVER().",
        }
        return dialect_hints.get(db_type, "Median/percentile function syntax varies by dialect.")

    # PIVOT/UNPIVOT differences
    if "pivot" in err_lower:
        dialect_hints = {
            "bigquery": "BigQuery doesn't have native PIVOT. Use CASE WHEN with GROUP BY.",
            "snowflake": "Snowflake supports PIVOT and UNPIVOT natively.",
            "mssql": "SQL Server supports PIVOT/UNPIVOT natively.",
        }
        return dialect_hints.get(db_type, "PIVOT support varies. Use CASE WHEN with GROUP BY for portable SQL.")

    # Array/JSON function differences
    if "array" in err_lower or "json" in err_lower:
        dialect_hints = {
            "bigquery": "BigQuery uses UNNEST() for arrays, JSON_EXTRACT_SCALAR() for JSON.",
            "snowflake": "Snowflake uses FLATTEN() for arrays, GET_PATH()/PARSE_JSON() for JSON.",
            "postgres": "PostgreSQL uses unnest() for arrays, jsonb_extract_path() / -> / ->> for JSON.",
            "clickhouse": "ClickHouse uses arrayJoin() for arrays, JSONExtract*() for JSON.",
            "mysql": "MySQL uses JSON_EXTRACT() / ->> for JSON.",
        }
        return dialect_hints.get(db_type, "Array/JSON function names vary by dialect.")

    return None
