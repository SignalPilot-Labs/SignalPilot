---
sidebar_position: 6
---

# Security

SignalPilot was designed to make AI database access safe by default.

## Governance

- **Read-only enforcement**: DDL and DML statements are blocked at the parse layer
- **Dangerous function denylist**: 79+ functions blocked across PostgreSQL, MySQL, SQLite, SQL Server, Snowflake, Databricks, and BigQuery
- **LIMIT injection**: Fail-closed -- if LIMIT can't be injected, the query is rejected
- **Multi-statement blocking**: Prevents SQL stacking attacks
- **INTO clause detection**: Blocks `SELECT INTO`, `COPY TO`, and similar exfiltration patterns

## Authentication

- **Clerk JWT** verification with JWKS rotation, clock leeway, and required claims
- **API keys** with AES-GCM encryption at rest, org-scoped, with brute-force rate limiting (60/min/IP)
- **Org role enforcement**: Admin-only endpoints require `org:admin` role

## Network

- **SSRF protection**: Cloud warehouse connection parameters validated against allowed domains (Snowflake, Databricks, BigQuery)
- **DNS rebinding defense**: Hostnames resolved and validated before connection
- **Non-root containers**: Gateway and backend run as UID 10001

## Audit

- **Every query logged** with timestamp, org, user, connection, and SQL
- **PII redaction**: SQL string literals replaced with `'***'` in audit logs
- **Query cost estimation** before execution

## Encryption

- **AES-GCM** for credential storage (connection passwords, API key secrets)
- **Legacy SHA-256** gated behind `SP_ALLOW_LEGACY_CRYPTO` flag (disabled by default)
