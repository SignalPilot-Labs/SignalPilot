---
name: dbt-testing
description: "Load when task involves adding, writing, or fixing dbt unit tests. Covers unit_tests YAML format, given/expect blocks, edge-case coverage, and the difference between unit tests and schema tests."
disable-model-invocation: false
allowed-tools: Bash(dbt *)
---

# dbt Testing Skill - Unit Tests

## 1. Unit Tests vs Schema Tests

Schema tests (`unique`, `not_null`, `accepted_range`) check constraints on output data.
Unit tests check computation logic with mock inputs and expected outputs.

When a task says "add tests," determine which type:
- "logic", "computation", "calculation", "edge cases", "verify behavior" = **unit tests**
- "constraints", "uniqueness", "nullability", "referential integrity" = **schema tests**

If the model already has schema tests and the task says "add tests," it means unit tests.

Do NOT add schema tests when the task asks to verify logic - schema tests cannot detect formula bugs like reversed signs, wrong denominators, or incorrect window sizes.

## 2. YAML Structure

Unit tests live in a `.yml` file next to the model. Top-level key is `unit_tests:`, NOT inside `models:`.

```yaml
unit_tests:
 - name: test_order_total_basic
    model: my_orders
    given:
 - input: ref('stg_orders')
        rows:
 - {order_id: 1, quantity: 3, unit_price: 10.00}
 - {order_id: 2, quantity: 1, unit_price: 25.00}
 - input: ref('stg_discounts')
        rows:
 - {order_id: 1, discount_amount: 5.00}
    expect:
      rows:
 - {order_id: 1, total: 25.00}
 - {order_id: 2, total: 25.00}
```

Rules:
- `given` lists every `ref()` the model uses. Each entry has `input` and `rows`.
- `expect.rows` uses the model's output column names from its SELECT.
- Column names in `given` rows must match the input model's column names exactly.
- Column names in `expect` rows must match the tested model's output column names exactly.
- You may omit columns from `expect` rows - only listed columns are checked.

## 3. Read the Model SQL First

Before writing any unit test, read the model's SQL file. Identify:
1. All `ref()` calls - these are the inputs for `given` blocks.
2. All output column names - these are the keys for `expect` rows.
3. The transformation logic - this determines what edge cases to test.

Do NOT guess input or output column names. Read the SQL.

## 4. Do NOT Rewrite Model SQL

When the task says "add tests," add tests. Do NOT rewrite, refactor, or rename columns in the model SQL. Unit tests verify existing logic - they do not change it.

If a unit test reveals a bug in the model (e.g., integer division truncation), document the finding. Do NOT delete the failing test to make the suite green. A failing test that catches a real bug is correct.

## 5. Edge-Case Coverage

Write tests that isolate specific behaviors. Each test should catch exactly one class of bug.

Required edge cases for numeric/aggregation models:
- **All-positive input** - baseline correctness
- **All-negative input** - catches reversed sign bugs
- **Mixed positive/negative** - catches wrong numerator/denominator
- **Single category only** - catches division-by-zero or missing COALESCE
- **NULL inputs** - catches missing NULL handling
- **Boundary values** - zero, exactly-at-threshold, min/max

For rolling window models, add:
- Rows inside AND outside the window boundary to verify exclusion. For an N-day window, place one fixture row exactly N-1 days before the target (must be INCLUDED) and one exactly N+1 days before (must be EXCLUDED). A gap wider than N+1 leaves a dead zone where an off-by-one window size produces identical output and the bug passes undetected.

For ratio/percentage models, add:
- Zero denominator - catches division-by-zero
- Denominator equals numerator - result should be 100% (or 1.0)

Name tests descriptively: `test_<model>_<behavior>` (e.g., `test_daily_nps_all_negative_reviews`).

## 6. Running Unit Tests

```bash
# Run unit tests for a specific model
dbt test --select <model_name>,test_type:unit

# Run all unit tests in the project
dbt test --select test_type:unit
```

After writing unit tests, run them. If tests fail against the current model, that means the tests caught a bug. Report the finding. Do NOT delete the test.

## 7. Placement

Put unit test YAML in the same directory as the model's existing `.yml` file. If the model's schema tests are in `models/marts/agg.yml`, add unit tests to `models/marts/agg.yml` (or a new file like `models/marts/unit_tests.yml`). Either location works - dbt finds unit tests by scanning all `.yml` files.

## Rules

- NEVER conflate unit tests with schema tests - they serve different purposes and use different YAML structures.
- NEVER place `unit_tests:` inside a `models:` block - it is a top-level key.
- NEVER rewrite model SQL when the task only asks to add tests.
- NEVER delete a failing unit test that catches a real bug.
- ALWAYS read the model SQL before writing tests - column names must be exact.
