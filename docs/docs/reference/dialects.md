---
sidebar_position: 7
---

# Dialect Support Matrix

SignalPilot supports 7 SQL dialects across three tiers.

## Tier overview

| Tier | Connectors | Query | Schema | Cost estimate | EXPLAIN | FK discovery | Schema stats |
|------|-----------|-------|--------|---------------|---------|-------------|-------------|
| **1** | PostgreSQL, DuckDB, Snowflake, BigQuery | Full | Full | Yes | Yes | Yes | Yes |
| **2** | MySQL, SQLite, SQL Server | Full | Full | Limited | Yes | Yes | Partial |
| **3** | Databricks | Full | Partial | No | Basic | Limited | No |

## Per-dialect details

### PostgreSQL (Tier 1)

- Full schema introspection via `information_schema` and `pg_catalog`
- FK discovery via `pg_constraint`
- `EXPLAIN (ANALYZE, BUFFERS)` for execution plans
- No cost estimation (row-based billing, not byte-based)
- Dangerous functions blocked: `pg_read_file`, `pg_read_binary_file`, `pg_ls_dir`, `lo_import`, `lo_export`, `dblink`
- Plugin skill: use `sql-workflow` for query patterns

### DuckDB (Tier 1)

- Full schema introspection via `information_schema`
- FK discovery supported
- EXPLAIN supported
- No cost estimation
- Dangerous functions blocked: `read_csv`, `read_parquet`, `read_json`, `httpfs` extensions
- Gotchas: integer division truncates, `INTERVAL` syntax requires quotes, `DATE_TRUNC` returns TIMESTAMP
- Plugin skill: `duckdb-sql` — covers all major DuckDB-specific patterns

### Snowflake (Tier 1)

- Full schema introspection via `INFORMATION_SCHEMA`
- FK discovery via `SHOW PRIMARY KEYS` / `SHOW IMPORTED KEYS`
- `EXPLAIN` supported (estimated cost, not actual)
- Cost estimation: estimated credits based on bytes scanned
- No dangerous functions blocked (Snowflake's sandbox model handles this)
- LIMIT injection uses `LIMIT n` syntax
- Plugin skill: `snowflake-sql` — QUALIFY, LATERAL FLATTEN, VARIANT

### BigQuery (Tier 1)

- Full schema introspection via `INFORMATION_SCHEMA`
- FK discovery limited (BigQuery doesn't enforce FKs at write time)
- Cost estimation: **exact bytes billed** via dry-run (`estimate_query_cost` is highly accurate)
- EXPLAIN returns query plan with byte estimates per stage
- Table references require backtick quoting: `` `project.dataset.table` ``
- Plugin skill: `bigquery-sql` — UNNEST, STRUCT, EXCEPT/REPLACE, partitioned tables

### MySQL (Tier 2)

- Schema introspection via `information_schema`
- FK discovery via `KEY_COLUMN_USAGE`
- EXPLAIN supported
- No byte-based cost estimation
- Dangerous functions blocked: `LOAD_FILE`, `INTO OUTFILE`, `INTO DUMPFILE`, `LOAD DATA INFILE`
- No `FULL OUTER JOIN` (use `UNION` of LEFT and RIGHT)
- Plugin skill: use `sql-workflow` for general patterns

### SQLite (Tier 2)

- Schema introspection via `sqlite_master`
- FK discovery via `PRAGMA foreign_key_list`
- No cost estimation
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
- Dangerous functions blocked: `xp_cmdshell`, `xp_fileexist`, `xp_readfile`, `sp_OACreate`, `OPENROWSET`, `BULK INSERT`
- LIMIT injection uses `SELECT TOP n` (not `LIMIT n`)
- Plugin skill: use `sql-workflow` for general patterns

### Databricks (Tier 3)

- Schema introspection via `information_schema`
- Limited FK discovery (Delta tables don't enforce FKs)
- Basic EXPLAIN support
- No cost estimation
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
| PostgreSQL, MySQL, SQL Server, Databricks | `sql-workflow` |
