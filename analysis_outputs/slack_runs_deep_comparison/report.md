# Deep Comparison: Slack 14:02 vs Slack 15:45 Transfer-Revenue Runs

Generated: `2026-06-22T16:01:14`

## Bottom Line

The 15:45 run is the stronger execution path because it queried the materialized mart directly. But it did **not** merely produce the same answer faster. It changed the business definition being answered.

- **14:02 raw fallback:** `Q1 2026 GBP customer transfer revenue: ~£2,088 (GBP equiv.) from 220 completed transfers`

- **15:45 mart backed:** `Q1 2026 completed GBP transfer revenue: £2,530.33 across 190 transfers (91.6% FX margin, 7.7% fees)`

- Revenue moved from **£2,087.68** to **£2,530.33**, a **£442.65 / 21.2% increase**.

- Completed transfers moved from **220** to **190**, a **30 transfer / 13.6% decrease**.


That combination is the clue: the mart-backed query is not just a cleaner implementation; it selected a different population and revenue definition. The 14:02 run treated “GBP customers” as raw customers with `customers.currency = 'GBP'`, then included mixed send currencies and converted revenue into GBP. The 15:45 run treated “UK/GBP” as transfers where `send_currency = 'GBP'` inside `analytics_marts.fct_transfers`.

## Run Scorecard

| Dimension | 14:02 raw fallback | 15:45 mart backed | Interpretation |
|---|---:|---:|---|
| Runtime | 932.1s | 773.9s | 15:45 was 17.0% faster |
| Cost | $2.597882 | $2.169192 | 15:45 was 16.5% cheaper |
| Events | 916 | 770 | 15:45 emitted 146 fewer events |
| Tool calls | 69 | 41 | 15:45 used 28 fewer calls |
| Read calls | 34 | 18 | 15:45 avoided 16 reads |
| Project/dbt reads | 32 | 16 | 15:45 read half as many dbt files |
| Notebook edits | 14 | 7 | fewer rewrite loops in 15:45 |
| Notebook runs | 13 | 6 | fewer execution/debug loops in 15:45 |
| Final confidence | 0.82 | 0.9 | model-authored, but directionally higher for mart-backed run |
| Query path | raw tables + manual dbt replay | materialized mart | 15:45 is operationally better |

## Where Time Went

### 14:02 raw fallback

| Phase | Idx range | Events | Duration | What happened |
|---|---:|---:|---:|---|
| Initial setup | 0-188 | 189 | 204.9s | tools, missing skill files, dbt understanding |
| Notebook setup / connection discovery | 189-315 | 127 | 107.0s | setup cells, duplicate sp import repair, connection discovery |
| Initial mart attempt | 316-342 | 27 | 37.5s | created fct_transfers queries, run failed because relation did not exist |
| Schema/materialization discovery | 343-486 | 144 | 112.6s | searched schemas/tables, concluded only raw schemas existed |
| Raw-table fallback execution | 487-637 | 151 | 185.6s | rewrote SQL against raw_core_transfers and executed successfully |
| FX/charts/repair | 638-755 | 118 | 157.6s | added FX conversion and charts; fixed missing EUR rate and corridor send_currency |
| Verification/finalization | 756-915 | 160 | 125.8s | checked stale errors, updated summary, final JSON |

### 15:45 mart backed

| Phase | Idx range | Events | Duration | What happened |
|---|---:|---:|---:|---|
| Initial setup | 0-24 | 25 | 26.2s | tools and prompt intake |
| dbt scouting / model selection | 25-430 | 406 | 435.0s | Explore subagent plus dbt file reads before notebook edit |
| Notebook rebuild after edit failure | 431-502 | 72 | 87.5s | stale cell id caused partial edit; rebuilt notebook cells |
| Execution repair loop | 503-600 | 98 | 68.7s | fixed sp.init, connection name, and schema prefix |
| Mart execution and summary | 601-652 | 52 | 65.6s | successful analytics_marts.fct_transfers run and summary update |
| Final JSON | 653-769 | 117 | 73.9s | final answer generation |

The mart-backed run still spent ~435s before the first serious notebook edit. That means materialized tables helped execution, but not discovery. The agent still paid to understand the dbt project from scratch.

## Query Path Difference

### 14:02 raw fallback

- Started from intended dbt marts, but `fct_transfers` was not available in the DB.

- Searched schemas/tables, concluded only raw schemas existed.

- Reimplemented revenue from raw tables: `raw_core_transfers.transfers`, `raw_core_transfers.customers`, `raw_core_transfers.transfer_fees`, and `raw_fx.fx_rates`.

- Used `customers.currency = 'GBP'` as the customer population, then included GBP/EUR/USD send currencies and converted revenue into GBP.

- This answered “GBP customers, GBP-equivalent revenue,” not “GBP transfers.”


Representative raw fallback SQL pattern:

```sql
SELECT t.send_currency AS revenue_currency, COUNT(*) AS total_transfers, COUNT(*) FILTER (WHERE t.status = 'COMPLETED') AS completed_transfers, ROUND(SUM(t.send_amount) FILTER (WHERE t.status = 'COMPLETED'), 2) AS completed_send_volume, ROUND(SUM(t.fee_amount) FILTER (WHERE t.status = 'COMPLETED'), 2) AS completed_fee_amount, ROUND(SUM(t.send_amount * t.fx_margin_bps / 10000.0) FILTER (WHERE t.status = 'COMPLETED'), 2) AS completed_fx_margin_modelled, ROUND( SUM(t.fee_amount) FILTER (WHERE t.status = 'COMPLETED') + SUM(t.send_amount * t.fx_margin_bps / 10000.0) FILTER (WHERE t.status = 'COMPLETED') , 2) AS completed_total_revenue_modelled FROM raw_core_transfers.transfers t JOIN raw_core_transfers.customers c ON t.customer_id = c.customer_id WHERE c.currency = 'GBP' AND t.created_at >= '2026-01-01' AND t.created_at < '2026-04-01' GROUP BY t.send_currency
```

### 15:45 mart backed

- Found the mart schema and queried `analytics_marts.fct_transfers`.

- Used `send_currency = 'GBP'`, `is_completed = true`, and Q1 `created_at` bounds.

- Avoided manual raw-table joins, fee reconstruction, and FX-rate lookup.

- This answered “completed GBP transfers in Q1,” using mart-defined revenue.

```sql
SELECT COUNT(*) as transfer_count, ROUND(SUM(fee_revenue)::numeric, 2) as total_fee_revenue, ROUND(SUM(fx_margin_revenue)::numeric, 2) as total_fx_margin_revenue, ROUND(SUM(total_revenue)::numeric, 2) as total_revenue, MIN(created_at::date) as earliest_transfer, MAX(created_at::date) as latest_transfer FROM analytics_marts.fct_transfers WHERE send_currency = 'GBP' AND is_completed = true AND created_at >= '2026-01-01' AND created_at < '2026-04-01'
```

## Why The Answers Diverged

| Difference | 14:02 raw fallback | 15:45 mart backed | Effect |
|---|---|---|---|
| Population filter | `customers.currency = 'GBP'` | `send_currency = 'GBP'` | Different transfer population |
| Currency handling | Mixed GBP/EUR/USD revenue converted to GBP | Revenue already in GBP send-currency mart rows | Different conversion and inclusion logic |
| Source of revenue logic | Manual reconstruction from raw fields | dbt mart columns `fee_revenue`, `fx_margin_revenue`, `total_revenue` | Mart can include business rules not replicated exactly in fallback |
| Count basis | 220 completed transfers | 190 completed transfers | 30 fewer transfers in mart-backed answer |
| Revenue basis | £2,087.68 GBP equivalent | £2,530.33 transfer revenue | Mart result is £442.65 higher despite fewer transfers |
| Date basis | `created_at` | `created_at` | Same broad date field, still caveated vs completion/settlement date |

The most likely explanation is a semantic mismatch: “UK (GBP) customers” is ambiguous. If business means “customers whose home/default currency is GBP,” the raw fallback is closer in population but weaker in implementation. If business means “transfers sent in GBP,” the mart-backed run is closer. If business means “UK-domiciled customers,” neither run fully proves it because neither final query joined `dim_customers.home_country = 'GB'`.

## Tool/Discovery Behavior

| Tool | 14:02 | 15:45 | What changed |
|---|---:|---:|---|
| `Agent` | 1 | 1 |  |
| `Glob` | 4 | 5 |  |
| `Grep` | 0 | 1 |  |
| `Read` | 34 | 18 | materialized mart path required fewer project reads |
| `ToolSearch` | 1 | 1 |  |
| `mcp__signalpilot-notebook__edit_notebook` | 14 | 7 | raw fallback required more notebook rewriting |
| `mcp__signalpilot-notebook__get_lightweight_cell_map` | 1 | 2 |  |
| `mcp__signalpilot-notebook__get_notebook_errors` | 1 | 0 | 14:02 checked errors but still had stale markers; 15:45 did not call it |
| `mcp__signalpilot-notebook__run_cells` | 13 | 6 | raw fallback required more execution/repair loops |

## File Read Difference

### Reads unique to 14:02

- `/home/notebook/.sp/projects/907a47d1-b196-428b-89de-7f4a8b7acc41/fin-project/models/intermediate/int_ledger_entries.sql`
- `/home/notebook/.sp/projects/907a47d1-b196-428b-89de-7f4a8b7acc41/fin-project/models/intermediate/int_transfers_funding.sql`
- `/home/notebook/.sp/projects/907a47d1-b196-428b-89de-7f4a8b7acc41/fin-project/models/intermediate/int_transfers_payout.sql`
- `/home/notebook/.sp/projects/907a47d1-b196-428b-89de-7f4a8b7acc41/fin-project/models/marts/finance/fct_fx_pnl_daily.sql`
- `/home/notebook/.sp/projects/907a47d1-b196-428b-89de-7f4a8b7acc41/fin-project/models/marts/finance/fct_ledger_balances.sql`
- `/home/notebook/.sp/projects/907a47d1-b196-428b-89de-7f4a8b7acc41/fin-project/models/staging/raw_core_transfers/stg_core_transfers__recipients.sql`
- `/home/notebook/.sp/projects/907a47d1-b196-428b-89de-7f4a8b7acc41/fin-project/models/staging/raw_core_transfers/stg_core_transfers__transfer_fees.sql`
- `/home/notebook/.sp/projects/907a47d1-b196-428b-89de-7f4a8b7acc41/fin-project/models/staging/raw_flutterwave/_raw_flutterwave__sources.yml`
- `/home/notebook/.sp/projects/907a47d1-b196-428b-89de-7f4a8b7acc41/fin-project/models/staging/raw_fx/_raw_fx__sources.yml`
- `/home/notebook/.sp/projects/907a47d1-b196-428b-89de-7f4a8b7acc41/fin-project/models/staging/raw_ledger/_raw_ledger__sources.yml`
- `/home/notebook/.sp/projects/907a47d1-b196-428b-89de-7f4a8b7acc41/fin-project/models/staging/raw_marqeta/_raw_marqeta__sources.yml`
- `/home/notebook/.sp/projects/907a47d1-b196-428b-89de-7f4a8b7acc41/fin-project/models/staging/raw_mpesa/_raw_mpesa__sources.yml`
- `/home/notebook/.sp/projects/907a47d1-b196-428b-89de-7f4a8b7acc41/fin-project/models/staging/raw_onfido/_raw_onfido__sources.yml`
- `/home/notebook/.sp/projects/907a47d1-b196-428b-89de-7f4a8b7acc41/fin-project/models/staging/raw_plaid/_raw_plaid__sources.yml`
- `/home/notebook/.sp/projects/907a47d1-b196-428b-89de-7f4a8b7acc41/fin-project/models/staging/raw_segment/_raw_segment__sources.yml`
- `/home/notebook/.sp/projects/907a47d1-b196-428b-89de-7f4a8b7acc41/fin-project/models/staging/raw_stripe/_raw_stripe__sources.yml`

### Reads unique to 15:45


14:02 read broader source/model context because it had to fall back into raw schemas. 15:45 read a narrower subset and added a targeted `Grep` to understand `home_country`/`send_country`.

## Validation Quality

### 14:02

- Stronger cross-checking against raw components: modeled revenue vs transfer fees, monthly totals, corridor totals, FX conversion repair.

- Weaker final cleanliness: `get_notebook_errors` reported two ancestor-error cells; the agent reasoned they were stale and continued.

- Weaker semantic reliability: hand-reimplemented dbt logic from raw tables and latest FX rates.


### 15:45

- Stronger canonicality: used the mart and mart-defined `total_revenue`.

- Cleaner execution path after fixes: final text says all 14 cells ran cleanly and reconciliations passed.

- Weaker explicit verification: no `get_notebook_errors` call; we rely on `run_cells` output and the assistant text.

- Same unresolved business ambiguity: `send_currency = 'GBP'` is not the same as “UK-domiciled customers.”

## What This Proves For Cost/SLA

Materialized marts are a big improvement, but they do not remove agent discovery cost by themselves. The 15:45 run still spent most of its wall time before executing the final mart query. The next system improvement should be to hand the agent a compact semantic routing packet before any file reads.

Suggested routing packet for this class of question:

```yaml
question_class: transfer_revenue
primary_relation: analytics_marts.fct_transfers
metric: sum(total_revenue)
required_filters:
  completed: is_completed = true
  period: created_at >= :start and created_at < :end
uk_gbp_definition_options:
  - send_currency = 'GBP'
  - send_country = 'GB'
  - join dim_customers on customer_id and filter home_country = 'GB'
recommended_validation:
  - status breakdown
  - monthly total reconciles to headline
  - component total reconciles to headline
  - final get_notebook_errors
```

## Concrete Product Recommendations

1. **Materialized marts stay mandatory.** The direct `analytics_marts.fct_transfers` path cut calls and cost, and avoided raw reimplementation.

2. **Add semantic routing, not just dbt files.** The agent should begin with “use this relation/metric/filter,” then inspect dbt only if confidence is low.

3. **Define “UK (GBP) customers.”** Pick one canonical definition. The two runs prove ambiguity can move the answer by **£442.65**.

4. **Expose live connection names.** The dbt `profiles.yml` connection `nala` wasted time; runtime had `fin-db`. Put runtime connection aliases in the agent prompt/context.

5. **Require final structured verification.** Every run should end with a machine-checkable clean notebook status, not a prose assertion.

6. **Cache dbt manifest/catalog summaries.** That should remove the 16-32 file-read tax for common finance questions.
