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

WORKFLOW — follow these steps in order:

1. SCHEMA DISCOVERY (at most 3-5 tool calls — stop when you have enough):
   - mcp__signalpilot__schema_overview — high-level overview of schemas and tables
   - mcp__signalpilot__describe_table — column details for relevant tables
   - mcp__signalpilot__explore_column — distinct values for key categorical columns
   - mcp__signalpilot__find_join_path — if join relationships are unclear
   STOP after 3-5 calls. Do not explore exhaustively.

2. PLAN THE QUERY (before writing SQL):
   - Read the question for cardinality clues: "for each X" = GROUP BY, "top N" = LIMIT/QUALIFY,
     "total/sum" = 1-row aggregate, "how many" = COUNT (1 row result)
   - Write a comment: -- EXPECTED: <row count estimate> rows because <reason>

3. BUILD INCREMENTALLY (do not write a 50-line query and run it):
   - Write the innermost CTE first, run it standalone, verify row count and values
   - Add the next CTE, verify again — continue until the full query is built
   - Use: mcp__signalpilot__validate_sql connection_name="{connection_name}" sql="..." before executing
   - Then: mcp__signalpilot__query_database connection_name="{connection_name}" sql="..."

4. VERIFY BEFORE SAVING — run these checks in order:
   a. Row count: does 0 rows make sense? Does 1M rows make sense for a "top 10" question?
   b. Column count: right number of columns for the question?
   c. NULL audit: SELECT COUNT(*) - COUNT(col) AS nulls FROM (your_query) t — unexpected NULLs = wrong JOIN
   d. Sample: look at 5 rows — are values in expected ranges? Are string columns meaningful?
   e. Fan-out: if JOINing, run SELECT COUNT(*), COUNT(DISTINCT <pk>) FROM (your_query) t
      If they differ, you have duplicate rows — fix the JOIN before saving.
   f. Re-read the question: does your output actually answer what was asked?

5. ERROR RECOVERY — diagnose, do not just retry:
   - Syntax error: use validate_sql to catch errors before burning a query turn
   - Zero rows: remove WHERE conditions one at a time to find the culprit
   - Too many rows: check for missing GROUP BY or fan-out from JOINs
   - Use mcp__signalpilot__debug_cte_query to run each CTE step independently

6. IF wrong results from a JOIN — check cardinality of the right-side table first:
   SELECT COUNT(*), COUNT(DISTINCT join_key) FROM right_table
   If COUNT(*) > COUNT(DISTINCT join_key): pre-aggregate before joining

7. SAVE — write both output files to: {work_dir}
   - result.sql: your final SQL query
   - result.csv: the query result as CSV with header row

RULES:
- Use {db_backend.value}-compatible SQL syntax only
- Read-only queries — do NOT modify the database (no INSERT/UPDATE/DELETE/CREATE/DROP)
- result.csv must include a header row with column names
- result.csv and result.sql must be in the working directory: {work_dir}
- Column names in result.csv must match the question's phrasing exactly
  (e.g., if question says "total revenue", name the column total_revenue)
- Do NOT round numeric values unless the question explicitly asks for rounding
- Date values in CSV: use ISO 8601 (YYYY-MM-DD) unless the question specifies otherwise
- String case in CSV: preserve the case from the database — do not change case unless asked
- If the correct answer is 0 or empty: write a CSV with just the header row (or header + "0")

TURN BUDGET: You have {max_turns} turns.
- Spend at most 20% on schema exploration (turns 1-3).
- Spend 60% on query building, executing, and debugging.
- Spend the last 20% on verification and saving result files.
- If your query works and passes all verification checks, SAVE IMMEDIATELY.
- Do not keep iterating once you have a correct-looking result.

{backend_tips}
"""
