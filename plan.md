# Cloud Readiness Plan

## Features to Disable in Cloud Mode (`SP_DEPLOYMENT_MODE=cloud`)

These features must be completely hidden in the UI and their API endpoints must not be registered when running in cloud mode. No way to activate them.

| # | Feature | Component | Why |
|---|---------|-----------|-----|
| 1 | Sandbox service (gVisor) | `sp-sandbox` container | Requires SYS_ADMIN/SYS_PTRACE, 512MB+ per container |
| 2 | `execute_code` MCP tool | `mcp_server.py` | Depends on sandbox |
| 3 | File browser (`/files/browse`) | `api/files.py` | Browses host filesystem |
| 4 | File-based DuckDB connections | `connectors/sandboxed_duckdb.py` | Requires host FS + sandbox |
| 5 | File-based SQLite connections | `connectors/sandboxed_sqlite.py` | Requires host FS + sandbox |
| 6 | dbt project creation (new) | `api/projects.py` | Writes to DATA_DIR/projects/ |
| 7 | dbt project creation (local) | `api/projects.py` | Reads from user local path |
| 8 | dbt project scan | `api/projects.py` | Reads filesystem |
| 9 | dbt project validate | `dbt/validator.py` | Runs dbt subprocess on filesystem |
| 10 | dbt project map | `mcp_server.py` | Reads filesystem |
| 11 | Local BYOK provider | `byok.py` | Writes key files to DATA_DIR |
| 12 | Auto-generated encryption key | `store.py` | Writes .encryption_key to DATA_DIR |
| 13 | YAML-based annotations | `governance/annotations.py` | Reads from ~/.signalpilot/ |
| 14 | Local API key file | `store.py` | Writes DATA_DIR/local_api_key |
| 15 | `LocalDBFilePicker` UI | `connections/page.tsx` | Browse button for local files |
| 16 | Budget ledger (in-memory) | `governance/budget.py` | Resets on pod restart |

## Backend Changes

### API Endpoint Registration
- `api/files.py` — do not register router in cloud mode
- `api/projects.py` — do not register router in cloud mode
- `api/sandboxes.py` — do not register router in cloud mode
- MCP tools: `execute_code`, `dbt_project_validate`, `dbt_project_map`, `dbt_error_parser` — do not register in cloud mode
- Pool manager: reject file-based DuckDB/SQLite connection strings in cloud mode
- `byok_factory.py`: reject `local` provider type in cloud mode

### Store Changes
- `get_local_api_key()` — return None / skip in cloud mode
- `_get_encryption_key()` — require SP_ENCRYPTION_KEY env var in cloud mode (no auto-generate)

## Features Requiring Migration from In-Memory to DB

These are not simple on/off switches — they require product changes to work correctly in multi-replica cloud deployments.

| # | Feature | Current State | Required Change |
|---|---------|---------------|-----------------|
| 1 | Budget ledger | In-memory `dict[str, SessionBudget]` singleton | New `gateway_budgets` table: track per-user/session spend, query on charge, persist across restarts |
| 2 | Schema cache | In-memory `dict` with TTL | Add Redis or DB-backed cache layer. Acceptable per-pod for v1 — auto-refreshes fill each pod independently |
| 3 | Query cache | In-memory `dict` with TTL | Same as schema cache. Acceptable per-pod for v1 |
| 4 | Health monitor | In-memory latency/error tracking | New `gateway_health_samples` table or time-series store. Acceptable per-pod for v1 |
| 5 | YAML annotations | Filesystem `~/.signalpilot/annotations/*.yml` | Migrate to DB: new `gateway_annotations` table or extend endorsements JSON column |
| 6 | Blocked tables (from YAML) | Read from annotation files | Same migration as annotations — DB-backed |

### Priority

**P0 (must fix for cloud launch):**
- Budget ledger → DB (users can bypass budgets by hitting different pods)
- YAML annotations → DB (PII rules and blocked tables must be consistent across pods)

**P1 (acceptable per-pod for v1, fix later):**
- Schema cache → Redis (cache miss just means one extra introspection query)
- Query cache → Redis (cache miss just means one extra query execution)
- Health monitor → DB (each pod shows its own view, which is fine for now)

## Frontend Changes

### Connections Page (`connections/page.tsx`)
- Hide `LocalDBFilePicker` component in cloud mode
- Hide DuckDB "local file" mode option (keep MotherDuck and in-memory)
- Hide SQLite "local file" mode option (keep in-memory)
- Hide file browser button

### Settings Page (`settings/page.tsx`)
- Hide sandbox configuration section in cloud mode

### Security Page (`settings/byok/page.tsx`)
- Hide "local (auto-generated)" provider option in cloud mode
- Only show AWS KMS, GCP Cloud KMS, Azure Key Vault

### Sidebar (`sidebar.tsx`)
- Hide sandbox nav link in cloud mode (if it exists)
- Hide projects nav link in cloud mode

### Dashboard (`dashboard/page.tsx`)
- Hide sandbox section in system topology diagram in cloud mode

## Environment Variable

All checks use: `SP_DEPLOYMENT_MODE` (set in docker-compose or env)
- `local` (default) — all features enabled
- `cloud` — disable everything listed above

Gateway reads: `os.environ.get("SP_DEPLOYMENT_MODE", "local")`
Frontend reads: `process.env.NEXT_PUBLIC_DEPLOYMENT_MODE` (build-time)
