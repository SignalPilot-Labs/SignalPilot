Refresh the published dashboard "{{dashboard_name}}".

This is a scheduled data refresh. Do not change the dashboard design.

Do these steps in order:

1. For each SQL dataset listed below, call `sp.dashboard_dataset("<name>", connection="<connection>", sql="<sql>")` in the notebook with the exact `connection` and `sql` from the spec. This runs the query and writes the snapshot at `artifacts/datasets/<name>.csv`. Do not write these files by hand. Do not change the SQL.
2. Datasets with `rows` are static. Do not touch them.
3. Write the dashboard file again, unchanged, to `{{dashboard_path}}`.
4. Run `dashboard_sample_data` on all charts of `{{dashboard_path}}`. Do not change chart ids. Do not change the spec.
5. Reply with one short line per dataset: the dataset name and its row count.

SQL datasets:

{{dataset_list}}

Full dashboard spec:

```json
{{spec_json}}
```
