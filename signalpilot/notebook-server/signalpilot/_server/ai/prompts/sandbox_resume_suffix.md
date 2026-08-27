## Resuming a chat: what persists, what doesn't

A conversation can resume in a fresh sandbox. If you resume shortly after your
last message the same sandbox is still warm and everything is exactly as you
left it. But after a period of inactivity that sandbox is torn down and rebuilt,
and the two layers are restored from durable storage:

- **The dbt project and its compiled metadata** — re-hydrated from source (the
  project's git/S3), so models and the compiled DAG are always present.
- **Your own analysis scripts and notebooks** — restored from this chat's store.

**Local data files are NOT restored.** On a rebuilt sandbox, anything you
generated locally is gone:

- DuckDB databases (`*.duckdb`), and any Parquet/CSV extracts you downloaded,
- dbt build artifacts under `target/` beyond the compiled manifest,
- extra packages you installed, and anything in `/tmp`.

Data materialized in the **warehouse** persists — a mart you refreshed into the
dev database is still there on resume. Only *local sandbox files* are cleared.

### Resume gracefully — never assume a local data file survived

- Before reading a local data file (e.g. a `.duckdb` you loaded an extract into),
  check that it exists. If it does not, **regenerate it** by re-running the step
  that produced it — re-extract from the warehouse, rebuild the local table.
- Write every script to be **idempotent and re-runnable**: running it again on a
  fresh sandbox must reproduce its own inputs, not error on a missing file.
- A missing extract or `.duckdb` after a resume is **expected, not a failure**.
  Recreate it and continue — do not report it as an error to the user.
- Prefer re-deriving from the warehouse (read-only) or from your persisted
  scripts over depending on a specific local file being present.
