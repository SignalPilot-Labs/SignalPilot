---
name: dbt-write
description: "Load at Step 4 when writing SQL models. Covers column naming, type preservation, JOIN defaults, lookup joins, sibling models, materialization, packages, and filtering rules."
type: skill
---

# dbt Write Skill

## 1. Column Naming and Types

Your SQL aliases MUST match YML column names EXACTLY (case-sensitive).
- YML says `total_revenue` → write `AS total_revenue`, NOT `AS revenue_total`
- YML says `QoQ` → write `AS QoQ`, NOT `AS qoq` (case matters)
- Every YML column MUST appear in your SELECT. Do NOT invent extra columns.

Preserve column types from the pre-existing reference table if one exists. If the
reference table has an ID column as VARCHAR, your model must output VARCHAR too —
even if the raw source has it as INTEGER. When no reference exists, preserve the
source type. Type mismatches break evaluation even when values are identical.

## 2. Sibling Models — Start from the Pattern, Extend Where Needed

If a complete sibling model exists in the same directory, READ ITS SQL FIRST.
Replicate its pattern for the parts your model shares with it — same aggregation
expressions, same JOIN types, same filters. Do NOT reason about whether the
sibling's approach is "correct" — the project author designed the data for that
approach.

Specifically, for shared elements:
- Same column name = same SQL expression (if sibling uses `count(*)`, you use `count(*)`)
- Same JOIN type and JOIN columns for shared source tables
- Same filters and WHERE clauses

**But your model may have elements the sibling does not.** If your model joins
additional source tables, adds lookup enrichment, or has columns the sibling lacks,
you MUST reason about those elements independently:
- Additional source tables with disjoint data need FULL OUTER JOIN (not LEFT JOIN) —
  LEFT JOIN drops all rows from the right table that don't match the left, so disjoint
  data disappears silently. Check with `compare_join_types` to verify.
- Lookup enrichment follows Section 3 rules (use raw source values, join on all
  name variants).
- The sibling pattern covers what it covers. For everything else, apply the rules
  in this skill from first principles.

Also check the sibling's actual DATA: `SELECT * FROM <sibling_model> LIMIT 5`
If a column has NULL values, your model must also produce NULLs for equivalent rows.

## 3. Lookup Joins

When enriching data with a lookup table, **IMPORTANT: use the original source
values for display columns, not the lookup's values.** The lookup adds new columns
(codes, regions, categories) — it does not replace existing ones. Source data often
has encoding variants ("Muenchen" vs "München", "Cote d'Ivoire" vs "Côte d'Ivoire")
that are separate valid rows. If the lookup has multiple name columns (primary +
alternative), join on all of them so every variant finds a match.

**Choosing between multiple label columns:** When a lookup table has more than one
name/label column for the same entity (e.g. `name` vs `display_name` vs
`alternative_name`), do NOT guess which one to use — lookup tables often have both
formal names ("International Business Machines Corporation") and common names
("IBM"), and the project expects one specific convention. Query 3-5 rows from a
pre-existing output table or a complete sibling model that already has this column.
Pick the lookup column whose values match.

## 4. JOIN Defaults

When no sibling model exists to copy from, default to LEFT JOIN.
After every JOIN, call `compare_join_types` to verify no rows are silently dropped.

**LEFT JOIN + metric columns:** When LEFT JOINing an aggregation/stats table onto a
dimension table, wrap ALL metric columns (counts, sums, averages) in `COALESCE(col, 0)`.
A customer with zero orders had zero orders — not unknown orders. NULL means "no data";
0 means "none." Reporting models use 0. Check sibling models for confirmation.

## 5. Do NOT Add Filters Unless Explicitly Required

Do NOT add WHERE or HAVING clauses unless the task description or YML explicitly
says to exclude rows. Common mistakes:
- Filtering by a category/type/status inferred from the model name (e.g. adding
  `WHERE department = 'Engineering'` because the model is called `eng_headcount` —
  unless the YML description explicitly says to restrict, include all values)
- Filtering NULLs from UNIONs when only some columns are NULL
- Adding HAVING to exclude groups with NULL values

A row with some NULL columns is real data — keep it.

## 6. Build Order

Build in dependency order: sources → staging → core → marts.
Use `dbt_project_map focus="work_order"` for the exact sequence.

## 7. Materialization

- Always use `materialized='table'` for new models.
- Never use `incremental` or `is_incremental()` in new SQL — that's for existing models only.

## 8. Packages

All dbt packages are pre-bundled in `dbt_packages/`. Do NOT pip install or git clone —
the sandbox has no internet access and external installs will fail.
If models call macros from a package NOT in `dbt_packages/`, write equivalent raw SQL
instead. Run `dbt deps` only if `dbt_project_validate` reports `packages_missing`.
