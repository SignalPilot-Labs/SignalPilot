Edit the dashboard "{{dashboard_name}}".

The current dashboard spec is below. Do these steps first:

1. Write the spec to `{{dashboard_path}}` exactly as given.
2. For each SQL dataset in `datasets`, call `sp.dashboard_dataset("<name>", connection="<connection>", sql="<sql>")` in the notebook with the values from the spec. This writes the snapshot at `artifacts/datasets/<name>.csv`. Do not write these files by hand.
3. Run `dashboard_sample_data` on all charts to confirm the datasets load.

Then wait for my edit request. When I ask for a change, do these steps:

1. Update the spec. When a dataset changes, change its `sql` and call `sp.dashboard_dataset` again with the new SQL. Put every derivation in the SQL. Do not transform rows in pandas.
2. Run `dashboard_sample_data` again.
3. Tell me what changed.

SQL datasets:

{{dataset_list}}

Dashboard spec:

```json
{{spec_json}}
```
