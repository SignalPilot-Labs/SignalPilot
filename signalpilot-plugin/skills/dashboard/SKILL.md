---
name: dashboard
description: "Load when the user asks for a dashboard. Covers the dashboard JSON file, datasets, chart types, and the two check tools."
type: skill
---

# Dashboard

A dashboard is one file: `artifacts/<name>.dashboard.json`. You write the
file. The chat renders it as an interactive dashboard. The exact contract is
`dashboard.schema.json` in this skill directory. Read it when a check tool
reports a schema error.

The renderer does not aggregate, join, or compute. It reads rows from the
datasets you name, applies filter defaults, the chart `sort`, and the chart
`limit`, then draws. Aggregate the data before you write it.

## Workflow

1. Compute each dataset in the analysis notebook. Aggregate to the grain the
   chart shows: one row per bar, per point, per pie slice, or per table row.
   Write each dataset with
   `dataframe.to_csv(sp.artifact_path("name.csv"), index=False)`.
2. Write `artifacts/<name>.dashboard.json`. Give every chart a stable `id`
   that matches `^[a-z][a-z0-9_]{0,63}$`. Keep the same ids when you change
   the file later.
3. Call `dashboard_sample_data` with the path and all chart ids. Read the
   `issues` of every chart. Fix each issue in the file or in the data.
4. Call `dashboard_screenshot` with the path. Look at the image. Fix layout,
   axis, format, and series problems in the file.
5. Repeat steps 3 and 4 at most two times. Stop when no issue remains or
   when the two loops are used. Report an issue you could not fix.
6. Reference the dashboard one time in the reply, directly under the finding
   it supports: `[Revenue overview](artifacts/revenue.dashboard.json)`. Do not
   describe chart values in prose that the dashboard already shows.

## The file

```json
{
  "version": 1,
  "title": "Revenue overview",
  "description": "Net revenue by month and region, 2025.",
  "layout": { "columns": 12, "rowHeight": 72 },
  "datasets": {
    "monthly": {
      "file": "artifacts/revenue_monthly.csv",
      "source": { "kind": "sql", "connection": "warehouse", "sql": "select ..." }
    },
    "totals": { "rows": [ { "revenue": 1234567.8, "orders": 8123 } ] }
  },
  "filters": [],
  "charts": []
}
```

- `version` is always `1`.
- `datasets` keys match `^[a-z][a-z0-9_]{0,63}$`. Each dataset is
  `{ "file": "artifacts/x.csv" }`, `{ "file": "artifacts/x.tsv" }`,
  `{ "file": "artifacts/x.json" }`, or `{ "rows": [ ... ] }`. A file has a
  header row. A JSON file is an array of flat objects. Inline `rows` hold at
  most 5000 objects.
- Record `source: { "kind": "sql", "connection": "<name>", "sql": "<query>" }`
  on every dataset you produced with SQL. The renderer never runs it. It is
  kept so the dashboard can be refreshed later.
- Use ISO dates: `YYYY-MM-DD` or a full ISO datetime.
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
  "dataset": "monthly_region",
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

Filters live at the top level and bind to one dataset and one column. The
`default` is applied by the renderer and by the check tools.

| Type | `default` |
|---|---|
| `equals` | one scalar |
| `in` | array of scalars; empty means no filter |
| `date_range` | `{ "from": "2025-01-01", "to": "2025-12-31" }`, each optional |
| `number_range` | `{ "min": 0, "max": 100 }`, each optional |

```json
{ "id": "region", "label": "Region", "dataset": "monthly_region",
  "column": "region", "type": "in", "default": [] }
```

A filter applies to every chart on its dataset. Bind a filter to a dataset
that has the column.

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
| `dataset_unreadable` | chart fails | The file is missing or not parseable. Write the file again. Check the path starts with `artifacts/`. |
| `missing_column` | chart fails | Use a column from the listed columns, or add the column to the data. |
| `series_with_multi_y` | chart fails | Keep one y column with `series`, or remove `series`. |
| `empty_dataset` | warning | No rows after filters, sort, and limit. Check the filter defaults and the data. |
| `non_numeric_y` | warning | The y or value column has text. Write numbers, not formatted strings. |
| `unparseable_date` | warning | Write dates as `YYYY-MM-DD`, or set `x.type` to `category`. |
| `too_many_rows` | warning | More than 50000 rows. Aggregate or add a `limit`. |
| `unknown_chart` | tool only | The id is not in the file. Use one of the listed ids. |

`dashboard_screenshot` can return `"error": "renderer_unavailable"`. Then
rely on `dashboard_sample_data` and continue.

## Rules

- Aggregate before you write. The renderer does not aggregate.
- One finding per chart. Keep the series count at 8 or fewer and the
  category count at 24 or fewer.
- Sort time series by date in the data, and set `sort` on the chart.
- Keep the file small. Put large tables in files, not in inline `rows`.
- Do not write HTML dashboards. Do not draw dashboards with matplotlib.
- Never write into the dbt project. The file goes under `artifacts/`.

See `examples/revenue.dashboard.json` in this skill directory for a
complete valid file.
