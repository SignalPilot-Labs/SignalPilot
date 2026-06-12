# Project Instructions

## Loaded skills and MCP tools override "be efficient"
When a skill or MCP server is loaded, its instructions are the workflow. Follow every step - do not skip, shortcut, or substitute steps with ad-hoc alternatives to save time. "Output efficiency" means concise *text*, not skipping prescribed tool calls or verification steps. If a skill says to use a specific tool or subagent, use it - do not replace it with a script, CLI command, or manual check.

## Use the tools you have
If an MCP tool or subagent exists for an action (querying, validation, verification), use it. Do not write throwaway scripts or shell commands to do what a provided tool already does. The tools exist because they enforce governance, logging, or correctness guarantees that ad-hoc alternatives bypass.

## Derive SQL from data, not from descriptions
Task descriptions explain what the data represents. Do NOT translate
description words into SQL predicates, aggregation levels, or deduplication
logic. Query source tables first. Let the data's structure, the YML column
contract, and sibling model patterns determine your SQL. When a description
states explicit transformation rules, implement those rules against the
actual source data.

## Trust the YML contract for model names, columns, and materializations
The YML contract defines exact model names, exact column names, and exact materializations. Use the YML `name:` field as the SQL filename - `daily_agg_nps_reviews` in YML means create `daily_agg_nps_reviews.sql`, not `daily_agg_reviews.sql`. Use the YML `materialized:` as-is - do not change `table` to `incremental`. Do NOT add columns beyond what the YML specifies. Do NOT create models that are not listed in the YML - every `.sql` file you create must have a corresponding `name:` entry. When sibling models show a YML column is a denormalized value rather than a raw FK, follow the sibling pattern.

## Prefer minimal edits
For models the scan marks as "existing complete" - EDIT minimally, do not delete and recreate. Existing files contain JOINs, aliases, CTEs, and filters that rewriting drops. For bug fixes: change only the broken expression. Stubs and missing models should be written from scratch as normal.

Always load the dbt-workflow skill before any other action - it owns the workflow steps and stop condition for this project.
