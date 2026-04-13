---
name: sql-workflow
description: "Use this skill before writing any SQL query. Covers: efficient schema exploration, query writing strategy, result verification, saving output to result.sql and result.csv, and turn budget management for SQL benchmark tasks."
type: skill
---

# SQL Workflow Skill

## 1. Schema Exploration — Do This First

Before writing any SQL, understand the data:

1. Call `schema_overview` to get a list of all schemas and tables
2. Call `describe_table` on the tables that seem relevant to the question
3. Call `explore_column` on categorical columns to see distinct values (for filtering/grouping)
4. Call `find_join_path` if you need to join tables and the relationship is unclear

Stop exploring after 3-5 tool calls. Write SQL based on what you've found.

## 2. Query Writing Strategy

- Start simple: write the query in parts and test each part
- Use CTEs to build up complex queries step by step
- Check row counts after each step: `SELECT COUNT(*) FROM ...`
- Verify no fan-out from JOINs: `SELECT COUNT(*) vs COUNT(DISTINCT key)`

## 3. Execution and Verification

```
mcp__signalpilot__query_database
  connection_name="<task_connection_name>"
  sql="SELECT ..."
```

After getting results:
- Check: does the row count make sense?
- Check: are the values in the expected range?
- Check: are there unexpected NULLs?

## 4. Saving Output

Once you have the correct result:

1. Write final SQL to `result.sql`:
   ```
   Write tool: path="result.sql", content="<your SQL query>"
   ```

2. Write the result as CSV to `result.csv`:
   ```
   Write tool: path="result.csv", content="col1,col2,...\nval1,val2,..."
   ```
   - Always include a header row with column names
   - Use comma as delimiter
   - Quote string values that contain commas or newlines

## 5. Turn Budget Management

- **First 20% of turns**: Explore schema, understand data shape. STOP exploring.
- **Middle 60% of turns**: Write SQL, execute, verify, iterate.
- **Last 20% of turns**: Write result.sql and result.csv. Do not start new exploration.

If you have the correct result, write the output files immediately — do not continue exploring.

## 6. Common Pitfalls

- **Fan-out from JOINs**: Always check `COUNT(*) vs COUNT(DISTINCT key)` after joining
- **Wrong NULL handling**: Use `IS NULL` / `IS NOT NULL`, not `= NULL`
- **Date format mismatch**: Check the actual format stored in the column with `explore_column`
- **Case sensitivity**: Use the correct case-insensitive function for your backend
- **Column name in output**: Match the column names expected by the question exactly
