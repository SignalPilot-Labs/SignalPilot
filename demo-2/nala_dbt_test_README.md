# nala_dbt_test — broken pipeline for SignalPilot demos

A full copy of the `nala_dbt` project with **three upstream intermediate models
deliberately broken**, materialized into an isolated **`nala_test_*`** schema set.
The canonical `analytics_*` marts are untouched and serve as ground truth.

Use it to demo SignalPilot getting tripped up: every headline number is silently
inflated by a one-line change to an intermediate that cascades downstream. See
`PROMPTS.md` for the three asks and the answer key.

## The three breaks (all live in this project)

| broken model | what changed | breaks |
|---|---|---|
| `models/intermediate/int_transfers_enriched.sql` | LEFT JOINs `transfer_status_history` (~3.9 rows/transfer) without deduping → fee/revenue fan-out | `fct_revenue_daily`, `fct_transfers`, `dim_customers`, `dim_corridors`, `int_revenue_per_transfer`, `int_customer_lifetime` |
| `models/intermediate/int_customer_risk.sql` | keeps each customer's *worst-ever* risk score instead of the latest | `dim_customer_risk` (high-risk % 8.46% → 11.16%) |
| `models/intermediate/int_marketing_spend_unioned.sql` | adds a "Performance Max" channel reading the same Google feed → double counts spend | `fct_marketing_spend_daily` (CAC ~doubles) |

One intermediate change (`int_transfers_enriched`) alone breaks **6 downstream
models** — the "change an intermediate, break everything below it" scenario.

## Current state: the warehouse IS broken (in place)

We made the live warehouse the broken one — the broken build now occupies the
canonical `analytics_*` schemas, and there is **no correct copy to fall back to**.
This project (`nala_dbt_test`) and the clean project (`nala_dbt`) BOTH target the
`analytics` schema now, so whichever you run last wins. `raw_*` (source data) is
untouched.

## Wire it up to SignalPilot

1. **Connection** (you already have this), no scoping needed:
   `postgresql://nala:nala_dev_only@nala-warehouse-pg:5432/nala_warehouse`
   (docker→docker) or `...@host.docker.internal:5602/...`.
2. **Run the prompts** in `PROMPTS.md` and compare against the answer key. The
   agent reads `analytics_marts` (now broken) — there's no clean layer to pick.
3. **(If the agent writes models)** point its workspace at this directory so it
   reads the broken intermediates and can add new models.

## Toggle broken <-> correct (both target analytics_*)

```bash
# MAKE IT BROKEN (current state) — rebuild the broken marts into analytics_*
cd demo-2/nala_dbt_test && ../warehouse/.venv/Scripts/dbt.exe run --profiles-dir .

# RESTORE CORRECT — rebuild the clean marts into analytics_*
cd demo-2/nala_dbt && ../warehouse/.venv/Scripts/dbt.exe run --profiles-dir .

# see the breadcrumbs (fct_transfers + dim_customer_risk uniqueness tests fail)
cd demo-2/nala_dbt_test && ../warehouse/.venv/Scripts/dbt.exe test --profiles-dir .
```

Diff a broken model in this project against the same file in `../nala_dbt` to show
the exact line that cascades downstream.
