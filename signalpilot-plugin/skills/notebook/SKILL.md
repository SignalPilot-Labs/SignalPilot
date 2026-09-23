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
4. Make the first visible cell a title: `sp.md("# <title of the analysis>")`.
   Write a short title from the user's request, not the prompt text. Update
   it when the question changes. A markdown cell does not need `sp.init()`
   and must not import `signalpilot` again.

## The seeded cells

The notebook starts with two hidden cells and one empty visible cell. Never
edit or remove the hidden cells. Put the title in the empty cell.

- Cell 1 DEFINES `os`, `Path`, `runtime_context` and `sp`, sets
  `SP_CHAT_SCRATCH_DIRECTORY` and `SP_CHAT_ARTIFACTS_DIRECTORY`, and EXPORTS
  `Path`, `runtime_context`, `sp`.
- Cell 2 defines and exports `db`, `np`, `pd`.

Redefining any of those seven names raises `MultipleDefinitionError`. That
includes `import os`, even though `os` is not exported to your cells: it is
defined, so you cannot define it again, and it is not exported, so you cannot
use it. Import nothing that is already defined.

**Nothing else is defined. `plt` is not.** `sp.init()` has already applied the
house theme to matplotlib's `rcParams`, including `savefig.dpi` and
`savefig.bbox`, but the module itself is not imported. Put
`import matplotlib.pyplot as plt` in one cell of your own before the first
chart cell.

`sp.init()` returns None. There is no `signalpilot.db` export. Use `db` and
`sp` from these cells. Do not import `signalpilot` again.

## Before you write the first cell

Write every cell of the analysis before running any of them. Fixing cells until
they stop erroring produces code that runs and answers the wrong question.

Settle these four facts first, from the dbt project and `sp.describe_table`,
not by trial:

1. The connection's SQL dialect. SQL Server takes `YEAR(x)`, `select top 10`,
   and three-part `Database.schema.table` names, which the governed parser
   requires.
2. The definition of every column you will name, read from its model SQL. A
   column that sums cleanly can still mean something other than its name.
3. Which names must be public because a later cell reads them, and which are
   `_`-prefixed scratch private to one cell.
4. The grain of each mart, so you know whether your `GROUP BY` fans out.

## Cell rules (marimo, not Jupyter)

- One live cell defines each top-level name. A second definition raises
  `MultipleDefinitionError`. Fix all conflicting cells in one edit batch.
- An underscore name is local to the cell that writes it, and the editor
  rejects the WHOLE batch if another cell reads it. Decide before you write: a
  value the next cell needs gets a public name; a value used only inside this
  cell gets one underscore. `_fig`, `_ax` and loop variables are always
  underscore. After a `PrivateVariableCrossCellReference`, promote the name in
  the defining cell and resend both cells in one batch.
- Get every DataFrame with `db.query_df(sql)`. Show a small preview only.
- One query per cell, and no more than a few derived columns after it.
  Aggregate in SQL; use Python for ratios and formatting only. Keep a cell
  under 20 lines, define at most one public name in it, and end it in one bare
  expression or one `print`. A cell that runs three queries and twenty pandas
  statements fails as a unit, and its error output is truncated.
- Batching many small cells into one `edit_notebook` call is correct. Putting
  many steps into one cell is not.
- `pd` and `np` are already imported in the setup cell. Do not import them
  again.
- Use only the methods this skill names. The SDK has no other functions.

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
| `db.query_df(sql, row_limit=1000)` | **The default.** A typed DataFrame: numeric and date columns are already converted. |
| `db.query(sql, row_limit=1000)` | Rows as a list of dicts. Call `.df()` on it to get a typed DataFrame. |
| `db.query_result(sql, row_limit=100_000)` | Dict with `rows`, `columns`, and `completeness`. `truncated` means the limit cut the result. Aggregate or add a limit. |
| `db.query_dataset(sql)` | A private Parquet dataset for large results. Open it with `sp.open_dataset(ref)`. |
| `sp.artifact_path("name.png")` | The path for one artifact file. |
| `sp.dashboard_dataset(name, connection=..., sql=...)` | Runs the SQL and writes a dashboard snapshot. See the `signalpilot-dbt:dashboard` skill. |
| `sp.publish_result(dataframe, name=..., ...)` | Publishes a compact result without exposing rows to the agent. |

Rules:

- Never write your own query helper. `db.query_df(sql)` already returns a typed
  frame; `db.query(sql)` returns a list of row dicts, and only
  `db.query_result(sql)` returns a dict with a `rows` key. They are three
  different shapes, so do not index one like another. Never hand-write a
  `pd.to_numeric` or `.astype(float)` pass over a query result: if you are
  writing one, you called the wrong method.
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

- `sp.artifact_path("name.png")` returns the path for a deliverable and
  creates its directory. Pass it straight to `savefig`, `to_csv` or `open`.
  Never read `SP_CHAT_ARTIFACTS_DIRECTORY` yourself, never `mkdir`, never copy
  a file into it, and there is no publish call. Save a file again after you
  change it.
- Saving a file makes it exist; only a reference makes it visible. Reference it
  once, on its own line, under the finding it supports: an image as
  `![alt](artifacts/name.png)`, anything else as
  `[Download name.ext](artifacts/name.ext)`.
- Working notes (`analytics-steps.md`, `prebuild-state.md`) go to
  `$SP_CHAT_SCRATCH_DIRECTORY`, not to `artifacts/`.
- Use short lowercase file names with underscores.
- The chat ignores dot-files, `*.log`, `__pycache__`, dbt target dirs, and
  top-level `*.py` and `*.duckdb` files.

## Charts

1. Make charts in the analysis notebook with matplotlib. `plt` is NOT
   pre-imported: add `import matplotlib.pyplot as plt` once, in one cell, before
   the first chart. The house theme is already applied to `rcParams` by
   `sp.init()`. Do not set colors, fonts, or a style.
2. One chart per cell, one finding per chart, and one figure per chart. Never
   call `plt.subplots(rows, cols)` with more than one axis to build a
   multi-panel dashboard: the chat shows each saved PNG at one size, and a 3x2
   grid is unreadable. Six findings are six cells and six files. Add a title,
   axis labels with units, and a legend for more than one series.
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
| `NameError: name 'plt' is not defined` | `plt` is not seeded. | Add one cell with `import matplotlib.pyplot as plt`, then run the chart cells again. |
| `PrivateVariableCrossCellReference` | A cell reads an `_`-prefixed name from another cell. | Promote the name in the defining cell and resend both cells in one batch. |
| `CellNotFound` | The kernel restarted, so cell ids from before the restart are gone. | Call `get_lightweight_cell_map` for current ids. Re-add the cell and run all cells once. Do not add your own `import signalpilot` or `sp.init()` to recover. |
