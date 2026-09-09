---
name: dashboard
description: "Load when the user asks for a dashboard. Covers the dashboard JSON file, SQL datasets, chart types, and the two check tools."
type: skill
---

# Dashboard

A dashboard is one file: `artifacts/<name>.dashboard.json`. You write the
file. The chat renders it as an interactive dashboard. The exact contract is
`dashboard.schema.json` in this skill directory. Read it when a check tool
reports a schema error.

The renderer does not aggregate, join, or compute. It reads rows from the
datasets you name, applies filter defaults, the chart `sort`, and the chart
`limit`, then draws. Aggregate the data in SQL before you write the file.

## Datasets

Every dataset comes from one SQL query. The query defines the dataset. The
rows the dashboard shows are only the cached result of that query.

- Put all derivations in the SQL. Use window functions for trailing sums and
  year-over-year change. Use `CASE` for groupings such as region. Use CTEs
  for shares and ranks.
- Do not transform rows in pandas. A dataset that is shaped outside SQL
  cannot be refreshed, and the check tools report it as stale.
- Call `sp.dashboard_dataset("monthly", connection="warehouse", sql="...")`
  once per dataset in the notebook. It runs the query on the governed path,
  writes the snapshot at `artifacts/datasets/monthly.csv`, records the SQL
  that produced it, and returns a DataFrame you can inspect.
- Copy the same connection and SQL into the dashboard file. The check tools
  compare the file against the record. A different SQL or connection is
  `snapshot_stale`.
- Use `rows` only for constants that never change. Inline `rows` hold at
  most 5000 flat objects.
- Never write `artifacts/datasets/*.csv` by hand.

## Workflow

Load the skill `signalpilot-dbt:notebook` first. It explains the notebook
tools and the `sp` SDK that the steps below use.

1. Write one SQL query per dataset. Aggregate to the grain the chart shows:
   one row per bar, per point, per pie slice, or per table row. Run
   `sp.dashboard_dataset(name, connection=..., sql=...)` for each. Read the
   returned DataFrame and fix the SQL until the columns and rows are right.
2. Write `artifacts/<name>.dashboard.json` with the same connection and SQL
   in `datasets`. Give every chart a stable `id` that matches
   `^[a-z][a-z0-9_]{0,63}$`. Keep the same ids when you change the file
   later.
3. Call `dashboard_sample_data` with the path and all chart ids. Read the
   `issues` of every chart. Fix each issue in the file or in the SQL. After
   a SQL change, call `sp.dashboard_dataset` again and copy the SQL into the
   file again.
4. Call `dashboard_screenshot` with the path. Look at the image. Fix layout,
   axis, format, and series problems in the file.
5. Repeat steps 3 and 4 at most two times. Stop when no issue remains, or
   after two loops. Report an issue you could not fix.
6. Reference the dashboard one time in the reply, directly under the finding
   it supports: `[Revenue overview](artifacts/revenue.dashboard.json)`. Do not
   describe chart values in prose that the dashboard already shows.

## Edit a published dashboard

When the user asks to edit, update, or change a dashboard that already
exists, do not write a new file from scratch. Load the published one.

1. Call `dashboard_list_published`. Find the dashboard by name, slug, or
   description. If none matches, tell the user which dashboards exist.
2. Call `dashboard_load_published` with the id or slug. It writes
   `artifacts/<slug>.dashboard.json` and the snapshot of every SQL dataset
   from the current version. The result names the file path and the row
   count of each dataset.
3. Edit that file. Keep the chart ids that stay. Add, remove, or change
   charts, filters, and datasets as the user asked.
4. For each dataset whose SQL or connection you changed, call
   `sp.dashboard_dataset` in the notebook with the new SQL. Copy the same
   SQL into the file. Unchanged datasets keep their loaded snapshots.
5. Call `dashboard_sample_data` with the path and all chart ids. Fix every
   issue.
6. Call `dashboard_screenshot` with the path. Look at the image. Fix the
   layout.
7. Reference the file one time in the reply:
   `[Title](artifacts/<slug>.dashboard.json)`.
8. Tell the user to publish the file as a new version of the same
   dashboard from the chat panel. Do not create a second dashboard.

## Worked example

The notebook cell:

```python
monthly_sql = """
with monthly as (
  select
    date_trunc('month', order_date) as month,
    case
      when country in ('US', 'CA', 'MX') then 'North America'
      when country in ('GB', 'DE', 'FR', 'NL') then 'Europe'
      else 'Rest of world'
    end as region,
    sum(net_revenue) as revenue
  from fct_orders
  where order_status = 'completed' and order_date >= '2024-01-01'
  group by 1, 2
)
select
  month,
  region,
  revenue,
  sum(revenue) over (
    partition by region
    order by month
    rows between 11 preceding and current row
  ) as revenue_ttm
from monthly
where month >= '2025-01-01'
order by month, region
"""
monthly = sp.dashboard_dataset("monthly", connection="warehouse", sql=monthly_sql)
monthly.head()
```

The `CASE` maps countries to regions. The window function computes the
trailing twelve month sum. The query reads from 2024 so the first months of
2025 have a full window, then keeps only 2025 rows. The dashboard file
carries the same SQL:

```json
{
  "version": 1,
  "title": "Revenue overview",
  "description": "Net revenue by month and region, 2025.",
  "layout": { "columns": 12, "rowHeight": 72 },
  "datasets": {
    "monthly": {
      "connection": "warehouse",
      "sql": "with monthly as (select date_trunc('month', order_date) as month, case when country in ('US', 'CA', 'MX') then 'North America' when country in ('GB', 'DE', 'FR', 'NL') then 'Europe' else 'Rest of world' end as region, sum(net_revenue) as revenue from fct_orders where order_status = 'completed' and order_date >= '2024-01-01' group by 1, 2) select month, region, revenue, sum(revenue) over (partition by region order by month rows between 11 preceding and current row) as revenue_ttm from monthly where month >= '2025-01-01' order by month, region"
    },
    "totals": { "rows": [ { "revenue": 1234567.8, "orders": 8123 } ] }
  },
  "filters": [],
  "charts": [
    {
      "id": "revenue_ttm", "type": "line", "title": "Trailing twelve month revenue",
      "dataset": "monthly",
      "x": { "column": "month", "type": "date" },
      "y": [ { "column": "revenue_ttm", "format": "currency:USD" } ],
      "series": { "column": "region" },
      "sort": { "column": "month" }
    }
  ]
}
```

Whitespace differences between the notebook SQL and the file SQL are
allowed. Any other difference is `snapshot_stale`.

## The file

- `version` is always `1`.
- `datasets` keys match `^[a-z][a-z0-9_]{0,63}$`. Each dataset is
  `{ "connection": "<name>", "sql": "<query>" }` or `{ "rows": [ ... ] }`.
  No other keys are allowed.
- Use ISO dates: `YYYY-MM-DD` or a full ISO datetime. Cast in SQL when the
  warehouse returns another format.
- Write numbers as numbers, not as formatted strings.

## Chart types

Every chart has `id`, `type`, `title`, `dataset`, and optional
`description`, `sort`, `limit`, and `grid`.

### kpi

Shows the `value` column of the first row. `comparison` shows a second
column from the same row, small, under the value.

```json
{
  "id": "total_revenue", "type": "kpi", "title": "Net revenue",
  "dataset": "totals",
  "value": { "column": "revenue", "format": "currency:USD" },
  "comparison": { "column": "orders", "label": "Orders", "format": "integer" }
}
```

### table

```json
{
  "id": "region_table", "type": "table", "title": "Revenue by region",
  "dataset": "by_region",
  "columns": [
    { "column": "region", "label": "Region" },
    { "column": "revenue", "label": "Revenue", "format": "currency:USD" },
    { "column": "growth", "label": "Growth", "format": "percentage" }
  ],
  "sort": { "column": "revenue", "direction": "desc" },
  "limit": 20
}
```

### bar, line, area

`x` is the axis column. `y` is a list of one to eight numeric columns.
Set `x.type` to `"date"` for time axes, `"number"` for numeric axes, and
`"category"` (the default) for labels.

```json
{
  "id": "revenue_by_month", "type": "line", "title": "Revenue by month",
  "dataset": "monthly",
  "x": { "column": "month", "type": "date", "label": "Month" },
  "y": [ { "column": "revenue", "label": "Revenue", "format": "currency:USD" } ]
}
```

Use `series` to split one y column by the values of another column. This
is allowed only when `y` has exactly one entry.

```json
{
  "id": "revenue_by_region", "type": "bar", "title": "Revenue by region",
  "dataset": "monthly",
  "x": { "column": "month", "type": "date" },
  "y": [ { "column": "revenue", "format": "compact" } ],
  "series": { "column": "region", "stack": true }
}
```

- `stack: true` on the chart stacks several y columns.
- `horizontal: true` on a bar chart draws horizontal bars.

### pie

```json
{
  "id": "region_share", "type": "pie", "title": "Share by region",
  "dataset": "by_region",
  "label": "region",
  "value": { "column": "revenue", "format": "percentage" },
  "donut": true,
  "limit": 8
}
```

### scatter

```json
{
  "id": "orders_vs_revenue", "type": "scatter", "title": "Orders and revenue",
  "dataset": "by_region",
  "x": { "column": "orders", "type": "number" },
  "y": { "column": "revenue", "format": "currency:USD" },
  "size": "customers",
  "color": "region"
}
```

## Formats

`format` on a series, value, or column controls the number display:

| Value | Display |
|---|---|
| `integer` | `12,345` |
| `decimal` | `12,345.68` |
| `compact` | `12.3K`, `1.2M` |
| `percentage` | value times 100 with one decimal: `0.123` shows `12.3%` |
| `currency:USD` | `$12,346`; two decimals under 1000 |

Store percentages as fractions (`0.123`), not as `12.3`.

## Filters

Filters live at the top level. A filter names a `column`. Omit `dataset` and
the filter applies to every dataset that has that column, so one control can
drive several charts. Set `dataset` to bind the filter to one dataset only.
The `default` is applied by the renderer and by the check tools.

| Type | `default` |
|---|---|
| `equals` | one scalar |
| `in` | array of scalars; empty means no filter |
| `date_range` | `{ "from": "2025-01-01", "to": "2025-12-31" }`, each optional |
| `number_range` | `{ "min": 0, "max": 100 }`, each optional |

```json
{ "id": "region", "label": "Region", "column": "region", "type": "in", "default": [] }
```

Give the same column name to every dataset a shared filter must drive, for
example `region` in the monthly, market, and channel datasets. A filter bound
with `dataset` must find its column there.

## Grid

The grid has 12 columns. `grid: { "x", "y", "w", "h" }` places a tile at
column `x` (0 to 11), row `y`, with width `w` (1 to 12) and height `h` rows.
One row is `layout.rowHeight` pixels (default 72).

Tiles without `grid` flow after the placed tiles, left to right, and wrap at
12 columns:

| Type | Auto size |
|---|---|
| kpi | w 3, h 2 |
| table | w 12, h 5 |
| all others | w 6, h 4 |

Give KPIs `h: 2`. Give charts at least `h: 4`. Do not overlap tiles.

## Issue codes

`dashboard_sample_data` returns `issues` per chart. `dashboard_screenshot`
returns `failed` entries with the same codes.

| Code | Effect | What to do |
|---|---|---|
| `missing_dataset` | chart fails | Add the dataset to `datasets` or fix the chart `dataset` name. |
| `snapshot_missing` | chart fails | No snapshot at `artifacts/datasets/<name>.csv`. Call `sp.dashboard_dataset` for that dataset in the notebook. |
| `snapshot_stale` | chart fails | The connection or SQL in the file is not the one that produced the snapshot. Call `sp.dashboard_dataset` again with the SQL from the file, or copy the notebook SQL into the file. |
| `dataset_unreadable` | chart fails | The snapshot is not parseable. Call `sp.dashboard_dataset` again. |
| `missing_column` | chart fails | Use a column from the listed columns, or add the column to the SQL. |
| `series_with_multi_y` | chart fails | Keep one y column with `series`, or remove `series`. |
| `empty_dataset` | warning | No rows after filters, sort, and limit. Check the filter defaults and the SQL. |
| `non_numeric_y` | warning | The y or value column has text. Cast to a number in SQL. |
| `unparseable_date` | warning | Cast dates to `YYYY-MM-DD` in SQL, or set `x.type` to `category`. |
| `too_many_rows` | warning | More than 50000 rows. Aggregate in SQL or add a `limit`. |
| `unknown_chart` | tool only | The id is not in the file. Use one of the listed ids. |

`dashboard_screenshot` can return these `"error"` values:

| Error | What to do |
|---|---|
| `renderer_unavailable` | The image has no renderer. Rely on `dashboard_sample_data` and continue. |
| `render_failed` | Read the message. Fix the cause and call it again. |
| `unknown_chart` | One id in `chart_ids` is not in the file. Use the listed ids. |
| `payload_too_large` | The datasets are too big to render. Aggregate in SQL or add a `limit` to the charts, then call it again. |

## Rules

- One SQL query per dataset. All derivations in SQL. No pandas transforms.
- Aggregate in SQL. The renderer does not aggregate.
- One finding per chart. Keep the series count at 8 or fewer and the
  category count at 24 or fewer.
- Sort time series by date in SQL, and set `sort` on the chart.
- Keep the file small. Put large tables in SQL datasets, not in inline
  `rows`.
- Do not write HTML dashboards. Do not draw dashboards with matplotlib.
- Never write into the dbt project. The file goes under `artifacts/`.

See `examples/revenue.dashboard.json` in this skill directory for a
complete valid file.
