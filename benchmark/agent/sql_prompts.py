"""Prompt builders for SQL-based benchmark suites (spider2-snowflake, spider2-lite)."""

from __future__ import annotations

from pathlib import Path

from ..core.suite import DBBackend

_BACKEND_TIPS: dict[DBBackend, str] = {
    DBBackend.SNOWFLAKE: (
        "SNOWFLAKE-SPECIFIC TIPS:\n"
        "- Use QUALIFY to filter window function results without a subquery\n"
        "- Use ILIKE for case-insensitive string matching\n"
        "- Use LATERAL FLATTEN(input => col) or FLATTEN(col) to expand arrays\n"
        "- Date arithmetic: DATEADD(day, N, col), DATEDIFF(day, start, end)\n"
        "- Semi-structured: col:field for VARIANT, PARSE_JSON for JSON strings\n"
        "- String functions: SPLIT_PART, REGEXP_SUBSTR, TRIM, UPPER/LOWER\n"
        "- Null-safe equality: col IS NOT DISTINCT FROM other_col"
    ),
    DBBackend.BIGQUERY: (
        "BIGQUERY-SPECIFIC TIPS:\n"
        "- Use UNNEST(array_col) to expand array columns\n"
        "- Date arithmetic: DATE_ADD(col, INTERVAL N DAY), DATE_DIFF(end, start, DAY)\n"
        "- Table references: `project.dataset.table` (backtick-quoted)\n"
        "- EXCEPT DISTINCT / UNION DISTINCT remove duplicates automatically\n"
        "- SELECT * EXCEPT (col1) or SELECT * REPLACE (expr AS col1)\n"
        "- STRUCT constructor: STRUCT(val1, val2) or STRUCT(val AS name)\n"
        "- Approximate aggregation: APPROX_COUNT_DISTINCT for large cardinality"
    ),
    DBBackend.SQLITE: (
        "SQLITE-SPECIFIC TIPS:\n"
        "- String concatenation: use || operator (not CONCAT)\n"
        "- Substring: substr(col, start, length) — 1-indexed\n"
        "- Find position: instr(haystack, needle)\n"
        "- LIKE is case-insensitive for ASCII by default\n"
        "- No ILIKE — use LIKE or LOWER(col) LIKE LOWER(pattern)\n"
        "- No FULL OUTER JOIN — use UNION of LEFT JOINs\n"
        "- Date functions: date(), datetime(), strftime() for formatting\n"
        "- Type casting: CAST(col AS INTEGER), CAST(col AS REAL)"
    ),
    DBBackend.DUCKDB: (
        "DUCKDB-SPECIFIC TIPS:\n"
        "- Use QUALIFY to filter window function results without a subquery\n"
        "- Date arithmetic: INTERVAL N DAYS, DATE_TRUNC('month', col)\n"
        "- STRPTIME(col, '%Y-%m-%d') for non-ISO date parsing\n"
        "- String functions: regexp_extract, string_split, str_split_regex\n"
        "- PIVOT / UNPIVOT for reshaping data"
    ),
}


def build_sql_agent_prompt(
    instance_id: str,
    instruction: str,
    work_dir: Path,
    db_backend: DBBackend,
    connection_name: str,
    max_turns: int,
) -> str:
    """Build the agent prompt for a SQL benchmark task.

    The agent must write a SQL query, execute it via the SignalPilot MCP tool,
    and save result.sql and result.csv to work_dir.
    """
    backend_tips = _BACKEND_TIPS.get(db_backend, "- Use standard SQL syntax")

    return f"""You are a SQL expert. Answer the following question by writing and executing SQL.

TASK: {instruction}

DATABASE: SignalPilot connection '{connection_name}' (backend: {db_backend.value}).

WORKFLOW:
1. Explore the schema to understand available tables and columns:
   - mcp__signalpilot__schema_overview — high-level overview
   - mcp__signalpilot__schema_ddl — full CREATE TABLE statements
   - mcp__signalpilot__describe_table — column details for a specific table
   - mcp__signalpilot__explore_table — sample values and statistics
   - mcp__signalpilot__explore_column — distinct values for a column
2. Write a SQL query that answers the task question
3. Execute: mcp__signalpilot__query_database connection_name="{connection_name}" sql="..."
4. Verify the result is sensible (row count, column values, edge cases)
5. Write your final SQL to result.sql (use Write tool)
6. Write the final result as CSV to result.csv (use Write tool, include header row)

RULES:
- Use {db_backend.value}-compatible SQL syntax only
- Read-only queries — do NOT modify the database (no INSERT/UPDATE/DELETE/CREATE/DROP)
- result.csv must include a header row with column names
- result.csv and result.sql must be in the working directory: {work_dir}
- Budget: you have {max_turns} turns — explore efficiently, then focus on writing correct SQL

{backend_tips}
"""
