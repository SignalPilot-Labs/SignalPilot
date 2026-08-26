---
sidebar_position: 7
---

# Dialect Support Matrix

SignalPilot supports 11 SQL dialects across three tiers.

## Tier overview

| Tier | Connectors | Query | Schema | Cost estimate | EXPLAIN | FK discovery | Schema stats |
|------|-----------|-------|--------|---------------|---------|-------------|-------------|
| **1 — Full Support** | PostgreSQL, MySQL, Snowflake, BigQuery | Full | Full | Yes | Yes | Yes (except BigQuery) | Yes (PostgreSQL, MySQL) |
| **2 — Stable** | Redshift, ClickHouse, Databricks, SQL Server, Trino | Full | Full | Yes | Yes | Yes (except ClickHouse) | Yes (Redshift, ClickHouse, SQL Server) |
| **3 — Basic** | DuckDB, SQLite | Full | Full | No | Yes | Yes | No |

## Per-dialect details

### PostgreSQL (Tier 1)

- Full schema introspection via `information_schema` and `pg_catalog`
- FK discovery via `pg_constraint`
- `EXPLAIN (ANALYZE, BUFFERS)` for execution plans
- Cost estimation supported (planner-based, from `EXPLAIN`)
- Dangerous functions blocked: file-system access (`pg_read_file`, `pg_read_binary_file`, `pg_ls_dir`, `pg_file_write`), large-object smuggling (`lo_import`, `lo_export`), out-of-band connections (`dblink` family), OS command execution (`pg_execute_server_program`), server management (`pg_terminate_backend`, `pg_reload_conf`), and `set_config`
- Plugin skill: use `sql-workflow` for query patterns

### DuckDB (Tier 3)

- Full schema introspection via `information_schema`
- FK discovery supported
- EXPLAIN supported
- No cost estimation
- Dangerous functions blocked: file-system reads (`read_csv`, `read_csv_auto`, `read_parquet`, `read_json`, `read_json_auto`, `read_blob`, `read_text`), network access (`httpfs_get`, `http_get`, `http_post`), cross-engine scanning (`postgres_scan`, `sqlite_scan`, `mysql_scan`, `iceberg_scan`, `delta_scan`), and extension loading (`load_extension`, `install_extension`)
- Gotchas: integer division truncates, `INTERVAL` syntax requires quotes, `DATE_TRUNC` returns TIMESTAMP
- Plugin skill: `duckdb-sql` — covers all major DuckDB-specific patterns

### Snowflake (Tier 1)

- Full schema introspection via `INFORMATION_SCHEMA`
- FK discovery via `SHOW PRIMARY KEYS` / `SHOW IMPORTED KEYS`
- `EXPLAIN` supported (estimated cost, not actual)
- Cost estimation: estimated credits based on bytes scanned
- Dangerous functions blocked: `system$execute_program`, `system$stream_get`, `system$pipe_force_resume`, `system$cancel_all_queries`
- LIMIT injection uses `LIMIT n` syntax
- Plugin skill: `snowflake-sql` — QUALIFY, LATERAL FLATTEN, VARIANT

### BigQuery (Tier 1)

- Full schema introspection via `INFORMATION_SCHEMA`
- No FK discovery (BigQuery doesn't enforce FKs at write time)
- Cost estimation: **exact bytes billed** via dry-run (`estimate_query_cost` is highly accurate)
- EXPLAIN returns query plan with byte estimates per stage
- Dangerous functions blocked: `external_query`
- Table references require backtick quoting: `` `project.dataset.table` ``
- Plugin skill: `bigquery-sql` — UNNEST, STRUCT, EXCEPT/REPLACE, partitioned tables

### Amazon Redshift (Tier 2)

- PostgreSQL wire protocol (psycopg2); supports provisioned clusters and Redshift Serverless
- Full schema introspection via `pg_table_def`, `svv_table_info`, `pg_stats`, and `pg_description` (column/table comments)
- FK discovery via `pg_constraint`
- EXPLAIN supported; sessions run read-only with `autocommit`
- No byte-based cost estimation (row-based billing)
- Surfaces Redshift-specific metadata: `diststyle`, sort keys, column encodings, distribution keys, estimated row counts
- IAM auth supported (temporary credentials via `GetClusterCredentials` / Serverless `GetCredentials`); IAM auth forces SSL
- Gotchas: column statistics come from `pg_stats` (`n_distinct`), so they reflect the last `ANALYZE`
- Plugin skill: use `sql-workflow` for query patterns

### MySQL (Tier 1)

- Schema introspection via `information_schema`
- FK discovery via `KEY_COLUMN_USAGE`
- EXPLAIN supported
- Cost estimation supported (planner-based, from `EXPLAIN`)
- Dangerous functions blocked: `load_file`, `sys_exec`, `sys_eval` (plus `SELECT ... INTO OUTFILE` / `INTO DUMPFILE` rejected by the `INTO`-clause check)
- No `FULL OUTER JOIN` (use `UNION` of LEFT and RIGHT)
- Plugin skill: use `sql-workflow` for general patterns

### SQLite (Tier 3)

- Schema introspection via `sqlite_master`
- FK discovery via `PRAGMA foreign_key_list`
- No cost estimation
- Dangerous functions blocked: `load_extension`, `readfile`, `writefile`, `edit`, `zipfile`, `sqlar`
- No `FULL OUTER JOIN`
- No `ILIKE` (use `LIKE` with `LOWER()`)
- No `SPLIT_PART` or `POSITION` (use `substr`/`instr`)
- String concatenation: `||` operator
- Plugin skill: `sqlite-sql` — covers all major SQLite-specific patterns

### SQL Server / MSSQL (Tier 2)

- Schema introspection via `INFORMATION_SCHEMA` and `sys` catalog
- FK discovery via `sys.foreign_keys`
- EXPLAIN via `SET STATISTICS IO ON`
- No byte-based cost estimation
- No dialect-specific dangerous-function denylist; all DDL/DML, statement stacking, and the universal `load_extension` / `install_extension` are blocked
- LIMIT injection uses `SELECT TOP n` (not `LIMIT n`)
- Plugin skill: use `sql-workflow` for general patterns

### ClickHouse (Tier 2)

- Native TCP first (ports 9000 / 9440 TLS) with automatic fallback to HTTP (ports 8123 / 8443 TLS); `protocol` forces `native` or `http`
- Schema introspection via `system.columns`, `system.tables`, and `system.parts_columns`
- No FK discovery (ClickHouse does not have foreign keys)
- No byte-based cost estimation
- Dangerous table functions blocked: `file`, `url`, `s3`, `s3cluster`, `mysql`, `postgresql`, `remote`, `remotesecure`, `hdfs`, `jdbc`, `mongo`, `redis`, `sqlite`, `odbc`, `input`, `generaterandom`, `executable`, `azureblobstorage`, `deltalake`, `hudi`, `iceberg`
- Surfaces table engine, sorting key, primary key, row counts, and compressed/uncompressed column sizes
- Identifier quoting uses backticks (`` ` ``)
- Gotchas: `Nullable(...)` and `LowCardinality(...)` type wrappers are unwrapped during introspection; nullability is derived from the `Nullable` wrapper
- Plugin skill: use `sql-workflow` for general patterns

### Trino (Tier 2)

- Federated SQL across catalogs (formerly PrestoSQL); used by Starburst and similar platforms
- Schema introspection via `information_schema` batch queries, with a `SHOW SCHEMAS` / `SHOW TABLES` / `SHOW COLUMNS` fallback for catalogs that don't expose it
- FK and PK discovery via `table_constraints` / `key_column_usage` (best-effort — not all connectors expose constraints)
- Row counts via `SHOW STATS` (best-effort, capped at 50 tables per introspection)
- No byte-based cost estimation
- No dialect-specific dangerous-function denylist; all DDL/DML, statement stacking, and the universal `load_extension` / `install_extension` are blocked
- Identifier quoting uses double quotes; query timeout enforced via `SET SESSION query_max_run_time`
- Auth methods: password (Basic), JWT, certificate, Kerberos; any auth other than none forces HTTPS
- Gotchas: introspection scope depends on the configured `catalog`; without one, all non-`system` catalogs are scanned
- Plugin skill: use `sql-workflow` for general patterns

### Databricks (Tier 2)

- Schema introspection via `information_schema` and Unity Catalog
- FK discovery supported (declared constraints; Delta tables don't enforce FKs at write time)
- EXPLAIN supported
- No row counts (not surfaced by the connector)
- Cost estimation supported (planner-based, from `EXPLAIN`)
- No dialect-specific dangerous-function denylist; all DDL/DML, statement stacking, and the universal `load_extension` / `install_extension` are blocked
- Plugin skill: use `sql-workflow` for general patterns

## Dialect detection

SignalPilot detects the dialect from the connection's `db_type` field. You can check the detected dialect and feature tier with `connector_capabilities`.

## Cross-dialect skill mapping

| Dialect | Recommended skill |
|---------|-----------------|
| DuckDB | `duckdb-sql` |
| Snowflake | `snowflake-sql` |
| BigQuery | `bigquery-sql` |
| SQLite | `sqlite-sql` |
| PostgreSQL, Redshift, MySQL, SQL Server, ClickHouse, Trino, Databricks | `sql-workflow` |
