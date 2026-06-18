# NALA dashboard + the "break an intermediate" demo

`nala_dashboard.ipynb` is a 3-panel analyst dashboard over the NALA warehouse
marts (Postgres on host port 5602):

1. **Revenue & volume** (Finance) — `fct_revenue_daily`
2. **Compliance risk exposure** (MLRO) — `dim_customer_risk`, `fct_kyc_checks`
3. **Marketing efficiency / CAC** (Growth) — `fct_marketing_spend_daily`, `fct_acquisition_funnel`

Run it:
```bash
cd demo-2/dashboard
../warehouse/.venv/Scripts/python.exe -m jupyter nbconvert --to notebook \
  --execute --inplace nala_dashboard.ipynb --ExecutePreprocessor.timeout=180
```
(or open it in Jupyter / VS Code). The final cell documents the dbt lineage
behind each KPI.

---

## Demo: break one intermediate, watch the dashboard lie

Every KPI in panel 1 traces to a single intermediate:

```
fct_revenue_daily  <-  int_revenue_per_transfer  <-  int_transfers_enriched
fct_transfers      <------------------------------------^
dim_customers, dim_corridors, int_customer_lifetime  <---^
```

`int_transfers_enriched` carefully **pre-aggregates `transfer_fees` to one row
per transfer** before joining. Break that grain and *all six* downstream models
inflate — but `fct_revenue_daily`'s own grain test (date × corridor × currency)
still passes, so **the dashboard shows a wrong number with no error**.

### The break (one change, many broken downstreams)

A developer "wires in" the `transfer_status_history` table to surface a transfer's
latest workflow status, but forgets it's one row *per status transition*
(~3.9 rows/transfer). The added `LEFT JOIN` fans out every transfer ~3.9×.

The ready-made broken model is `../llm-trap/break/int_transfers_enriched.sql`.
Apply it into an isolated `trap_*` schema (canonical `analytics_*` is left intact):

```bash
cd demo-2/llm-trap
BREAK=revenue bash build_broken.sh
# prints:  BROKEN trap_marts ~£5.36M   vs   TRUTH analytics_marts ~£1.36M  (GBP, Q1)
```

Point the notebook's connection schema at `trap_marts` instead of `analytics_marts`
and re-run panel 1: **Q1 revenue jumps ~3.9× and transfer counts balloon** — all
from one upstream line. (`fct_transfers`' `unique(transfer_id)` test *does* fail —
that's the breadcrumb a careful analyst/agent follows back upstream. The revenue
table's tests don't, which is why the number slips through.)

### Two more break recipes (`build_broken.sh BREAK=...`)

- **`risk`** — `int_customer_risk` keeps each customer's *worst-ever* score
  instead of the latest → high-risk share reads **11.2%** vs the true **8.5%**.
  No test fails.
- **`cac`** — `int_marketing_spend_unioned` adds a "Performance Max" channel that
  reads the same Google feed → spend double-counts → blended CAC ~doubles
  (**£93.1M** vs **£57.1M** total spend). No test fails.

### Restore

```bash
docker exec nala-warehouse-pg psql -U nala -d nala_warehouse -c \
  "drop schema if exists trap_marts cascade; drop schema if exists trap_intermediate cascade; drop schema if exists trap_staging cascade;"
```
The canonical `analytics_*` marts were never touched, so the dashboard is correct
again the moment you point it back at `analytics_marts`.

---

See `../llm-trap/README.md` for handing these same breaks to a Claude Code agent
and grading whether it catches them.
