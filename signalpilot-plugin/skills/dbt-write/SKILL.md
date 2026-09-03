---
name: dbt-write
description: "Loaded at Step 2 for the full workflow. Covers column naming, type preservation, JOIN defaults, lookup joins, sibling models, materialization, packages, and filtering rules."
type: skill
---

# dbt Write Skill

## 1. Column Naming and Types

Match required YML aliases exactly because names are case-sensitive. A same-shape sibling has the same layer, grain, and source family and differs only in the requested grouping dimension or metric. Treat YML columns as required unless at least one complete same-shape sibling exists, all such siblings omit the field, and the task does not name it. An explicitly lossless passthrough directly projects upstream columns without aggregation, filtering, deduplication, or a row-changing join. Add non-YML columns only when an output macro with available inputs, a complete same-shape sibling, or an explicitly lossless passthrough establishes them because mapper observations alone do not define output.

**Two-candidate columns**: when a YML description names two source columns for one output ('nickname or full_name', 'the A, or the B if absent'), the output is a COALESCE of both - do not project just one, even if one is never NULL, because the description names two sources. This applies even when one candidate is the model's own column and the other is joined - the description naming both is the sourcing evidence Section 3 requires. Profile both: `SELECT COUNT(*), COUNT(x), COUNT(y) FROM <upstream>`. Order by the NULL profile, not the description's prose order: put the sparser column first - the fallback covers the candidate that is sometimes missing. A two-candidate COALESCE whose first argument has no NULLs while the other candidate does is a defect - the order is wrong. Fix the order; do not delete the COALESCE. When neither candidate has NULLs, keep the description's prose order. When all complete same-shape siblings agree on the argument order for the same COALESCE, their order wins.

**Unit-qualified amounts**: before passing a numeric column through as a monetary amount, check the same table for a companion type or unit column (`value_type`, `*_type`, `unit`, `rate_type`) and `SELECT DISTINCT` it. When the task or YML defines the output as an amount and the qualifier shows proportion rows (percentage), convert those rows with a CASE on the qualifier, e.g. `CASE WHEN value_type = 'percentage' THEN amount / 100.0 * base_amount ELSE amount END`. Identify the base from the table's other amount columns and their YML descriptions. A percentage stored next to dollar amounts is not itself an amount.

**Boolean columns**: preserve a passthrough column's source type - a source `'t'`/`'f'` VARCHAR stays VARCHAR even if its name starts with `is_`/`has_` (do NOT convert it). Emit a real BOOLEAN only for a column the YML types `boolean`, or one you DERIVE fresh with boolean meaning (e.g. a new `is_currently_*` column computed from a comparison); in that case convert a source `'t'`/`'f'` with `(col = 't')`.

Preserve column types from the pre-existing reference table if one exists. If the
reference table has an ID column as VARCHAR, your model must output VARCHAR too -
even if the raw source has it as INTEGER. When no reference exists, preserve the
source type. Type mismatches break downstream contracts even when values are identical.

**Rounding**: do not round or cast an aggregate unless something asks for that precision: the task, a YML decimal type or description, a pre-existing table with the same column, or an upstream model your model reads via ref() whose output is already rounded. Rounding follows lineage, not analogy: when your model reads raw sources directly, use the raw values as they are - another model's rounding of the same source does not transfer unless you read that model's output. Unrequested rounding changes every value in the column. When rounding IS required, aggregate first, then round: `ROUND(SUM(expr), 2)` - NOT `SUM(ROUND(expr, 2))`, which accumulates per-row drift. Round per-row only when the task or YML explicitly does. When the task or YML conflicts with other evidence, the task or YML wins.

**Surrogate / hash key columns**: when a YML column is described as a "surrogate
key" or "concatenation", follow this exact sequence:
1. Query the pre-built table FIRST: `SELECT <key_col> FROM <model> LIMIT 3`.
   If the values look like hex hashes (32 chars, a-f0-9), the formula uses MD5.
2. The standard dbt_utils MD5 pattern is `md5(col1 || '-' || col2)` with a
   `'-'` separator between each field.
3. Test your formula: `SELECT md5(col1 || '-' || col2) FROM <source> LIMIT 1`
   and compare against the pre-built value. If it doesn't match, try without
   separator, or with different column order.
4. Only write the model after your test output matches the reference.

## 2. Sibling Models - Start from the Pattern, Extend Where Needed

**CTE extraction OVERRIDES the sibling pattern.** When extracting CTEs from an existing model into a new model - GATE:
1. Read the parent model's outermost final SELECT. The table in its FROM clause is the spine. Write it down.
2. BLOCKED - do not write the new model until you run: `SELECT COUNT(DISTINCT <key>) FROM <spine>` and `SELECT COUNT(DISTINCT <key>) FROM <aggregation_source>`. If the spine count is higher, there are rows the aggregation does not cover.
3. The new model MUST start FROM the spine table and LEFT JOIN the aggregation CTEs onto it. The new model's row count must equal the spine's row count - if the spine has 16 rows and the aggregation covers only 13, the new model still has 16 rows (3 with NULLs).
4. Do NOT move COALESCE, CAST, or alias transformations from the parent's final SELECT - those belong to the parent (consumer), not the new model (producer).

If a complete sibling model exists in the same directory, READ ITS SQL FIRST.
Replicate its pattern for the parts your model shares with it - same aggregation
expressions, same JOIN types, same filters. Do NOT reason about whether the
sibling's approach is "correct" - the project author designed the data for that
approach.

Specifically, for shared elements:
- Same column name = same SQL expression (if sibling uses `count(*)`, you use `count(*)`). Copy a sibling's rounding or numeric casts only if your model reads that sibling's output via ref(). Date/timestamp parsing (bullet below) always transfers.
- Same JOIN type and JOIN columns for shared source tables
- Same filters and WHERE clauses
- Same date/timestamp casts - if the sibling parses a non-ISO date string with `STRPTIME`, apply the same parse to the analogous column in your model. Never pass a date string through raw or use a generic `CAST(... AS DATE)` on a non-ISO string.
- Same ranking operator, `ORDER BY`, directions, cutoff, and tie-break presence because cutoff membership is part of the local contract. For each element, copy it only when all complete same-shape siblings agree and the verbatim task or YML does not explicitly change that specific element. Use explicit task or YML evidence when siblings disagree because conflicting precedent cannot define one value.

Without a same-shape sibling, use unpartitioned `ORDER BY ... LIMIT N` for an unqualified top-N result that exposes no rank column because it returns at most N rows without inventing rank semantics. Use `ROW_NUMBER` when the task requires per-partition exact-N selection or an exact ordinal rank column because it returns N rows per partition. Use `RANK` or `DENSE_RANK` when the task, YML, or executable project SQL selects that operator because ties before the cutoff change their membership differently. When the task requires positional top-N with boundary ties but names neither operator, use `RANK` because it preserves competition positions. Use `DENSE_RANK` without explicit naming only for a top-N-distinct-rank-level contract because it removes gaps between rank values. Add tie-break columns and directions only when the task, YML, or executable project SQL defines them because an invented ordering changes boundary membership.

Exception: if Section 6 (Grain Consistency) conflicts with a sibling
pattern, Section 6 wins.

Exception: if a sibling is `materialized="incremental"` and computes
period-over-period columns (MoM, WoW, YoY) with LAG/LEAD, do NOT copy
the LAG/LEAD expression. The sibling relies on incremental history that
does not exist on a first build. Use `CAST(NULL AS DOUBLE)` for the
period-over-period column instead - see dbt-workflow "Incremental Models".

**But your model may have elements the sibling does not.** If your model joins
additional source tables, adds lookup enrichment, or has columns the sibling lacks,
you MUST reason about those elements independently:
- Additional source tables with disjoint data need FULL OUTER JOIN (not LEFT JOIN) -
  LEFT JOIN drops all rows from the right table that don't match the left, so disjoint
  data disappears silently. Check with `compare_join_types` to verify.
- Lookup enrichment follows Section 3 rules (use raw source values, join on all
  name variants).
- The sibling pattern covers what it covers. For everything else, apply the rules
  in this skill from first principles.

**Grain-spine rule for multi-source reports.** When a sibling builds a
`reporting_grain` CTE by UNION ALL-ing some intermediates, match which
sources the sibling includes in its UNION ALL and which it LEFT JOINs.
The sibling's author chose those specific sources for a reason - copy
that selection logic, not just the CTE shape.

Specifically: if the sibling UNION ALLs sources A + B but LEFT JOINs C
and D, your model should also only UNION ALL the equivalents of A + B.
The sibling typically unions sources that have different dimensional
coverage (e.g., one synthesizes `cast(null as string) as source_type`)
and LEFT JOINs sources that share the same native grain columns.

Do NOT override this pattern based on test data overlap. Test datasets
are often sparse with non-overlapping dates across sources - that does
not mean UNION ALL is correct. The sibling's structural choice reflects
the production design intent.

Also check the sibling's actual DATA: `SELECT * FROM <sibling_model> LIMIT 5`
If a column has NULL values, your model must also produce NULLs for equivalent rows.

When writing CASE WHEN on categorical columns (order_status, category, tier),
read ALL YML files (`models/**/*.yml`) for vocabulary hints - not just the
model you're building, but every model in the project. Column descriptions
like "contained 'X'" mean use LIKE, not exact match. Descriptions listing
multiple values ("A, B, C") mean use IN(...). Test data may be too sparse
to discover all valid values - the YML descriptions are the source of truth
for categorical patterns.

When fixing a bug in one model, grep ALL models/ for the same CLASS of bug BEFORE editing any file. Run `grep -rn '<pattern>' models/` where `<pattern>` covers the class (e.g., for date bugs: `_date\|_at\|_on`). List every matching file and column. Fix all of them in the same pass.

## 3. Lookup Joins

**OBT/wide join models**: when joining a fact table to a dimension table, list the output columns explicitly (do NOT `SELECT *`) and match a sibling OBT's column selection if one exists. A sibling OBT's column selection can exceed the YML list - when the sibling carries every column of each joined dimension, do the same. Include columns from BOTH tables. If both tables share a column name, the DIMENSION's column keeps the original name (it is the authoritative key); the FACT's foreign-key copy gets the alias. Use the alias the task names; otherwise check a sibling OBT in the same directory.

When enriching data with a lookup table, **use the original source
values for display columns, not the lookup's values.** The lookup adds new columns
(codes, regions, categories) - it does not replace existing ones. Source data often
has encoding variants ("Muenchen" vs "München", "Cote d'Ivoire" vs "Côte d'Ivoire")
that are separate valid rows. If the lookup has multiple name columns (primary +
alternative), join on all of them so every variant finds a match.

**Prefixed column names:** When a YML column name is just a table name prefixed or suffixed onto a column the model's own source already has (e.g. YML `orders_ship_date`, own source column `ship_date`), take the value from the model's own source - not from a joined table that has a similar column. Do not switch to the joined table's value because it has fewer NULLs; a NULL in the own source is real data. Use the joined table's value only when the task, the YML description, a pre-existing table, or a sibling model shows the value comes from there. For a column name present on BOTH tables, the shared-column rule above governs.

**`_id` columns with matching lookup tables:** If a YML column ends in `_id` (e.g., `supplier_id`), the Step 1 scan's LOOKUP JOINS section flags that FK, and the model's own source does not already hold the value the output needs, JOIN the lookup table and output the display-name column. (A raw ID is not the same as a display name - check what the output actually wants.) Check the sibling OBT or pre-existing table to confirm which alias the project uses - it may be `supplier_company`, `supplier_name`, or the original `supplier_id` depending on the project convention.

When the Step 1 scan's LOOKUP JOINS section flags an FK on your source (e.g. `supplier_id → join suppliers → use company`), apply that join - it reflects this model's data, even if a sibling dimension passes its own FK through unresolved. Skip when the scan does not flag a lookup for that column, or when the model's own source already holds the needed value.

**Choosing between multiple label columns:** When a lookup table has more than one
name/label column for the same entity (e.g. `name` vs `display_name` vs
`alternative_name`), do NOT guess which one to use - lookup tables often have both
formal names ("International Business Machines Corporation") and common names
("IBM"), and the project expects one specific convention. Query 3-5 rows from a
pre-existing output table or a complete sibling model that already has this column.
Pick the lookup column whose values match.

**Lookup fan-out is NOT always a bug.** When a lookup table has multiple rows
per join key, the JOIN produces more output rows than input rows. Do NOT
pre-deduplicate the lookup to prevent this. Before deduplicating, query the
duplicate rows: `SELECT * FROM <lookup> WHERE <key> IN (SELECT <key> FROM
<lookup> GROUP BY <key> HAVING COUNT(*) > 1)`. If the duplicate rows have
different values in ANY column, they are distinct data - the fan-out is
correct and MUST be preserved. Update the expected row count in your
technical spec to match the fan-out count. Only deduplicate when duplicate
rows are truly identical across all columns (exact same values in every
field).

"Different values in ANY column" includes name/label variants for the same
entity (e.g., "Brunei" vs "BruneiDarussalam", "Russia" vs "RussianFederation").
These are separate valid rows that carry different information. Do NOT
collapse them - the output should have one row per variant.

## 4. JOIN Defaults

Decide joins in this order; stop at the first step that answers. The driving table (FROM clause) is decided first by the domain skill and the AGGREGATION DRIVING TABLE hint - this ladder decides join types and paths onto it.

1. **Sibling first.** A sibling model over the same staging chain defines the join: copy its join types, keys, and path. Do not override a sibling's join type to preserve a raw table's row count - the sibling's population is the project's definition of the entity.
2. **No sibling: existing producer, then measure.** Before measuring, call `find_column_producers` with the column names you need: when a pre-existing model already projects a column with this exact name, use the relation it reads and do not measure - a lower-coverage upstream chosen by the project is the project's definition of the population, not a coverage defect to route around. When no producer exists, list the candidate join paths and measure each: `SELECT COUNT(*), COUNT(<col>) FROM <driving> LEFT JOIN <candidate>`. The higher `COUNT(<col>)` wins; prefer a path with `COUNT(<col>) = COUNT(*)`. Join entities through staging models, not raw sources - staging carries the project's filters. This step chooses the path; step 3 decides the join type when no sibling or task/YML text fixes it. The measurement decides - rejecting the winner needs task text, a YML description, sibling SQL, or a pre-existing model projecting this column.
3. **Tests are tiebreakers, not authority.** A YML test never chooses a population by itself. When LEFT and INNER remain equally supported, profile the joined column on its own table: `SELECT COUNT(*) - COUNT(<col>) FROM <candidate upstream table>`. Zero stored NULLs means any NULLs in your output would be join-created - INNER satisfies a declared not_null and loses no data. Stored NULLs are data - keep the rows and the LEFT join. A unique test vetoes a measured winner only when upstream grain, source cardinality, or sibling row counts independently confirm the coarser grain - otherwise the test may be aspirational.
4. **Fan-out from a winning path is not a defect.** More rows than the driving table is governed by Section 3's fan-out rule, not by rejecting the path.

After every JOIN, call `compare_join_types` and read its counts as measurements.

**LEFT JOIN + metric columns:** decide by who created the NULL.
- Your own LEFT JOIN created it (e.g. a customer overview where a customer has no
  matching rows): fill it with `COALESCE(col, 0)` - the entity exists and its metric is zero.
- The NULL was already stored in the upstream's rows: keep it - it is data, and a 0
  would change values.

If unsure, run: `SELECT COUNT(*), COUNT(col), COUNT(CASE WHEN col = 0 THEN 1 END) FROM <upstream>` -
NULLs present and zeros absent means the upstream writes "no data" as NULL.
Exception: when extracting CTEs from a parent model (Section 2 gate), the parent
keeps the COALESCE - do not add one in the extracted model.

**LEFT JOIN + COUNT:** When counting child rows after a LEFT JOIN, use
`COUNT(child.primary_key)` not `COUNT(*)`. COUNT of a nullable FK column
returns 0 when the LEFT JOIN produces NULLs (no matching children),
without needing COALESCE.

If the model computes metrics FROM a fact table (SUM of transactions, COUNT
of orders), the domain skill's driving table rule applies instead - the
fact aggregation drives the FROM clause, not the dimension.

## 5. Do NOT Add Filters Unless Explicitly Required

Treat `not_null` tests as output assertions because they do not authorize filtering, `COALESCE`, or source substitution. Join choice is decided by Section 4.

Do NOT add WHERE or HAVING clauses unless the task description or YML explicitly
says to exclude rows. When a filter IS required, apply it at the NARROWEST
single point - the first model where the filtered entity is the driving
table. Do NOT add the same filter to other models that JOIN the entity
as a lookup - those models inherit the filter through the ref() chain.
If the entity is the driving table in one intermediate and a lookup JOIN
in others, filter ONLY the driving-table model.

Exceptions that REQUIRE filters:
- Boolean flag filters (Section 14)
- Domain skill status filters - if the loaded domain skill says to filter
  a status column (e.g., excluding returns via WHERE), that filter is
  MANDATORY and overrides this section. Use WHERE, not CASE WHEN.

Common mistakes:
- Filtering by a category/type/status inferred from the model name (e.g. adding
  `WHERE department = 'Engineering'` because the model is called `eng_headcount` -
  unless the YML description explicitly says to restrict, include all values)
- Filtering by a column value that matches a word in the task description.
  Task descriptions use domain language, not SQL predicates. "actors" does
  not mean WHERE role = 'ACTOR'. The source table defines the population.
  Include all rows unless the task or YML description explicitly requires a row filter.
  If unsure, check complete sibling models in the same project. If they
  don't filter that table, neither should you.
- Filtering NULLs from UNIONs when only some columns are NULL
- Adding HAVING to exclude groups with NULL values

A row with some NULL columns is real data - keep it.

**Derived metrics do not redefine their inputs.** A column computed from other columns (a difference, ratio, or percentage) takes those columns as already defined by their own descriptions and rules. Do not change an input's filters or population to make the derived value look plausible (non-negative, under 100%). A negative difference or a percentage over 100 is information about the data, not evidence that an input is wrong.

## 6. Grain Consistency

Before writing any aggregate, run:
`SELECT COUNT(*), COUNT(DISTINCT <key>) FROM <source_table>`.
If they differ, the source grain is finer than the key.

All metrics in a report MUST operate at the same grain. If a SUM
uses every row, every COUNT must use COUNT(*) - not COUNT(DISTINCT).

YML column descriptions explain what a column represents, not how
to aggregate it. The source table's grain determines the correct
aggregation.

If this rule conflicts with a sibling pattern, the grain check
wins - if a sibling uses COUNT(DISTINCT) but the grain check shows
the source is finer, MUST use COUNT(*). The grain check is
measurable; sibling patterns are inherited assumptions.

## 7. Build Order

Build in dependency order: sources → staging → core → marts.
Use `dbt_project_map focus="work_order"` for the exact sequence.

## 8. CASE WHEN Boundary Validation

Before writing a CASE WHEN with numeric thresholds, query `SELECT MIN(col), MAX(col)` on the input column. If values fall outside your threshold ranges, the ELSE clause catches anomalies that don't belong in any valid category.

Example: a score column has accepted categories low/medium/high for ranges 0-33/34-66/67-100. If `SELECT MAX(score)` returns 150, then scores above 100 are anomalies - ELSE should be NULL, not "high". Forcing anomalies into the nearest bucket corrupts the data.

If the YML defines `accepted_values`, any row that doesn't map to a listed value MUST be NULL.

For event-type columns that classify actions, prefer `LIKE '%keyword%'`
over exact equality when sibling models or YML descriptions indicate
compound values exist. Exact equality silently misses compound types.

Do NOT round the input column before the CASE WHEN comparison. Rounding shifts values across threshold boundaries. Compute the CASE from the full-precision value. Round in the final SELECT only if the Section 1 rounding rule asks for it.

## 9. Use Ref Models Instead of Recomputing

If the YML lists a ref to a model that computes a metric, use that model's output. Do NOT recompute the same metric from raw sources - the ref model exists because the project author designed it for that calculation. This overrides sibling patterns - even if a sibling recomputes the metric, use the dedicated ref model.

Recomputing introduces precision differences from rounding order and diverges from the project's intended data flow.

This applies to non-numeric values too (names, concatenations, flags, keys). An intermediate carries the project's row filters, so deriving the same value from a different relation changes the population, not just precision. When an intermediate already holds the value, source it from that intermediate - deriving the same value from a different relation is a defect. Call `find_column_producers` with your output column names to see which existing models already produce them.

Exception: when a model aggregates child events (driving FROM the child, or
FROM the parent LEFT JOIN child), compute every `first_*_at`, `last_*_at`, and
count metric directly from child rows using MIN/MAX/COUNT. A parent column like
`first_*_created_at` captures the source system's semantics, not your predicate -
do NOT use it. The child aggregation IS the definition; deriving from it is not
"recomputing".

## 10. Materialization

- Default to `materialized='table'` for new models.
- Do NOT add `incremental` materialization or `is_incremental()` to a plain table/view model. BUT if a model IS materialized `incremental` (its config requires it, or the task asks to build/maintain one), the `{% if is_incremental() %}` guard is REQUIRED - it filters to new rows on later runs. Omitting it re-inserts all rows every run, doubling the data and breaking downstream counts.

## 11. Removing Jinja Feature Flags

When a task says to remove a dbt variable that gates SQL via `{% if var(...) %}`:
1. Delete the Jinja tags (`{% if %}`, `{% endif %}`)
2. Delete the CTE defined inside the block
3. Delete the JOIN to that CTE in the final query
4. Delete the SELECT column that came from that CTE
All four must go. "Remove a variable" means DELETE the feature's code,
not unwrap it - leaving SQL content without its gate makes the feature
permanent instead of removed.

## 12. Packages

All dbt packages are pre-bundled in `dbt_packages/`. Do NOT pip install or git clone -
the sandbox has no internet access and external installs will fail.
If models call macros from a package NOT in `dbt_packages/`, write equivalent raw SQL
instead. Run `dbt deps` only if `dbt_project_validate` reports `packages_missing`.

When `dbt_packages/` contains cross-platform packages (Fivetran, dbt-utils),
use dbt macros for date arithmetic (`{{ dbt.datediff(...) }}`) instead of
database-native functions. This ensures compatibility across adapters.

## 13. Percentage Columns

If a YML column name contains `pct`, `percent`, `percentage`, or `rate`, the output MUST be on a percent scale (multiply the ratio by 100), not a 0-1 ratio. A column called `return_pct` with value 0.65 is wrong - it MUST be 65.0. Percent values may exceed 100.

## 14. Boolean Flag Columns

When counting events by date (e.g., conversions by converted_date, closings by closed_date), check for a boolean flag column (is_converted, is_deleted, is_closed, is_won). A non-null date does NOT confirm the event occurred - CRM and SaaS systems populate date fields speculatively. Filter on the boolean flag, not the date column.


