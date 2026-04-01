# SignalPilot Database Connectors — Improvements Log

## Overview
Major overhaul of database connectors to match HEX-level flexibility and optimize for Spider2.0 benchmarks.

---

## Round 2: SSH Tunnels, Index Metadata, Schema Compression (2026-04-01)

### 1. SSH Tunnel Support (sshtunnel library)

**What:** Full SSH tunnel implementation for bastion-host connections — the most-requested enterprise feature.

**Implementation:**
- `SSHTunnel` class wrapping `sshtunnel.SSHTunnelForwarder`
- Supports password and private key auth (RSA, Ed25519, ECDSA)
- Auto-selects a free local port for tunnel binding
- 60-second keepalive interval (industry standard)
- Lifecycle-managed alongside connector pools in `PoolManager`
- Connection string automatically rewritten to route through tunnel
- Supported DB types: Postgres, MySQL, Redshift, ClickHouse

**Architecture pattern:** On-demand SSH sessions (matches HEX pattern) — each pool manager entry gets its own tunnel, cleaned up on idle timeout or close.

### 2. Index Metadata in Schema

**Before:** No index information in schema output.

**After:** Full index metadata for query planning:

| Database | Index Info Available |
|----------|-------------------|
| PostgreSQL | Index name + DDL definition from `pg_indexes` |
| MySQL | Index name + columns + uniqueness from `STATISTICS` |
| ClickHouse | Engine type + sorting key + primary key from `system.tables` |
| DuckDB | Foreign keys from `information_schema` |
| SQLite | Foreign keys via `PRAGMA foreign_key_list` |

**Spider2.0 impact:** Index metadata helps the agent understand access patterns. For example, knowing a table has a btree index on `(customer_id, created_at)` tells the agent to use those columns in WHERE clauses and ORDER BY, avoiding full table scans.

### 3. Schema Compression for LLM Context Windows

**What:** `compact=true` query parameter on `/api/connections/{name}/schema` returns compressed DDL-style schema.

**Compression results on enterprise_prod (10 tables, 136 columns, 43 indexes, 10 FKs):**
- Full schema: 25,264 bytes
- Compact schema: 6,476 bytes
- **75% reduction** in token count

**Compact format per table:**
```json
{
  "ddl": "CREATE TABLE public.orders (\n  id integer NOT NULL, user_id integer NOT NULL, amount numeric\n  PRIMARY KEY (id)\n)",
  "row_count": 50000,
  "foreign_keys": ["user_id -> public.users.id"],
  "indexes": ["orders_pkey"]
}
```

**Spider2.0 impact:** Top performers (LinkAlign, Paytm Prism) use table compression for schemas >50K tokens. This is especially critical for Spider2.0-Snow tasks where Snowflake schemas can have 100+ tables with 20+ columns each.

### 4. Two-Phase Connection Testing

**Before:** Single-phase test — connect and health check.

**After:** Industry-standard two-phase pattern (matches HEX/DBeaver):
1. **Phase 1 (SSH Tunnel):** Verify tunnel configuration and connectivity
2. **Phase 2 (Database):** Authenticate and run test query

**Response format:**
```json
{
  "status": "healthy",
  "phases": [
    {"phase": "ssh_tunnel", "status": "ok", "message": "...", "duration_ms": 45.2},
    {"phase": "database", "status": "ok", "message": "...", "duration_ms": 22.6}
  ],
  "total_duration_ms": 67.8
}
```

This makes debugging connection issues much easier — users can see exactly which phase failed.

### 5. ClickHouse Enhanced Metadata

**Before:** Only columns from `system.columns`.

**After:** Added table-level metadata from `system.tables`:
- `engine` (MergeTree, ReplacingMergeTree, etc.)
- `sorting_key` (the columns data is sorted by on disk)
- `row_count` (exact count from `total_rows`)
- `total_bytes` (storage size)

This is critical for ClickHouse query optimization — the sorting key determines which queries can use primary key index scans vs full scans.

---

## Round 1: Connector Expansion & HEX-Style UX (2026-04-01)

### 1. Expanded Database Support (5 → 9 connectors)

| Database | Status | Library | Connection Modes | Spider2.0 Relevance |
|----------|--------|---------|-----------------|---------------------|
| PostgreSQL | **Enhanced** | asyncpg | Host/port, URL | Core — most benchmarks |
| MySQL | **New** | pymysql | Host/port, URL | Spider2.0-Lite |
| Snowflake | **New** | snowflake-connector-python | Account/warehouse/role | Spider2.0-Snow (547 tasks) |
| BigQuery | **New** | google-cloud-bigquery | Project/dataset + service account JSON | Spider2.0-Lite |
| Redshift | **New** | psycopg2-binary | Host/port, URL | AWS enterprise workloads |
| ClickHouse | **New** | clickhouse-driver | Host/port, URL (native TCP) | OLAP benchmarks |
| Databricks | **New** | databricks-sql-connector | Server hostname + HTTP path + PAT | Spider2.0-DBT (68 tasks) |
| DuckDB | Existing | duckdb | File path / :memory: / MotherDuck | Spider2.0-DBT |
| SQLite | **Promoted** | sqlite3 (stdlib) | File path / :memory: | Spider2.0-Lite |

### 2. HEX-Style Connection UX

**Before:** Generic form with host/port/database/username/password for all DB types.

**After:** DB-specific forms that match HEX's connector UI:
- **Visual DB type selector** with icons for all 9 database types
- **Connection string vs. individual fields** toggle (like HEX)
- **DB-specific fields:**
  - Snowflake: account identifier, warehouse, role, default schema
  - BigQuery: GCP project ID, dataset, service account JSON textarea
  - Databricks: server hostname, HTTP path, access token, Unity Catalog
  - DuckDB/SQLite: simplified path-only form
- **SSL/TLS configuration** (collapsible section):
  - SSL mode selector (require, verify-ca, verify-full)
  - CA certificate, client certificate, client key (PEM textareas)
- **SSH tunnel configuration** (collapsible section):
  - Bastion host/port, username
  - Password or private key authentication
  - Key passphrase support
- **Save & Test** workflow button

### 3. Enhanced Schema Pulling (Spider2.0 Optimization)

**Before:** Basic columns + primary keys only.

**After:** Rich metadata critical for AI agent join path discovery:

| Metadata | PostgreSQL | MySQL | Snowflake | ClickHouse | DuckDB | SQLite |
|----------|-----------|-------|-----------|------------|--------|--------|
| Columns + types | Yes | Yes | Yes | Yes | Yes | Yes |
| Primary keys | Yes | Yes | Best-effort | Yes | N/A | N/A |
| **Foreign keys** | **Yes** | **Yes** | N/A | N/A | **Yes** | **Yes** |
| **Row count estimates** | **Yes** | **Yes** | N/A | **Yes** | N/A | **Yes** |
| **Indexes** | **Yes** | **Yes** | N/A | **Engine/sort key** | N/A | N/A |
| **Table comments** | **Yes** | **Yes** | Yes | Yes | N/A | N/A |
| **Column comments** | **Yes** | **Yes** | Yes | Yes | N/A | N/A |

**Performance optimization:** PostgreSQL schema pulling now uses `asyncio.gather` with separate pool connections to fetch columns, foreign keys, row counts, and indexes concurrently (4 parallel queries).

**Spider2.0 impact:** Foreign key metadata is the #1 predictor of join accuracy in text-to-SQL benchmarks. Schema linking errors cause 27.6% of SQL failures (EDBT 2026).

### 4. Cost Estimation for All DB Types

| Database | Method | Cost Model |
|----------|--------|------------|
| PostgreSQL | EXPLAIN (FORMAT JSON) | $0.0000003/row (RDS baseline) |
| MySQL | EXPLAIN FORMAT=JSON | $0.0000003/row |
| Snowflake | EXPLAIN USING TEXT | $0.000001/row (credit-based) |
| BigQuery | **dry_run** (exact bytes) | $5/TB scanned |
| Redshift | EXPLAIN (text parsing) | $0.0000005/row |
| ClickHouse | EXPLAIN ESTIMATE | $0.0000001/row (efficient columnar) |
| Databricks | EXPLAIN (heuristic) | $0.000001/row |
| DuckDB/SQLite | EXPLAIN | $0 (local/free) |

### 5. Security Improvements

- Error sanitization expanded to cover all new connection string formats
- Access token and private key patterns added to sensitive data redaction
- Credential extras stored in-memory only (never persisted to disk)
- SSH tunnel credentials stripped from persistent connection info
- BigQuery service account JSON stored only in credential vault

### 6. Testing

- **25 new integration tests** covering all connector types
- **Live tests verified:** PostgreSQL 17, MySQL 8.0, ClickHouse 26.3, DuckDB, SQLite
- **All 132 tests passing**

---

## Architecture Notes

### One-Size-Fits-All Approach
Where possible, connectors use `information_schema` for metadata (Postgres, MySQL, DuckDB all support it). This means the schema representation is consistent across databases, which is critical for the Spider2.0 agent to work with any backend.

### Connector Interface
All connectors implement the same `BaseConnector` abstract class:
- `connect(connection_string)` — open connection
- `execute(sql, params, timeout)` — run query, return `list[dict]`
- `get_schema()` — return full schema metadata
- `health_check()` — verify connectivity
- `close()` — cleanup resources

### Pool Manager
The `PoolManager` singleton reuses connectors across requests with:
- Health-check-on-acquire pattern
- Idle timeout cleanup (300s)
- SSH tunnel lifecycle management
- Support for `credential_extras` for connectors needing structured auth

### Schema Compression Pipeline
```
Full Schema (25KB) → _compress_schema() → DDL-style (6KB, 75% smaller)
                                          ↓
                                  Preserves: FKs, PKs, indexes,
                                  row counts, comments
                                          ↓
                                  Optimal for LLM context windows
```

---

## Industry Standards Compliance (April 2026 Research)

### Comparison with HEX
| Feature | HEX | SignalPilot |
|---------|-----|-------------|
| DB type count | 15+ | 9 (covering all Spider2.0 DBs) |
| SSH tunnels | On-demand sessions | On-demand sessions (sshtunnel) |
| SSL/TLS modes | Full (disable→verify-full) | Full (disable→verify-full) |
| Two-phase test | Yes | Yes |
| IP allowlisting | Static IPs | Not needed (self-hosted) |
| OAuth | Some DBs | Planned |
| Connection string mode | Yes | Yes |
| Schema caching | Yes | Yes (with TTL) |
| Schema compression | N/A | Yes (compact mode for AI agents) |

### Spider2.0 Leaderboard Context
- **Genloop Sentinel:** 96.7% (Snow) — multi-agent swarm, table compression
- **Paytm Prism:** 82.63% (Snow) — multi-agent swarm architecture
- **LinkAlign:** 33.09% (Lite, open-source only) — semantic retrieval, approximate string matching
- **Key insight (EDBT 2026):** Schema linking errors cause 27.6% of SQL failures → our FK + index metadata directly addresses this

---

## Next Steps
- [ ] Encrypt credentials at rest (AES-256-GCM)
- [ ] OAuth support for Snowflake, BigQuery, Databricks
- [ ] Schema diff detection (track changes over time)
- [ ] Automated schema refresh scheduling (like HEX workspace connections)
- [ ] Sample value extraction for column linking (reduces schema linking errors by ~15%)
- [ ] Multi-round semantic retrieval for irrelevant table filtering
- [ ] Approximate string matching (threshold 0.5) for column name hallucination correction
