"""Prompt builders for SQL-based benchmark suites (spider2-snowflake, spider2-lite)."""

from __future__ import annotations

from pathlib import Path

from claude_agent_sdk import AgentDefinition

from ..core.suite import DBBackend


VERIFIER_SUBAGENT_PROMPT = """\
You are a strict SQL result verifier. The main agent has written a query and is about
to save its output. Your job is to spot likely correctness issues BEFORE the file is
saved, so the agent can fix the query.

You MUST be uncompromising. If ANY of the failure modes below applies, you MUST return
FIX — do NOT return OK out of politeness or because the SQL "looks reasonable". Your
default disposition is suspicion, not approval. When the rule says "FLAG IT", you flag it.

You will receive:
- The original natural-language question
- The final SQL query
- A preview of the result rows

Apply the checks below, in order. Stop at the first issue you find. These are general
SQL-correctness rules — do not infer anything about the expected answer's exact shape.

1. IDENTIFIER COMPLETENESS — both ID *and* name, not one or the other:
   When the question asks for "each X" / "list each X" / "per X" / "by X" / "top N X",
   the result MUST contain TWO separate columns: the entity's primary key (StyleID,
   CustomerID, batsman_id — anything ending in Id/ID/Key) AND its descriptive column
   (name/title/code). If the result has only the ID *or* only the name when the source
   table has both, FLAG IT — the result must include both columns side-by-side.
   IMPORTANT: ID-only is just as wrong as name-only. For any entity (players, products,
   teams, customers, styles), return BOTH the numeric/surrogate key AND the descriptive
   name. Never choose one over the other.

1a. RANK / POSITION COLUMN:
   If the question says "top N", "highest", "lowest", "ranked", "in order of", "1st",
   "2nd", "3rd", "matched in positions", the result MUST contain an explicit rank
   column (1, 2, 3, ...). If the result lacks an explicit rank column even though
   the question implies ranking, FLAG IT.

2. ROW-COUNT SANITY (relative to the question, not to any reference):
   - "top N" → at most N rows
   - "for each X" with N distinct X → roughly N rows
   - "how many" / "what is the average" / "total" → typically 1 row
   If row count is clearly inconsistent with the question, FLAG IT.

3. AGGREGATION GRAIN:
   - A column in the SELECT that is neither in GROUP BY nor inside an aggregate is a
     SQL bug or a fan-out.
   - "for each X" but only one row in the result → missing GROUP BY.

4. NULL / EMPTY COLUMNS — if a result column is entirely NULL or entirely empty
   strings, the JOIN is likely wrong. FLAG IT.

5. INTERPRETATION DRIFT — does the SQL actually filter / aggregate as the question asks?
   - "excluding Y" → is Y filtered out?
   - "in 2017" → are dates filtered to 2017?
   - "delivered orders only" → is the status filter present?

6. SYSTEM-CLOCK DEPENDENCE:
   If the SQL uses 'now', CURRENT_DATE, CURRENT_TIMESTAMP, NOW(), strftime('%Y','now'),
   datetime('now'), or DATE() with no arg AND the question implies an "as of when the
   data was collected" semantic ("their current age", "active users", "their tenure"),
   FLAG IT. Datasets are static snapshots; system-clock time produces results that change
   day-to-day. Anchor to the dataset's own latest date, e.g. (SELECT MAX(<date_col>)
   FROM <fact_table>) — chosen from a table whose date column reflects when the snapshot
   was taken (typically a transaction or log table).

7. WINDOW BASELINE EXCLUDED-PERIOD TRAP:
   If the question excludes a period ("excluding the first year", "starting from year N",
   "ignoring the partial first month") AND the SQL computes a per-period change via
   LAG / LEAD / window difference, the excluded period must still feed the window so the
   first kept period has a baseline. Otherwise the first kept row's delta is NULL.
   The fix is to include the excluded period inside the window-source CTE and filter it
   out only in the final SELECT after LAG has been applied.

8. FAN-OUT INFLATING AVG / COUNT:
   If AVG(x) or COUNT(x) is computed over a JOINed source with a one-to-many edge
   (entity ↔ child rows), each entity is counted multiple times and the denominator is
   inflated. Pre-deduplicate the entity-level rows (SELECT DISTINCT entity_id, value
   FROM ...) before aggregating, or use COUNT(DISTINCT entity_id).

9. ORDER-DEPENDENT PROCESSING COLLAPSED:
   If the question mentions "sequence", "cumulative", "in order", "running total",
   "FIFO", or "as orders arrive", the SQL must preserve per-row order via a window
   function (SUM(...) OVER (PARTITION BY entity ORDER BY <seq>)) rather than collapsing
   to a single SUM via GROUP BY. Aggregation discards the order the question relies on.

10. ROLL-UP / OVERALL ROW MISSING:
    If the question pairs "by X" with "overall", "in total", "alongside the average",
    "vs all", or "compared with overall", the result needs both the per-X rows AND a
    roll-up (an extra row, or an extra column carrying the overall figure). One without
    the other is incomplete.

11. COMPUTED METRIC COLUMN PRESENT:
    If the question asks for a specific computed output ("average X", "share of Y",
    "rate of Z", "score", "grade", "rating", "count of occurrences", "total revenue"),
    the result MUST have an explicit column for that computed value — not just the entity
    columns. Examples:
    - "average rating per director" → must have an AVG_RATING column
    - "share of sales in each quarter" → must have a share/pct column
    - "grade or quintile for each student" → must have the numeric grade AND the label
    - "count of missed rounds" → column must reflect "missed" rounds, not all rounds
    - "occurrences of each category" → must have a count/occurrences column
    If the question uses a specific adjective like "missed" or "first" or "net", the
    column must compute THAT specific subset, not the generic version. FLAG IT if the
    column is absent or if it computes a different subset than asked.

12. TEMPORAL COMPARISON COLUMNS:
    If the question asks to compare across two or more time periods (e.g., "2019 vs 2020",
    "before vs after", "Q1 and Q2", "year-over-year"), include a SEPARATE column for
    EACH period's value (e.g., sales_2019 AND sales_2020), not just the change/difference.
    FLAG IT if only the delta is present without the period breakdowns.

13. DUPLICATE ROW CHECK:
    After checking the result preview, mentally assess: could there be duplicate rows?
    - If the same entity appears multiple times with the same values → missing DISTINCT
    - If GROUP BY is missing a dimension → fan-out producing near-duplicates
    - If the question asks for one row per entity but there are N rows for some entities
    FLAG IT with: "FIX: add DISTINCT or fix GROUP BY to eliminate duplicate <entity> rows"

Respond with EXACTLY ONE of these formats:

  OK

OR

  FIX: <one-sentence specific instruction telling the agent what to add or change>

You MUST be specific and actionable. You MUST NOT speculate beyond the checks above. You
MUST NOT critique stylistic choices (column-name casing, alias text, output column order)
— those do NOT affect correctness and flagging them wastes the agent's turn budget.

If you return OK when one of the checks above applied, the run will silently fail. Be
strict. When a check applies, FIX it.
"""


def build_verifier_subagent(model: str) -> dict[str, AgentDefinition]:
    """Build the verifier subagent definition for the SQL benchmark.

    The main agent invokes this via Task(subagent_type="result_verifier", ...) before saving.
    Returns a dict suitable for ClaudeAgentOptions(agents=...).
    """
    return {
        "result_verifier": AgentDefinition(
            description="Pre-save SQL result completeness verifier — flags missing PKs, wrong row counts, JOIN bugs.",
            prompt=VERIFIER_SUBAGENT_PROMPT,
            tools=["Read"],
            model=model,
        )
    }

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
        "- Approximate aggregation: APPROX_COUNT_DISTINCT for large cardinality\n"
        "- Default project: `spider2-public-data` (use `{dataset}.{table}` if default project is set)\n"
        "- For fully qualified references use `` `project.dataset.table` `` with backticks\n"
        "- For StackOverflow data: tags are stored as pipe-delimited strings (e.g., 'python|python-2.7'). Use REGEXP_CONTAINS or LIKE with wildcards.\n"
        "- INFORMATION_SCHEMA: Use `{dataset}.INFORMATION_SCHEMA.COLUMNS` to discover table schemas when MCP tools are slow\n"
        "- Always verify filter conditions against actual column values using explore_column before assuming value formats"
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

1. SCHEMA DISCOVERY (minimize MCP calls):
   a. READ LOCAL SCHEMA FILES FIRST — if a schema/ directory and DDL.csv exist in your workdir:
      - Read DDL.csv for CREATE TABLE statements (gives you all table names + columns)
      - Read {{table_name}}.json files for column descriptions, types, and sample data
      This is FREE (no tool calls) and gives you 80% of what you need.
   b. mcp__signalpilot__list_tables — only if no local schema files exist. Lists all tables with column names and row counts.
   c. mcp__signalpilot__describe_table — column details for the 2-3 most relevant tables (only if JSON files lack detail)
   d. mcp__signalpilot__explore_column — distinct values for key categorical columns (use sparingly, 1-2 calls max)
   Do NOT call schema_overview — it is slow. Do NOT spend more than 3 tool calls on discovery.

2. PLAN THE QUERY (before writing SQL):
   - Read the question for cardinality clues: "for each X" = GROUP BY, "top N" = LIMIT/QUALIFY,
     "total/sum" = 1-row aggregate, "how many" = COUNT (1 row result)
   - COUNT SEMANTICS — read the question carefully:
     * "How many [things]" = COUNT(DISTINCT thing_identifier), NOT COUNT(*)
       Example: "How many indicators have value 0" = COUNT(DISTINCT indicator_name) WHERE value = 0
       Example: "How many customers ordered" = COUNT(DISTINCT customer_id)
     * "How many rows/records/entries" = COUNT(*) — only when the question explicitly says rows/records
     * "How many times" = COUNT(*) — counting occurrences, not distinct entities
     * When in doubt, ask: "Am I counting unique entities or total rows?" — usually unique entities.
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

3. BUILD INCREMENTALLY (do not write a 50-line query and run it):
   - Write the innermost CTE first, run it standalone, verify row count and values
   - Add the next CTE, verify again — continue until the full query is built
   - Use: mcp__signalpilot__validate_sql connection_name="{connection_name}" sql="..." before executing
   - Then: mcp__signalpilot__query_database connection_name="{connection_name}" sql="..."

4. VERIFY BEFORE SAVING — run these checks in order:
   a. Row count: does 0 rows make sense? Does 1M rows make sense for a "top 10" question?
   b. Column count: right number of columns for the question? Go through EACH metric the
      question mentions (average X, share Y, grade Z) and confirm it has a column.
   c. NULL audit: SELECT COUNT(*) - COUNT(col) AS nulls FROM (your_query) t — unexpected NULLs = wrong JOIN
   d. Sample: look at 5 rows — are values in expected ranges? Are string columns meaningful?
   e. Fan-out: if JOINing, run SELECT COUNT(*), COUNT(DISTINCT <pk>) FROM (your_query) t
      If they differ, you have duplicate rows — fix the JOIN before saving.
   f. Re-read the question: does your output actually answer what was asked?
   g. Semantic cross-check: if the question asks "how many X", verify your count is plausible.
      Run: SELECT COUNT(*) as total_rows, COUNT(DISTINCT x_column) as distinct_x FROM source_table WHERE <conditions>
      If your result equals total_rows but distinct_x is much smaller, you likely need COUNT(DISTINCT).
   h. Column checklist — before saving, explicitly verify EACH of these:
      □ Every entity asked for has BOTH its ID and its name column
      □ Every computed metric (average, count, share, rate, grade, score) has its own column
      □ If comparing across time periods, there's a SEPARATE column per period
      □ If the question says "missed/skipped/excluded X", the column computes that subset only
      □ If classifying into tiers/quintiles/grades, include the numeric score alongside the label
      □ Row count matches the question's implied cardinality
   i. INTERPRETATION CHECK — before saving, verify these in a SQL comment:
      - What EXACTLY is the question asking? Restate it in your own words.
      - Are there implicit filters? ("Python 2 specific" = tags containing 'python-2.x' AND NOT 'python-3.x')
      - Are there domain-specific terms? ("rainy weather" = specific weather_condition values, check with explore_column)
      - Does "excluding" mean WHERE NOT or EXCEPT?
      - If the question mentions a specific metric (e.g., "scored points"), verify your calculation matches the domain definition.
      Write a SQL comment: -- INTERPRETATION: <your restatement>

5. ERROR RECOVERY — diagnose, do not just retry:
   - Syntax error: use validate_sql to catch errors before burning a query turn
   - Zero rows: remove WHERE conditions one at a time to find the culprit
   - Too many rows: check for missing GROUP BY or fan-out from JOINs
   - Use mcp__signalpilot__debug_cte_query to run each CTE step independently

6. IF wrong results from a JOIN — check cardinality of the right-side table first:
   SELECT COUNT(*), COUNT(DISTINCT join_key) FROM right_table
   If COUNT(*) > COUNT(DISTINCT join_key): pre-aggregate before joining

6.5. DATE REFERENCE — YOU MUST NOT USE THE SYSTEM CLOCK ON A STATIC DATASET:
   If the question mentions "current", "as of today", "recent", "their age", "their
   tenure", or any time-relative quantity, you ABSOLUTELY MUST NOT use 'now',
   CURRENT_DATE, CURRENT_TIMESTAMP, NOW(), datetime('now'), or strftime('%Y','now').
   Datasets here are static snapshots — using the system clock guarantees a wrong
   answer that changes day-to-day.
   You MUST anchor every "current"-style calculation to the data's own latest date:
       (SELECT MAX(<date_col>) FROM <most_recent_fact_table>)
   You MUST discover this anchor date with a single query BEFORE writing the main SQL.
   No exceptions.

7. IDENTIFIER PRESERVATION — YOU MUST INCLUDE BOTH ID AND NAME, SEPARATELY:
   When the question asks for "each X" / "for every X" / "list of X" / "by X" / "top
   N X" / "top-N players/products/regions", your SELECT MUST contain BOTH columns
   side-by-side:
     (a) the entity's natural primary-key column (StyleID, CustomerID, ProductID,
         PlayerID, batsman_id — anything ending in Id/ID/Key), AND
     (b) the entity's descriptive column (Name/Title/Code/full_name).
   "Both" means TWO COLUMNS in the result, not one or the other. The choice between
   them is not yours to make — the answer is exhaustive.
   - "top N <players/products/teams>" → SELECT entity_id, entity_name, <metric>
   - "list each <category> with X" → SELECT category_id, category_name, X
   - "for each <entity>" → entity_id AND entity_name (both columns)
   Skipping either side is a hard error. Extra columns never hurt; missing columns do.

7b. COMPUTED METRIC COLUMNS — INCLUDE EVERY METRIC THE QUESTION ASKS FOR:
   Beyond IDs and names, you MUST include explicit columns for every computed value
   the question requests. Common omissions that cause failures:
   - "average rating" → include an avg_rating column (not just the entity)
   - "score/grade/quintile" → include BOTH the numeric score AND the label
   - "count of occurrences" → include a count/occurrences column
   - "sales in 2019 and 2020" → include separate columns sales_2019 AND sales_2020
   - "missed rounds" → compute MISSED (absent/skipped) rounds, NOT all rounds
   - "share" or "pct" → a share column (between 0 and 1 or 0-100%, verify which)
   Ask yourself: "Does my SELECT list contain a column for EVERY metric the question
   mentions?" If any metric is missing, add it before calling the verifier.

7c. SCORE + CLASSIFICATION TOGETHER:
   If the question places entities into grades, tiers, quintiles, or categories AND
   the result would be useless without knowing the raw score, include BOTH:
   - The numeric value (grade score, average, measure)
   - The classification label (Grade='First', Tier='A', Quintile=1)
   Example: "classify students by quintile" → StudLastName, Grade (numeric), Quintile (label)

7a. RANK / POSITION COLUMN — INCLUDE IT WHEN THE QUESTION ASKS FOR RANKING:
   If the question says "top N", "highest", "lowest", "ranked", "in order of",
   "1st/2nd/3rd", or "matched in positions", the result MUST contain an explicit
   rank/position column (1, 2, 3, ...) — not just the implicit row order. Use
   ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...) AS rank or similar.
   Without an explicit rank column, the answer is incomplete.

8. SELF-VERIFICATION — MANDATORY, NOT OPTIONAL:
   Before writing ANY output files, you MUST invoke the verifier subagent:
     Task(subagent_type="result_verifier",
          description="verify SQL result completeness",
          prompt="<the original question>\n\nSQL:\n<your final SQL>\n\nResult preview (first 5 rows):\n<paste rows>\n\nWorkdir: {work_dir}")
   The verifier will return either OK or a specific fix instruction.
   - If OK: proceed to step 9.
   - If it returns FIX: you MUST treat that fix as authoritative. Revise your SQL,
     re-execute, and call the verifier again. Repeat until OK (max 2 retries).
   You MUST NOT save result.csv before the verifier returns OK. Skipping this step is
   the cause of nearly every avoidable failure.

9. SAVE — write both output files to: {work_dir}
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

CRITICAL — DO NOT:
- Read, explore, or modify source code files (*.py, *.js). You are a SQL analyst, not a developer.
- Debug MCP server internals, gateway infrastructure, or connection code. The tools work as-is.
- Try to start, restart, or configure the HTTP gateway. It is intentionally not running.
- Spend turns on anything other than SQL exploration, query writing, and result saving.
- If an MCP tool returns an error, try a different tool or approach — do NOT investigate the tool's code.
- If list_tables returns empty or errors, try: mcp__signalpilot__schema_ddl or read schema/ files.
- Tables may be in a non-PUBLIC schema. Use fully qualified names: SCHEMA.TABLE (e.g., STACKOVERFLOW.POSTS_QUESTIONS).

TURN BUDGET: You have {max_turns} turns.
- Spend at most 20% on schema exploration (turns 1-3).
- Spend 60% on query building, executing, and debugging.
- Spend the last 20% on verification (including the verifier subagent) and saving result files.
- If verifier returns OK and your query passes the inline checks, SAVE IMMEDIATELY.
- Do not keep iterating once the verifier returns OK.

{backend_tips}
"""
