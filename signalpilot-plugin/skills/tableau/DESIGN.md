# Tableau dashboard design standard

Read this before you build or change a dashboard. A dashboard must be correct
AND easy to read. Good data on a poor page is a failed task.

## Use the design layer

Put `"theme": {"name": "sp"}` in the spec. Then use components, not raw
shelves:

| Kind | Use it for | Main keys |
|---|---|---|
| `card` | One headline number | `label`, `label_field`, `value`, `compare`, `secondary`, `note` |
| `combo` | Actual vs plan, this year vs last year | `x` (use `mname(date)`), `bar`, `line`, `label`, `colors`, `legend`, `marks`, `range` |
| `ranked_bars` | Rank people, products, regions | `category`, `value`, `color` |
| `status_bars` | Rank against a target with status colors | `category`, `value`, `bands` |
| `table` | Many measures per row (a scorecard) | `rows`, `columns`, `sort` |

For the dashboard, use `header`, `rows`, and `footer`. See
`examples/team_scorecard.spec.json` and `examples/ae_scorecard.spec.json`.
Copy them. They render correctly.

## Page structure

1. Header band: the title, a short purpose line, the main filter shown as
   text (`subtitle_param`), and the controls on the right.
2. One row of 4 to 6 cards with the headline numbers.
3. One or two rows of charts. Put the most important comparison first
   (vs plan, then vs last year).
4. A table when the user needs detail per person or per item.
5. A footer that defines every metric and names the data sources.

Use a width of 1600. Use card row height 150 to 160, chart rows 300 to 420.

## Rules

1. Match the depth of the original. When you rebuild a dashboard, keep every
   number the user saw. Make it cleaner, not smaller.
2. One accent color for actual values. Gray for last year or other context.
   Orange for plan. Green and red only for direction and status.
3. Every card shows the change against a comparison: `compare` with
   `previous`. Use `"unit": "points"` for rates. Add `secondary` for year to
   date.
4. Label the marks. The design layer hides value axes on combo and ranked
   charts, so each chart needs `label` (combo) or it shows its labels
   (ranked, status).
5. Titles are short sentences in sentence case. Put the legend in the title
   with `legend` (combo). Do not add a separate legend box.
6. Months: use `mname(date_field)`. It gives Jan to Dec, in order, horizontal.
   Show only the months that have data for "vs plan" (filter to year to date).
7. Rates: set `range` (for example `[0.2, 0.55]`) so the line uses the full
   height.
8. Tables: order the columns as the user reads them (value, change, plan,
   attainment, gap, then detail). Return NULL, not 0, when a value does not
   apply (for example no plan). The cell then stays blank.
9. Use one small data source per page when cards and charts must agree. A
   custom SQL rollup (one row per group and month) over the dbt models works
   well. Publish it with `tableau_publish_datasource` and `sql`. Do not use
   `WITH` (CTE) in custom SQL on SQL Server.
10. Keep business logic in dbt. Keep only period windows, ratios, and filters
    in Tableau calculations.

## Review every render

Render the dashboard with `tableau_view_image` after each publish. The tool
saves the PNG and returns its path. Open the PNG with the Read tool. Look at the
image. Fix each item and publish again:

- [ ] No `####` in a card. If you see it, make the row taller.
- [ ] No empty or blank panel. If a panel is blank, check its filters and data.
- [ ] No default blue bars where you set colors.
- [ ] No rotated or cut labels. No title that ends with "..".
- [ ] Every card has a change (▲ or ▼) and a comparison value.
- [ ] Numbers use the right format ($, %, pts). No 0.4 where you mean 40%.
- [ ] Columns in a table are in reading order.
- [ ] The numbers match your SQL check (rule 4 in SKILL.md).

Show the final image to the user. Say what you checked.
