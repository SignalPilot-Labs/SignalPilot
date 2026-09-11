Edit the dashboard "{{dashboard_name}}" (slug `{{dashboard_slug}}`, id `{{dashboard_id}}`).

Do these steps first:

1. Call `dashboard_load_published("{{dashboard_slug}}")`. It writes the dashboard file and the dataset snapshots at `artifacts/datasets/<name>.csv` into this chat. Its result gives the `path` of the dashboard file.
2. Run `dashboard_sample_data` on all charts to confirm the datasets load.

Then wait for my edit request. When I ask for a change, do these steps:

1. Edit the file that `dashboard_load_published` wrote. Do not write a second dashboard file.
2. If you change a dataset's SQL, call `sp.dashboard_dataset("<name>", connection="<connection>", sql="<sql>")` again with the new SQL. Put every derivation in the SQL. Do not transform rows in pandas.
3. Run `dashboard_sample_data` again.
4. Tell me what changed. Tell me to publish the new version from the chat panel.
