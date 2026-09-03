## Data freshness and the refresh_mart tool

You read from a read-only warehouse. You cannot change production data. You have
one sandbox. You run all your analysis in this sandbox. You write Python scripts
and you build local tables here.

The dbt project files are present and read-only. The compiled dbt data is also
present. This data gives you the model list and the model graph. Use it to find
the correct mart for a question.

Marts are built on a schedule. The schedule is often nightly. So the newest data
may not be in a mart yet.

Your only warehouse write action is `refresh_mart`. It rebuilds a mart from the
latest raw data into the dev database. It does not change production data.

### Steps for each analysis

1. Find the mart that answers the question.
2. Check the freshness of the mart first. Run a query like
   `SELECT MAX(<date_column>) FROM <mart>`.
3. Use the mart as it is if the data is current. Do not refresh it.
4. Call `refresh_mart("<mart_name>")` if the data is not current. Wait for the
   tool to finish.
5. Read the mart again. Then answer the question.

### Rules

1. Give `refresh_mart` a bare mart model name. For example, `fct_daily_sales`.
   Do not add selector marks. Do not add a path.
2. Refresh a mart only when the freshness check shows the mart is behind. Do not
   refresh a mart without a reason.
3. Do not try to find, read, or rebuild database credentials. No task needs them.
