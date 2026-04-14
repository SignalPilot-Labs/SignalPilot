"""Prompt builders for SQL-based benchmark suites (spider2-snowflake, spider2-lite)."""

from __future__ import annotations

from pathlib import Path

from ..core.suite import DBBackend


def _build_snowflake_tips() -> str:
    return (
        "SNOWFLAKE-SPECIFIC TIPS:\n"
        "- Use QUALIFY to filter window function results without a subquery\n"
        "- Use ILIKE for case-insensitive string matching\n"
        "- Use LATERAL FLATTEN(input => col) or FLATTEN(col) to expand arrays\n"
        "- Date arithmetic: DATEADD(day, N, col), DATEDIFF(day, start, end)\n"
        "- Semi-structured: col:field for VARIANT, PARSE_JSON for JSON strings\n"
        "- String functions: SPLIT_PART, REGEXP_SUBSTR, TRIM, UPPER/LOWER\n"
        "- Null-safe equality: col IS NOT DISTINCT FROM other_col\n"
        "- LISTAGG for string aggregation: LISTAGG(col, ',') WITHIN GROUP (ORDER BY col)\n"
        "\n"
        "LARGE DATABASE STRATEGY (CMS_DATA, STACKOVERFLOW, NHTSA_TRAFFIC_FATALITIES, WORLD_BANK):\n"
        "- Skip schema_overview entirely — use list_tables or read DDL.csv instead\n"
        "- Always use fully qualified names: SCHEMA_NAME.TABLE_NAME\n"
        "- Column names in Snowflake are UPPERCASE by default. Use UPPER case in SQL.\n"
        "- Do NOT iterate on column case — check with describe_table ONCE, then use those exact names.\n"
        "- Add LIMIT 100 to exploratory queries to avoid timeouts.\n"
        "- Non-PUBLIC schemas: Most Spider2 databases store data in named schemas, not PUBLIC.\n"
        "  Always check with list_tables which schema has the actual tables.\n"
        "\n"
        "SNOWFLAKE CRITICAL GOTCHAS:\n"
        "- IDENTIFIER CASE: Unquoted identifiers are uppercased. If a column was created with\n"
        '  double-quotes as "myCol", you must reference it as "myCol" (quoted). Check with describe_table.\n'
        "- FLOAT vs NUMBER: Snowflake defaults to NUMBER(38,0) for integers. Do not CAST to FLOAT\n"
        "  for aggregations — precision loss will fail evaluation."
    )


def _build_bigquery_tips() -> str:
    return (
        "BIGQUERY-SPECIFIC TIPS:\n"
        "- Use UNNEST(array_col) to expand array columns\n"
        "- Date arithmetic: DATE_ADD(col, INTERVAL N DAY), DATE_DIFF(end, start, DAY)\n"
        "- Table references: `project.dataset.table` (backtick-quoted)\n"
        "- EXCEPT DISTINCT / UNION DISTINCT remove duplicates automatically\n"
        "- SELECT * EXCEPT (col1) or SELECT * REPLACE (expr AS col1)\n"
        "- STRUCT constructor: STRUCT(val1, val2) or STRUCT(val AS name)\n"
        "- Approximate aggregation: APPROX_COUNT_DISTINCT for large cardinality\n"
        "- Default project for Spider2 tasks: `spider2-public-data`\n"
        "- Dataset reference: `spider2-public-data.{dataset}.{table}` or just `{dataset}.{table}` if default project is set\n"
        "- INFORMATION_SCHEMA: Use `{dataset}.INFORMATION_SCHEMA.COLUMNS` to discover table schemas when MCP tools are slow\n"
        "- Always verify filter conditions against actual column values using explore_column before assuming value formats\n"
        "\n"
        "BIGQUERY CRITICAL PATTERNS:\n"
        "- StackOverflow tags: pipe-delimited e.g. '|python|python-2.7|'.\n"
        "  For 'Python 2 specific': WHERE REGEXP_CONTAINS(tags, r'\\|python-2\\.\\d+\\|') AND NOT REGEXP_CONTAINS(tags, r'\\|python-3')\n"
        "  IMPORTANT: The pipe delimiters are part of the format. Always check actual values with explore_column first.\n"
        "- Always check partition columns — unfiltered scans may timeout or be blocked.\n"
        "- Default project: spider2-public-data. Omit project if connection already points to it.\n"
        "- Use INFORMATION_SCHEMA.COLUMNS for schema discovery instead of MCP tools when faster.\n"
        "- accepted_answer_id: Check if it's an ID column (join to answers table) or a boolean.\n"
        "- view_count, answer_count: These are per-question metrics, not per-answer.\n"
        "- For 'maximum number of answers': COUNT answers grouped by question, then MAX."
    )


def _build_sqlite_tips() -> str:
    return (
        "SQLITE-SPECIFIC TIPS:\n"
        "- String concatenation: use || operator (not CONCAT)\n"
        "- Substring: substr(col, start, length) — 1-indexed\n"
        "- Find position: instr(haystack, needle)\n"
        "- LIKE is case-insensitive for ASCII by default\n"
        "- No ILIKE — use LIKE or LOWER(col) LIKE LOWER(pattern)\n"
        "- No FULL OUTER JOIN — use UNION of LEFT JOINs\n"
        "- Date functions: date(), datetime(), strftime() for formatting\n"
        "- Type casting: CAST(col AS INTEGER), CAST(col AS REAL)\n"
        "\n"
        "SPIDER2 SQLITE GOTCHAS:\n"
        "- Tables often have inconsistent casing — use PRAGMA table_info(table_name) to check\n"
        "- Many SQLite databases have TEXT columns storing numbers — CAST to REAL/INTEGER for math\n"
        "- Date columns are often TEXT in YYYY-MM-DD format — use date() for comparison\n"
        "- Some databases have salary/monetary columns with commas or currency symbols —\n"
        "  use REPLACE to clean before CAST: CAST(REPLACE(col, ',', '') AS REAL)\n"
        "- No QUALIFY clause — wrap in subquery: SELECT * FROM (SELECT ..., ROW_NUMBER() ...) WHERE rn = 1"
    )


def _build_duckdb_tips() -> str:
    return (
        "DUCKDB-SPECIFIC TIPS:\n"
        "- Use QUALIFY to filter window function results without a subquery\n"
        "- Date arithmetic: INTERVAL N DAYS, DATE_TRUNC('month', col)\n"
        "- STRPTIME(col, '%Y-%m-%d') for non-ISO date parsing\n"
        "- String functions: regexp_extract, string_split, str_split_regex\n"
        "- PIVOT / UNPIVOT for reshaping data"
    )


def _get_backend_tips(backend: DBBackend) -> str:
    _BUILDERS = {
        DBBackend.SNOWFLAKE: _build_snowflake_tips,
        DBBackend.BIGQUERY: _build_bigquery_tips,
        DBBackend.SQLITE: _build_sqlite_tips,
        DBBackend.DUCKDB: _build_duckdb_tips,
    }
    builder = _BUILDERS.get(backend)
    if builder is None:
        return "- Use standard SQL syntax"
    return builder()


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
    backend_tips = _get_backend_tips(db_backend)
    mandatory_save_turn = max_turns - 4

    return f"""You are a SQL expert. Answer the following question by writing and executing SQL.

TASK: {instruction}

DATABASE: SignalPilot connection '{connection_name}' (backend: {db_backend.value}).

HOW YOUR OUTPUT IS EVALUATED:
Your result.csv is compared against a gold CSV by an automated evaluator:
- ROW COUNT must match EXACTLY — one extra or missing row = task failure, no partial credit
- Column VALUES are compared, NOT column names — each gold column vector is matched against ANY
  of your result columns. Column names are cosmetic; only values matter.
- Float tolerance: 0.01 absolute (3.14159 matches 3.14)
- Dates: '2024-01-01 00:00:00' matches '2024-01-01' (datetime suffixes are stripped)
- Row order does NOT matter (results are sorted before comparison)

PRIORITY ORDER: (1) correct row count > (2) correct values > (3) correct column count > (4) column names
Do NOT waste turns renaming columns. DO spend turns on getting row count and values right.

WORKFLOW — follow these steps in order:

1. SCHEMA DISCOVERY (turns 1-2, minimize MCP calls):
   a. READ LOCAL SCHEMA FILES FIRST — if a schema/ directory and DDL.csv exist in your workdir:
      - Read DDL.csv for CREATE TABLE statements (gives you all table names + columns)
      - Read {{table_name}}.json files for column descriptions, types, and sample data
      This is FREE (no tool calls) and gives you 80% of what you need.
   b. mcp__signalpilot__list_tables — only if no local schema files exist. Lists all tables with column names and row counts.
   c. mcp__signalpilot__describe_table — column details for the 2-3 most relevant tables (only if JSON files lack detail)
   d. mcp__signalpilot__explore_column — distinct values for key categorical columns (use sparingly, 1-2 calls max)
   Do NOT call schema_overview — it is slow. Do NOT spend more than 2 tool calls on discovery.

2. PLAN THE QUERY (turns 3-4, before writing SQL):
   - Read the question for cardinality clues: "for each X" = GROUP BY, "top N" = LIMIT/QUALIFY,
     "total/sum" = 1-row aggregate, "how many" = COUNT (1 row result)
   - COUNT SEMANTICS — read the question carefully:
     * "How many [things]" = COUNT(DISTINCT thing_identifier), NOT COUNT(*)
       Example: "How many indicators have value 0" = COUNT(DISTINCT indicator_name) WHERE value = 0
       Example: "How many customers ordered" = COUNT(DISTINCT customer_id)
     * "How many rows/records/entries" = COUNT(*) — only when the question explicitly says rows/records
     * "How many times" = COUNT(*) — counting occurrences, not distinct entities
     * When in doubt, ask: "Am I counting unique entities or total rows?" — usually unique entities.
   - COLUMN COUNT RULE: Count the distinct pieces of information the question asks for.
     "Find the name and salary" = 2 columns. "Top 5 countries by GDP" = at least 2 columns
     (country + GDP). If you have more columns than the question implies, remove the extras.
   - COLUMN NAMING — the output column name must reflect the question's intent:
     * "How many debt indicators" -> zero_value_indicator_count, NOT just "count"
     * Use AS to give every computed column a descriptive snake_case alias
     * Never leave a column named COUNT(*) or SUM(...) — always alias it
   - AGGREGATION LEVEL — match the question's granularity exactly:
     * "for each X" = one row per X. Your GROUP BY must be X, nothing else.
     * "the top X" = exactly X rows (or fewer if tied). Use LIMIT X or QUALIFY.
     * "for each X, the top Y" = at most X*Y rows. Use QUALIFY or a correlated subquery.
     * If the question asks for a single value per group, do NOT return multiple rows per group.
     * Compare your result row count against the expected shape BEFORE saving.
   - Write a comment: -- EXPECTED: <row count estimate> rows because <reason>

3. BUILD INCREMENTALLY (turns 5 through {mandatory_save_turn - 1}, do not write a 50-line query and run it):
   - Write the innermost CTE first, run it standalone, verify row count and values
   - Add the next CTE, verify again — continue until the full query is built
   - Use: mcp__signalpilot__validate_sql connection_name="{connection_name}" sql="..." before executing
   - Then: mcp__signalpilot__query_database connection_name="{connection_name}" sql="..."

4. VERIFY BEFORE SAVING — run these checks in order:
   a. Row count: does 0 rows make sense? Does 1M rows make sense for a "top 10" question?
      Run: SELECT COUNT(*) FROM (<your_query>) sub; — compare against your EXPECTED comment.
   b. Column count: right number of columns for the question?
   c. NULL audit: SELECT COUNT(*) - COUNT(col) AS nulls FROM (your_query) t — unexpected NULLs = wrong JOIN
   d. Sample: look at 5 rows — are values in expected ranges? Are string columns meaningful?
   e. Fan-out: if JOINing, run SELECT COUNT(*), COUNT(DISTINCT <pk>) FROM (your_query) t
      If they differ, you have duplicate rows — fix the JOIN before saving.
   f. Re-read the question: does your output actually answer what was asked?
   g. Semantic cross-check: if the question asks "how many X", verify your count is plausible.
      Run: SELECT COUNT(*) as total_rows, COUNT(DISTINCT x_column) as distinct_x FROM source_table WHERE <conditions>
      If your result equals total_rows but distinct_x is much smaller, you likely need COUNT(DISTINCT).
   h. Gold-format alignment: Re-read the question one more time. If it asks for
      "the name and the count", your CSV must have exactly 2 columns with descriptive names.
      If it asks for "top 5 by revenue", your CSV must have at most 5 rows.
      Count your columns and rows — if they do not match the question, fix the query.
   i. INTERPRETATION CHECK — before saving, verify these in a SQL comment:
      - What EXACTLY is the question asking? Restate it in your own words.
      - Are there implicit filters? ("Python 2 specific" = tags containing 'python-2.x' AND NOT 'python-3.x')
      - Are there domain-specific terms? ("rainy weather" = specific weather_condition values, check with explore_column)
      - Does "excluding" mean WHERE NOT or EXCEPT?
      - If the question mentions a specific metric (e.g., "scored points"), verify your calculation matches the domain definition.
      Write a SQL comment: -- INTERPRETATION: <your restatement>

   SAVE EARLY, SAVE OFTEN: Once you have a query that returns plausible results, save result.csv
   and result.sql IMMEDIATELY. You can always overwrite them later with improved results.
   An imperfect result.csv beats a missing one — rate limits and timeouts are real failure modes.

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

CRITICAL — DO NOT (VIOLATION = INSTANT FAILURE):
- NEVER read, explore, or modify source code files (*.py, *.js, *.json in repo dirs). You are a SQL analyst.
- NEVER debug MCP server internals, gateway infrastructure, or connection code. The tools WORK.
- NEVER try to start, restart, or configure the HTTP gateway. It is intentionally not running.
- NEVER install Python packages, read encryption keys, or inspect credential files.
- NEVER use Bash to connect to databases directly (pip install snowflake-connector-python, etc.)
- NEVER spend more than 1 turn on ANY non-SQL activity.
- If an MCP tool returns slowly (30+ seconds), that is NORMAL for large databases — NOT an error.
- If an MCP tool returns an error message, try a DIFFERENT QUERY or a different MCP tool — do NOT investigate code.
- If query_database fails, try simpler SQL (add LIMIT 10) — the connection is fine, your SQL may be wrong.
- If list_tables returns empty or errors, try: mcp__signalpilot__schema_ddl or read schema/ files.
- Tables may be in a non-PUBLIC schema. Use fully qualified names: SCHEMA.TABLE (e.g., STACKOVERFLOW.POSTS_QUESTIONS).
- YOUR JOB: Write SQL. Save CSV. Nothing else.

TURN BUDGET: You have {max_turns} turns. Use them as follows:
- Turns 1-2: Schema discovery (read local files, at most 1 MCP call)
- Turns 3-4: Plan query, write EXPECTED comment
- Turns 5 through {mandatory_save_turn - 1}: Build and verify query iteratively
- Turn {mandatory_save_turn}: MANDATORY SAVE — write result.csv and result.sql with whatever you have
- Remaining turns: Improve if possible, re-save with better results

If you reach turn {mandatory_save_turn - 1} without a result.csv, STOP debugging and save your best attempt.
If your query works and passes all verification checks, SAVE IMMEDIATELY — do not keep iterating.

{backend_tips}
"""
