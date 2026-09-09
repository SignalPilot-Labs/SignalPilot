---
name: notebook
description: "Load before you edit or run notebook cells in chat. Covers the notebook tools, the sp SDK, governed queries, files, and charts."
type: skill
---

# Notebook

The chat gives you one analysis notebook and optional named notebooks. Use them
to run queries, compute results, and save files. Evidence for an answer comes
from the analysis notebook.

## Start a notebook

1. Call `start_analysis_notebook` only when you will run cells. A notebook
   that you start and do not use rejects the whole run.
2. Pass `notebook: "scratch"` (short, lowercase) to start a separate notebook
   for drafting. Each name has its own kernel and `session_id`.
3. Use the `session_id` from the tool result with every notebook tool.

## The seeded cells

The notebook starts with two hidden cells. Never edit or remove them.

- Cell 1 imports `sp`, sets `SP_CHAT_SCRATCH_DIRECTORY` and
  `SP_CHAT_ARTIFACTS_DIRECTORY`, and returns `sp`.
- Cell 2 runs `sp.init(...)` and defines `db = sp.connect("<connection>")`.

`sp.init()` returns None. There is no `signalpilot.db` export. Use `db` and
`sp` from these cells. Do not import `signalpilot` again.

## Cell rules (marimo, not Jupyter)

- One live cell defines each top-level name. A second definition raises
  `MultipleDefinitionError`. Fix all conflicting cells in one edit batch.
- Prefix disposable names with one underscore, for example `_fig`. Never use
  an underscore name from another cell.
- Build DataFrames from query results. Show a small preview only.

## Tools

| Tool | Use |
|---|---|
| `edit_notebook` | `edits`: `add_cell` (code), `update_cell` (cell_id, code), `delete_cell` (cell_id). One batch per change set. |
| `run_cells` | Runs the given `cell_ids` (all cells when omitted) and blocks. Returns outputs, console text, and errors per cell. Set `timeout` for long queries. |
| `save_data_snapshot` | Saves a compact aggregate for an external deliverable. Do not dump raw tables. |
| `start_notebook_session` | Opens a `.py` notebook file you wrote with `Write` and returns its `session_id`. |

Read every `run_cells` result. A cell with `status: "failed"` has an
`error.message`. Fix the cell and run it again.

## The sp SDK

| Call | Result |
|---|---|
| `sp.connections()` | Names of the connections you may query. |
| `db.query(sql, row_limit=1000)` | Rows as a list of dicts. |
| `db.query_result(sql, row_limit=100_000)` | Dict with `rows`, `columns`, and `completeness`. `truncated` means the limit cut the result. Aggregate or add a limit. |
| `db.query_dataset(sql)` | A private Parquet dataset for large results. Open it with `sp.open_dataset(ref)`. |
| `sp.artifact_path("name.png")` | The path for one artifact file. |
| `sp.dashboard_dataset(name, connection=..., sql=...)` | Runs the SQL and writes a dashboard snapshot. See the `signalpilot-dbt:dashboard` skill. |
| `sp.publish_result(dataframe, name=..., ...)` | Publishes a compact result without exposing rows to the agent. |

Rules:

- Every query goes through `db` or `sp.connect(name)`. Never open a warehouse
  connection from `Bash`, a driver, or a script. The data plane is read-only.
- Write SQL in the dialect of the connection. SQL Server connections take
  T-SQL, for example `select top 10`. Postgres connections take Postgres SQL.
- Never copy MCP row previews into a DataFrame. Query the data in the notebook.
- `Gateway error (HTTP 400): Query blocked` means governance refused the SQL.
  Read the reason. Fix the SQL or the table access. Do not work around it.
- `aggregate_required` means: rewrite the work as a bounded warehouse
  aggregate. `refuse` means: stop and tell the user.

## Files

- Deliverables go to `$SP_CHAT_ARTIFACTS_DIRECTORY` through
  `sp.artifact_path(...)`. The chat shows each file as soon as you save it.
  No publish call is necessary. Save a file again after you change it.
- Working notes (`analytics-steps.md`, `prebuild-state.md`) go to
  `$SP_CHAT_SCRATCH_DIRECTORY`, not to `artifacts/`.
- Use short lowercase file names with underscores.
- The chat ignores dot-files, `*.log`, `__pycache__`, dbt target dirs, and
  top-level `*.py` and `*.duckdb` files.

## Charts

1. Make charts in the analysis notebook with matplotlib. The house theme is
   applied by the setup cell. Do not set colors, fonts, or a style.
2. One chart per cell. One finding per chart. Add a title, axis labels with
   units, and a legend for more than one series.
3. Save with `fig.savefig(sp.artifact_path("revenue_by_month.png"))`. Do not
   pass `dpi`, `facecolor`, or `bbox_inches`. The SDK sets them.
4. You cannot see the image. Check the data first: x values sorted, 8 series
   or fewer, 24 categories or fewer, no null values. The saved file is the only
   proof that the chart rendered.
5. Never draw charts with block characters, ASCII, or emoji.

## Tables and reports

- A table the user will reuse: `dataframe.to_csv(sp.artifact_path("name.csv"), index=False)`.
  Keep the column names, precision, and date format rules from the skills.
- A long analysis: also save `artifacts/report.md` or `artifacts/report.html`.
  The chat answer is still the full answer.

## Troubleshooting

| Symptom | Cause | Action |
|---|---|---|
| `MultipleDefinitionError` | Two cells define one name. | Rename with an underscore, or update the old cell in the same batch. |
| `NameError` for `db` or `sp` | The seeded cells did not run. | Run all cells once with `run_cells` and no `cell_ids`. |
| `Query blocked: SQL parse error` | The SQL is not valid in the connection dialect. | Fix the SQL for that dialect. |
| `completeness: "truncated"` | The row limit cut the result. | Aggregate in SQL or raise `row_limit`. |
| `run_cells` timed out | A slow query. | Add a `timeout`, or aggregate in SQL. |
