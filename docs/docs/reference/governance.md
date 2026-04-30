---
sidebar_position: 6
---

# Governance Reference

Authoritative reference for SignalPilot's SQL governance rules. All rules apply at parse time — before any query reaches the database.

## DDL block list

The following statement types are blocked regardless of dialect:

```
CREATE    DROP    ALTER    TRUNCATE    RENAME
```

If a query contains any of these at the top level or inside a subquery, it is rejected with a governance error.

## DML block list

```
INSERT    UPDATE    DELETE    MERGE    UPSERT    REPLACE
```

SignalPilot enforces read-only access. No data-modification statements are allowed.

## LIMIT injection

Every `SELECT` statement gets a `LIMIT` appended if one is not already present. The `query_database` tool accepts a `row_limit` parameter (default `1000`, max `10000`). If the query already contains a `LIMIT` that exceeds `row_limit`, it is clamped down.

The underlying limit is not configurable via an environment variable — it is controlled per-call by the `row_limit` tool parameter.

**Fail-closed behavior:** If the governance engine cannot inject a LIMIT (e.g. the query structure prevents safe injection), the query is rejected — not executed without a limit.

**Dialect support:** LIMIT injection is implemented for all supported dialects. Snowflake and BigQuery use `LIMIT n`; SQL Server uses `TOP n` in the outer query.

## INTO clause blocking

`SELECT INTO`, `INSERT INTO ... SELECT`, and `COPY TO` patterns are detected and blocked. This prevents data exfiltration to local files or other tables.

## Multi-statement blocking

Queries containing multiple statements (`;` separator) are rejected. This prevents SQL stacking attacks (e.g. `SELECT 1; DROP TABLE users`).

## Dangerous function denylist

79+ functions are blocked across 7 SQL dialects. These are functions that can read files, execute OS commands, make network calls, or access sensitive system information.

**Examples by dialect:**

| Dialect | Blocked functions (examples) |
|---------|------------------------------|
| PostgreSQL | `pg_read_file`, `pg_read_binary_file`, `pg_ls_dir`, `lo_import`, `lo_export`, `copy_to`, `dblink` |
| MySQL | `LOAD_FILE`, `INTO OUTFILE`, `INTO DUMPFILE`, `LOAD DATA INFILE` |
| SQL Server | `xp_cmdshell`, `xp_fileexist`, `xp_readfile`, `sp_OACreate`, `OPENROWSET`, `BULK INSERT` |
| Snowflake | `SYSTEM$PIPE_STATUS`, file staging functions |
| BigQuery | External table reads from unauthorized sources |
| DuckDB | `read_csv`, `read_parquet`, `read_json`, `httpfs` extension functions |
| SQLite | N/A (no filesystem functions exposed via MCP) |

The full denylist is maintained in `signalpilot/gateway/engine/` in the gateway source.

## Per-session budget cap

Budget caps are set per session via the `start_session` MCP tool. A session without a registered budget has no spending limit.

Queries that would exceed the session's budget are rejected before execution. The `check_budget` tool returns the remaining budget.

Applies to: BigQuery (exact bytes billed), Snowflake (estimated credits). PostgreSQL, MySQL, SQLite, DuckDB: no cost accounting (all queries allowed regardless of budget).

There is no global default budget env var — each session specifies its own cap.

## Audit log

Every query is logged with:

- Timestamp (UTC)
- Org ID and user ID
- Connection name and database type
- SQL text (string literals PII-redacted: replaced with `<REDACTED>`)
- Governance decisions applied (LIMIT injected, functions blocked, etc.)
- Cost estimate (if applicable)
- Row count returned

Audit records are append-only and stored in the gateway's SQLite database by default. The audit log is always enabled; there is no env toggle.

## Authentication and rate limiting

- **`SP_PER_KEY_RPM`** — MCP tool calls per minute per API key (default `1000`)
- **`SP_PER_ORG_RPM`** — MCP tool calls per minute per org in cloud mode (default `5000`)
- **`SP_JWT_LEEWAY`** — clock leeway in seconds for JWT verification (default `30`)
- Auth failure rate limiting is hardcoded at the gateway level; there is no env override for this.

## Tenant isolation

In multi-tenant (cloud) mode, every API key is scoped to an org. A key can only access connections registered by that org. Cross-org access is blocked at the data layer.

Enable cloud mode with `SP_DEPLOYMENT_MODE=cloud`.

## Encryption

- **AES-GCM** — connection passwords and API key secrets encrypted at rest using `SP_ENCRYPTION_KEY` and `SP_ENCRYPTION_SALT`
- **Legacy SHA-256** — gated behind `SP_ALLOW_LEGACY_CRYPTO=true` (disabled by default, for migration windows only)
- **BYOK** — available on Pro/Team/Enterprise plans via `SP_BYOK_PROVIDER` and `SP_BYOK_PROVIDER_CONFIG`

## Non-root containers

The gateway and backend run as UID 10001. The container has no write access to the host filesystem.

## SSRF protection

TCP-based database connections (PostgreSQL, MySQL, SQL Server, Redshift, ClickHouse, Trino) are validated against SSRF rules in cloud mode (`SP_DEPLOYMENT_MODE=cloud`):

- Hostnames are resolved to IP addresses before the connection is opened (eliminates DNS rebinding TOCTOU)
- Loopback (`127.0.0.0/8`, `::1`) and link-local (`169.254.0.0/16`, `fe80::/10`) addresses are always blocked
- RFC1918 private ranges are blocked unless `SP_ALLOW_PRIVATE_CONNECTIONS=true`
- DNS resolution failure is treated as rejection (fail-closed)

Cloud warehouse connectors (Snowflake, BigQuery, Databricks) skip the TCP/DNS check and instead validate the format of user-supplied identifiers (account slug, host, project ID) against known-valid patterns.

In local mode (`SP_DEPLOYMENT_MODE=local` or unset), SSRF validation is disabled — private network addresses are expected.
