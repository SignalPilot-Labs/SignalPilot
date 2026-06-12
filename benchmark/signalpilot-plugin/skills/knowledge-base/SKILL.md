---
name: knowledge-base
description: "Write a technical spec after research. Distills exploration into structured decisions. On retries, read the existing spec instead of re-researching."
---

# Knowledge Base - Technical Spec

## 1. Check for Existing Spec

Check if `<project_dir>/technical_spec.md` exists.

- **If it exists**: read it. Skip macro discovery and Step 5 research.
  Go directly to writing SQL from the spec. Do NOT re-research - re-researching
  contradicts persisted decisions and wastes turns.
- **If it does not exist**: write one using the rules in Sections 2-5.

## 2. Write the Spec

After Step 5 research, MUST write `<project_dir>/technical_spec.md`.

The spec distills exploration into decisions. NOT a copy of research output.
NOT SQL. NOT domain knowledge. The spec answers: "what will I build, from
what sources, with what joins and filters, and why?"

STOP writing the spec when every model has all seven fields from Section 3
and every decision in Section 4 has WHAT + WHY + EVIDENCE.

## 3. Per-Model Plan (mandatory fields)

For EACH model, MUST include ALL seven fields:

1. **Source**: `ref('model_name')` or raw table name. If an intermediate
   model already computes a value you need, MUST write `ref('that_model')`.
   Do NOT recompute from raw tables - recomputing introduces precision
   drift from rounding order differences.
2. **Driving table**: which table in the FROM clause. State the row count
   from the Step 1 scan or a `query_database` COUNT.
3. **Joins**: each join with type (LEFT/INNER/FULL OUTER) and exact keys.
   "Join some dimension table" is not a plan. `LEFT JOIN dim_customers
   ON fct.customer_id = dim.customer_id` is a plan.
4. **Key expressions**: computed columns. If a sibling or upstream model
   defines this expression, copy it exactly and name the source model
   and column. Untraced expression reuse causes silent divergence.
5. **Filters**: WHERE/HAVING clauses with justification (domain skill rule,
   YML description, or `query_database` discovery). If no filter, write "none."
   Unjustified filters silently drop rows and break row counts.
6. **Expected grain**: what one row represents (one per customer, one per
   line item, one per day-product pair).
7. **Expected rows**: from `query_database` cardinalities or entity
   counts. Do NOT guess.

Example:

```
## Model: fct_revenue
- Source: ref('int_order_items') - already computes item_total, do NOT recompute
- Driving table: int_order_items (600K rows)
- Joins: dim_customers ON customer_id = customer_id (LEFT JOIN)
- Key expressions:
 - total_revenue = SUM(item_total)  [from int_order_items.item_total]
 - order_count = COUNT(*)
- Filters: WHERE status != 'returned' (domain-ecommerce: exclude returns from revenue)
- Expected grain: one row per customer
- Expected rows: ~75K (query: 75K distinct customers excluding returns)
```

## 4. Decisions Section

MUST include a Decisions section after all model plans. Each decision states
WHAT you chose, WHY, and what EVIDENCE supports it. These are the choices
a reviewer needs to verify your work.

One decision per line. Example:

```
## Decisions
- int_order_items computes item_total -> fct_revenue refs it (avoids precision drift from recomputation)
- Returns excluded in fct_revenue, not in int_order_items (intermediate preserves all rows for other consumers)
- LEFT JOIN dim_customers (query: 75K customers vs 73K in dim - some deleted, keep all)
- COUNT(*) not COUNT(DISTINCT order_id) (grain check: COUNT(*) != COUNT(DISTINCT) on int_order_items)
```

## 5. Build Order

MUST list models in dependency order at the top of the spec. For each model,
note its layer (staging/intermediate/mart) and dependencies. Build failures
from wrong ordering waste turns on debugging instead of building.

```
## Build Order
1. stg_payments (staging - no dependencies)
2. int_order_items (intermediate - depends on stg_payments)
3. fct_revenue (mart - depends on int_order_items)
```

## 6. Updating After Verification

When a verifier reports FAIL, update `technical_spec.md` BEFORE changing SQL.
The spec is the source of truth - SQL follows the spec, not the other way
around. Changing SQL without updating the spec causes the spec to drift,
making future retries unreliable.

1. Find the model section in the spec.
2. Edit the field that caused the failure.
3. Add a decision line explaining the change.
4. Rewrite the SQL from the updated spec.

## 7. What Does NOT Go in the Spec

- Full SQL - that belongs in `.sql` files (written after the spec)
- Raw `query_database` output - that is exploration data
- Domain knowledge - that is in domain skills
- Column descriptions from YML - read YML directly when writing SQL
- dbt-write rules (JOIN defaults, filter rules, grain checks) - those
  rules live in the dbt-write skill. The spec records your DECISIONS
  about which rules apply, not the rules themselves.
