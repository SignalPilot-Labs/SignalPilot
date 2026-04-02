# SQL Safety Review Checklist

Scope: When diff touches `gateway/engine/`, `gateway/governance/`, `gateway/connectors/`, or SQL-related test files

---

## Query Validation Pipeline

The engine in `gateway/engine/__init__.py` implements a layered safety pipeline. Changes must preserve all layers.

- `validate_sql()` must run BEFORE `inject_limit()` — if parse fails in validate, the limit fallback path is never reached
- Null byte check (`\x00`) must remain the first check — prevents downstream parser bypass
- 100KB query length cap must not be raised without security review
- Comment stripping (`_strip_sql_comments`) must run before the stacking regex `;\s*\w`
  - Without this, `-- ; DROP TABLE` bypasses the regex check
- Query stacking detection has TWO layers: regex first, then AST `len(statements) > 1` — both must be preserved

## Statement Type Blocking

The `_BLOCKED_STATEMENT_TYPES` set blocks DDL/DML by matching `type(stmt).__name__`.

- New sqlglot statement types not added to the blocked set when they should be
  - The set includes `Command` to catch `COPY`, `VACUUM`, etc.
- Allowlist approach: only `Select`, `With`, `Union`, `Intersect`, `Except`, `Subquery` are permitted
- Changes to the blocked set must include corresponding test cases in `tests/`

## LIMIT Injection

`inject_limit()` uses sqlglot AST to find/replace LIMIT clauses.

- The fallback path `f"{sql} LIMIT {max_rows}"` activates when sqlglot parse fails
  - This corrupts queries with trailing clauses (e.g., `ORDER BY`) — verify `validate_sql` blocks these cases first
- Existing LIMIT values exceeding `max_rows` (default 10,000) must be reduced, not left as-is
- Subqueries should NOT have LIMIT injected — only the outermost SELECT

## Connector Parameterization

Connectors execute queries via driver-specific methods. Parameterization prevents injection at the driver level.

- **Postgres** (`connectors/postgres.py`): uses `asyncpg` with `$1, $2` positional params + `readonly=True` transactions
- **SQLite** (`connectors/sqlite.py`): uses `conn.execute(sql, params or [])` with `?` placeholders
- Schema introspection queries: MUST use `_quote_identifier()` / `_quote_table()` from base class, NOT f-string interpolation
  - SQLite uses bracket quoting `[tablename]`; Postgres uses double-quote `"tablename"`
- New connectors MUST enforce read-only at the driver level (Postgres uses `readonly=True`; SQLite currently lacks this — known gap)
- Connection strings passed as raw DSN — no sanitization layer exists; never log or expose them

## PII Governance

PII rules in `governance/pii.py` apply post-query via `annotations.yml`.

- `hash` rule uses truncated SHA-256 (12 hex chars = 48 bits) — insufficient for low-entropy data like short PINs
  - Use `drop` instead of `hash` for columns with fewer than 6 character values
- `mask` preserves structure (e.g., `***-**-1234`) — verify new masking patterns don't leak identifiable info
- `detect_pii_columns()` auto-detection uses 30+ column name patterns — new columns with PII-like names should be checked
- Annotations cache has 60-second TTL (`SP_ANNOTATIONS_TTL`) — changes to `annotations.yml` take up to 60s to apply

## Query Cache Safety

`governance/cache.py` caches results keyed by `SHA-256(connection + normalized_sql + row_limit)`.

- Cache key normalization is `strip().lower().split()` join — case-insensitive, whitespace-insensitive
- `invalidate(connection_name)` currently clears the ENTIRE cache (cannot filter by connection in hashed keys)
- New query types that return different results based on session state should NOT be cached
- Cache entries have 5-minute TTL and 1000-entry LRU limit — do not increase without memory impact analysis

## Cost Estimation

`governance/cost_estimator.py` routes by `db_type` to dialect-specific EXPLAIN parsing.

- `is_expensive` threshold: USD > $1.00 or rows > 1,000,000
- BigQuery has a hard byte-limit safety gate (`would_exceed_limit`) — other connectors do not
- New connectors must implement a cost estimation method or the feature silently returns no estimate
- EXPLAIN queries must use the same read-only transaction as the actual query
