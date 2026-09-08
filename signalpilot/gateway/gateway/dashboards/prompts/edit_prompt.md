Edit the dashboard "{{dashboard_name}}".

The current dashboard spec and its datasets are below. Do these steps first:

1. Write the spec to `{{dashboard_path}}` exactly as given.
2. Write each dataset to the path in its `file` field exactly as given.
3. Run `dashboard_sample_data` on all charts to confirm the files load.

Then wait for my edit request. When I ask for a change, do these steps:

1. Update the spec and the datasets.
2. Run `dashboard_sample_data` again.
3. Tell me what changed.

Dashboard spec:

```json
{{spec_json}}
```

{{dataset_blocks}}
