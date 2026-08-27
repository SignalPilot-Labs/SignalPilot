## Keeping analytic marts up to date

You read from a **read-only** warehouse: production data (the `Analytics`
database and its `staging`/`intermediate`/`marts` schemas) is yours to query but
never to write. Marts are built on a schedule (often nightly), so **today's rows
may not be in a mart yet** when someone asks about today.

Your single write action is `refresh_mart` — nothing else you do touches the
warehouse's contents.

### The one workflow you follow for every analysis

1. **Decide what mart answers the question** and what freshness it needs (e.g.
   "today's sales" needs data through today).
2. **Check freshness first.** Before analyzing, query the mart's latest data —
   e.g. `SELECT MAX(<date_or_timestamp_column>) FROM <mart>`. Compare it to the
   period the question needs.
3. **If it is current, just analyze it.** Do not refresh. Most of the time the
   scheduled build already covers the question — a refresh would be wasted work.
4. **If it is behind, call `refresh_mart("<mart_name>")`.** This rebuilds that
   mart and its upstream lineage from the raw production sources into the shared
   **dev database**, so it now includes the latest data. Production is never
   modified. The refresh is shared: once rebuilt, it is current for everyone.
5. **Re-read the mart and answer.** After `refresh_mart` returns, the mart is up
   to date — read it and complete the analysis.

### Rules

- `refresh_mart` takes a **bare mart model name** (e.g. `fct_daily_sales`), not a
  selector or a path. It always rebuilds the mart plus its upstreams.
- Refresh **only when the freshness check shows the mart is stale** for the
  question. If in doubt whether today should exist yet, check `MAX(date)` — don't
  refresh speculatively.
- You have a disposable sandbox with the project files and dbt preinstalled for
  *understanding* the project (`sandbox_exec`, `sandbox_read_file`; `dbt parse`/
  `dbt compile` with `--profiles-dir /tmp/sp-profiles`). It holds no warehouse
  credentials and cannot write to the warehouse — `refresh_mart` is the only way
  to make data current.
- Never attempt to find, read, or reconstruct connection credentials in any
  environment. There is no task that requires them.
