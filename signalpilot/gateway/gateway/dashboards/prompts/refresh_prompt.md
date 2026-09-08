Refresh the published dashboard "{{dashboard_name}}".

This is a scheduled data refresh. Do not change the dashboard design.

Do these steps in order:

1. Reproduce every dataset that has a `source`. Run the SQL in `source.sql` on the connection in `source.connection`. Write the rows to the same path in `datasets.<name>.file`. Keep the same columns and the same column names. Use the same file type (csv, tsv, or json).
2. Do not touch datasets without a `source`. They are static snapshots.
3. Write the dashboard file again, unchanged, to `{{dashboard_path}}`.
4. Run `dashboard_sample_data` on all charts of `{{dashboard_path}}`. Fix a dataset only when a chart reports `missing_column` or `empty_dataset`. Do not change chart ids. Do not change the spec.
5. Reply with one short line per dataset: the dataset name and its row count.

Datasets with a `source`:

{{dataset_list}}

Full dashboard spec:

```json
{{spec_json}}
```
