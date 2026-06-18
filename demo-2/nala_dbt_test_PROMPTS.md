# NALA test prompts + answer key

Paste these into SignalPilot (connected to the warehouse — no schema scoping
needed; the live `analytics_*` marts ARE the broken build now, with no correct
copy to fall back to). They read like normal Slack asks. The data behind them is
silently broken by three upstream intermediate changes, so an agent that trusts
the marts (or re-derives naively) returns badly inflated numbers. All "Q1 this
year" = 1 Jan 2026 – 31 Mar 2026.

---

### Prompt 1 — revenue (trusts a broken downstream mart)

> hey! pulling together the board deck — how much transfer revenue did we do from our UK (GBP) customers in Q1 this year? need a number i can stand behind 🙏

- ✅ correct: **£1,362,828**
- ❌ broken `analytics_marts` answer: **~£5,355,009** (3.9×)
- root cause: `int_transfers_enriched` now LEFT JOINs `transfer_status_history`
  (~3.9 rows/transfer) without deduping → fees/revenue fan out. Feeds
  `fct_revenue_daily`, whose own grain test still passes, so it slips through.

### Prompt 2 — write a new model (KE)

> hey! for the risk review can you build a model of our UK→Kenya transfers in Q1 this year that shows the status history each one went through? and give me the total GBP value we completed while you're in there 🙏

- ✅ correct: **£6,615,871** (20k-ish completed transfers)
- ❌ broken answer: **tens of millions** (e.g. ~£26M if it re-derives by joining
  `transfer_status_history`; up to ~£106M if it reads the already-fanned
  `analytics_marts.fct_transfers`)
- root cause: "show the status history" tempts a 1-to-many join; the vetted
  `int_transfers_enriched` already aggregates it. Summing value across the
  fan-out inflates the total ~4×+.

### Prompt 3 — write a new model (NG)

> we need a new model for our UK→Nigeria transfers in Q1 this year, broken out by fee type — and what was the total GBP we sent to NG in that window? ta!

- ✅ correct: **£7,344,688**
- ❌ broken answer: **~£15.8M+** (transfer_fees ≈ 2.15 rows/transfer), up to
  ~£115M off the already-fanned `fct_transfers`
- root cause: "broken out by fee type" tempts a join to `transfer_fees`
  (multiple rows per transfer); summing send volume post-join double/triple
  counts.

---

## Bonus (the other two breaks are also live)

If you also ask risk or marketing questions, those are broken too:

- **high-risk %** → broken **11.16%** vs true **8.46%**
  (`int_customer_risk` keeps each customer's *worst-ever* score, not the latest).
- **total marketing spend** → broken **£367.9M** vs true **£227.0M**
  (`int_marketing_spend_unioned` added a "Performance Max" channel that reads the
  same Google feed → spend double-counted).

## What "passing" looks like

A good agent **traces lineage / runs `dbt test`** and either reports the correct
number or flags the mart as untrustworthy. `fct_transfers`' `unique(transfer_id)`
test and `dim_customer_risk`'s uniqueness test both FAIL — that's
the breadcrumb. `fct_revenue_daily` and `fct_marketing_spend_daily` pass their own
tests, which is exactly why those numbers slip through unnoticed.
