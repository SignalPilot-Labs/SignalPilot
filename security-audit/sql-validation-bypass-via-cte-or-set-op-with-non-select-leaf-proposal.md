# SELECT-only validator may permit dialect-specific side-effecting set-op trees

- Slug: sql-validation-bypass-via-cte-or-set-op-with-non-select-leaf
- Severity: Medium
- Cloud impact: Yes
- Confidence: Medium
- Affected files / endpoints: `signalpilot/gateway/gateway/engine/__init__.py:60-134`

Back to [issues.md](issues.md)

---

## Problem

`validate_sql` checks that the top-level statement type is in `("Select", "With", "Union", "Intersect", "Except", "Subquery")`:

```python
# engine/__init__.py:114-118
if stmt_type not in ("Select", "With", "Union", "Intersect", "Except", "Subquery"):
    return ValidationResult(
        ok=False,
        blocked_reason=f"Blocked: only SELECT queries are allowed (got {stmt_type})",
    )
```

The validator only checks the top-level node type. It does not walk the AST to check for dangerous function calls within otherwise-valid SELECT trees. Many databases expose administrative or data-exfiltration functions as regular SQL functions callable inside SELECT statements:

- **PostgreSQL:** `pg_read_server_files('/etc/passwd')`, `pg_ls_dir('/var/data')`, `lo_import('/etc/passwd')`, `dblink('conn', 'DELETE FROM...')`, `pg_execute_server_program('id')`
- **Snowflake:** `SYSTEM$EXECUTE_PROGRAM(...)`, `SYSTEM$TYPEOF(...)` (less dangerous)
- **BigQuery:** `EXTERNAL_QUERY('conn', 'SELECT ...')` — executes against external databases
- **ClickHouse:** `file('/etc/passwd')`, `url('http://attacker.com/...')`, `s3(...)`, `mysql(...)`, `remoteSecure(...)`
- **Trino:** `system.runtime.nodes` (less dangerous) but plugin functions vary

A query like `SELECT pg_read_server_files('/etc/passwd')` is a valid `Select` statement and passes the validator if the DB role has the `pg_read_server_files` privilege.

Confidence is Medium because the actual exploitability depends on the DB role's privileges. Most managed warehouse roles do not have `pg_read_server_files`. The risk is higher for self-hosted Postgres connections where the warehouse role has been granted admin-equivalent privileges.

---

## Impact

- Depending on DB role privileges: file read, network requests from the database server, or cross-DB query execution.
- In managed cloud warehouses (Snowflake, BigQuery): lower risk, limited functions.
- In self-hosted Postgres: higher risk if the configured role has `SUPERUSER` or `pg_read_server_files` privileges.

---

## Exploit scenario

**PostgreSQL — file read (requires pg_read_server_files privilege):**
```sql
-- Passes validate_sql (it's a SELECT)
SELECT pg_read_server_files('/etc/passwd')
```

```bash
curl https://gateway.signalpilot.ai/api/query \
  -H "X-API-Key: sp_valid_key" \
  -H "Content-Type: application/json" \
  -d '{
    "connection_name": "acme-postgres",
    "query": "SELECT pg_read_server_files('/etc/passwd')"
  }'
```

**ClickHouse — URL fetch:**
```sql
-- Passes validate_sql (top-level Select)
SELECT * FROM url('http://internal-metadata.server/latest/meta-data/iam/security-credentials/', 'JSON', 'x String')
```

**BigQuery — external query:**
```sql
-- Passes validate_sql (top-level Select)
SELECT * FROM EXTERNAL_QUERY('projects/victim/locations/us/connections/internal-pg', 'SELECT * FROM secrets')
```

---

## Affected surface

- Files: `signalpilot/gateway/gateway/engine/__init__.py:60-134`
- Endpoints: `POST /api/query`, all query paths that call `validate_sql`
- Auth modes: Cloud (authenticated user with valid API key or JWT)

---

## Proposed fix

Walk the AST with `find_all(exp.Func)` and reject by name against a per-dialect denylist:

```python
# engine/__init__.py — add after top-level type check:

_DANGEROUS_FUNCTIONS: dict[str, frozenset[str]] = {
    "postgres": frozenset({
        "pg_read_server_files", "pg_read_binary_file", "pg_ls_dir",
        "lo_import", "lo_export", "dblink", "dblink_exec",
        "pg_execute_server_program", "copy_file_internal",
    }),
    "clickhouse": frozenset({
        "file", "url", "s3", "s3cluster", "mysql", "postgresql",
        "remoteSecure", "remote", "hdfs", "jdbc",
    }),
    "bigquery": frozenset({
        "external_query",
    }),
    "snowflake": frozenset({
        "system$execute_program", "system$stream_get",
    }),
    "mysql": frozenset({
        "load_file",
    }),
}

def _check_dangerous_functions(stmt: exp.Expression, dialect: str) -> str | None:
    """Return a blocked_reason if the AST contains a dangerous function, else None."""
    blocked = _DANGEROUS_FUNCTIONS.get(dialect, frozenset())
    if not blocked:
        return None
    for func in stmt.find_all(exp.Anonymous, exp.Func):
        name = (getattr(func, "name", None) or "").lower()
        if name in blocked:
            return f"Blocked: function '{name}' is not permitted in read-only mode"
    return None

# In validate_sql, after stmt_type check:
blocked_fn = _check_dangerous_functions(stmt, dialect)
if blocked_fn:
    return ValidationResult(ok=False, blocked_reason=blocked_fn)
```

Also add a generic allowlist approach: only permit functions from a list of known-safe aggregates, string functions, and math functions per dialect.

---

## Verification / test plan

**Unit tests:**
1. `test_pg_read_server_files_blocked` — `validate_sql("SELECT pg_read_server_files('/etc/passwd')", dialect="postgres")` → `ok=False`.
2. `test_clickhouse_url_function_blocked` — ClickHouse `url()` function → `ok=False`.
3. `test_normal_select_allowed` — `SELECT id, name FROM users WHERE active = true` → `ok=True`.
4. `test_aggregate_functions_allowed` — `SELECT count(*), avg(price) FROM orders` → `ok=True`.

**Manual checklist:**
- Connect a Postgres test database with a superuser role.
- Attempt `SELECT pg_read_server_files('/etc/passwd')` via the API.
- Before fix: succeeds. After fix: `blocked_reason` returned.

---

## Rollout / migration notes

- The denylist can be extended over time; new functions can be added without code changes if the denylist is loaded from a config file.
- False positives: legitimate queries using functions on the denylist will be blocked. Review the list carefully before deploying; start with high-confidence dangerous functions.
- No DB migration required.
- Rollback: remove the `_check_dangerous_functions` call.
