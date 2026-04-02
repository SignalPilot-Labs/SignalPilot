"""Shared error handling utilities for gateway and MCP server."""

from __future__ import annotations


def query_error_hint(error: str, db_type: str) -> str | None:
    """Return actionable hint for common SQL query errors.

    Enables structured error feedback for agent self-correction (Spider2.0 SOTA pattern).
    """
    err_lower = error.lower()

    if "column" in err_lower and ("not found" in err_lower or "does not exist" in err_lower or "unknown" in err_lower):
        return "Column name may be misspelled or from the wrong table. Check the schema for exact column names."

    if ("table" in err_lower or "relation" in err_lower) and ("not found" in err_lower or "does not exist" in err_lower or "doesn't exist" in err_lower):
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

    return None
