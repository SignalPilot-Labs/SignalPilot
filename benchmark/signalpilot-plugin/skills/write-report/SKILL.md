---
name: write-report
description: "Generates an HTML report summarizing dbt project work: decisions, SQL, queries, verifier results, and visual charts. Only load when explicitly requested."
disable-model-invocation: true
---

# Write Report

Generate a single self-contained HTML file at `<project_dir>/report.html` that
gives the user complete confidence in what was built and why.

## When to Load

Load this skill ONLY after Step 8 verification is complete and all checks pass.
This is the final step - it documents the work, it does not change any models.

## Report Structure

Write the HTML file with these sections in order:

### 1. Executive Summary (top of page)

A colored status banner showing:
- **Task**: the original task description (1-2 sentences)
- **Result**: PASS / FAIL with model count
- **Models built/edited**: list with materialization type
- **Total turns used**: from the agent run

### 2. Decision Log

A table showing every major decision the agent made:

| # | Decision | Reasoning | Evidence |
|---|----------|-----------|----------|

Include decisions about:
- Which driving table to use and why
- Which columns to include/exclude and why
- JOIN types chosen and why
- Filters applied (or not applied) and why
- Strategy choices (snapshot strategy, materialization, etc.)

Each row must cite the specific tool output, query result, or skill rule
that informed the decision. No unsupported claims.

### 3. SQL Models Written

For each model created or edited:
- The full SQL (in a collapsible `<details>` block)
- A plain-English explanation of what each CTE does
- The data flow: source tables → CTEs → final SELECT

### 4. Queries Executed

A collapsible section listing every `query_database` call the agent made:
- The SQL query
- The result (first 5 rows)
- Why it was run (what decision it informed)

Group by purpose: "Schema Discovery", "Data Profiling", "Verification".

### 5. Verifier Reports

Two subsections - Structure Verifier and Value Verifier:
- Each CHECK result (PASS/FAIL/SKIP) with the exact output
- For any FAIL that was fixed: what changed and why
- Final state: all checks that passed

### 6. Data Visualizations

Embed inline SVG or HTML/CSS charts (no external dependencies):

**Row Count Waterfall**: horizontal bar chart showing source rows → model
rows, with JOIN multipliers/reductions annotated.

**Column Coverage**: a grid showing YML columns vs model SELECT columns
(green = matched, red = missing, gray = extra).

**NULL Heatmap**: for each model column, show the % NULL as a colored cell
(green = 0%, yellow = partial, red = 100%).

Use inline CSS and simple HTML elements (`<div>` with `background-color`,
`width` as percentage). Do NOT use JavaScript libraries - the report must
render in any browser with zero dependencies.

### 7. Reproducibility

List the exact commands to rebuild from scratch:
```
dbt deps
dbt run --select <model1> <model2>
dbt test
```

## HTML Template Rules

- Single self-contained `.html` file - all CSS inline in `<style>` block
- No external CDN links, no JavaScript libraries
- Use a clean sans-serif font (`font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`)
- Color scheme: `#22c55e` for PASS, `#ef4444` for FAIL, `#f59e0b` for WARN, `#6b7280` for SKIP
- Collapsible sections use `<details><summary>` HTML elements
- Tables use `border-collapse: collapse` with alternating row colors
- Maximum width 900px, centered

## Rules

- Do NOT modify any model files. This skill is READ-ONLY documentation.
- Do NOT run dbt commands. Read existing results only.
- Query the database for chart data (row counts, NULL percentages) using `query_database`.
- The report must be accurate - every number must come from a tool call or query result, not from memory.
