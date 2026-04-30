# When sqlglot fails to parse, `inject_limit` returns `f"{sql} LIMIT {max_rows}"` — concatenation of unvalidated SQL

- Slug: inject-limit-fallback-string-concat-on-parse-failure
- Severity: Medium
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/engine/__init__.py:146-149`

Back to [issues.md](issues.md)

---

## Problem

`inject_limit` falls back to string concatenation when `sqlglot.parse_one` raises an exception:

```python
# engine/__init__.py:146-149
try:
    parsed = sqlglot.parse_one(sql, dialect=dialect)
except Exception:
    return f"{sql} LIMIT {max_rows}"  # <-- concatenation of unvalidated SQL
```

`validate_sql` runs before `inject_limit` and uses `sqlglot.parse` (note: different function from `parse_one`). If `sqlglot.parse` successfully parses the SQL but `sqlglot.parse_one` raises (due to parser asymmetry between the two functions, a dialect-specific parse_one bug, or a sqlglot version regression), the fallback path produces a SQL string that:

1. Has passed `validate_sql` (so it looks like a SELECT).
2. Has had no AST-level LIMIT injection (limit is appended as raw text).
3. Is sent directly to the database connector.

If the SQL contains any ambiguity that `parse_one` rejects but `parse` accepted, the validator's conclusions (blocked tables, statement type, etc.) may not apply to what `parse_one` would have produced. The string-concat fallback sends this potentially-ambiguous SQL to the database.

Additionally, `f"{sql} LIMIT {max_rows}"` does not handle dialects that require `FETCH FIRST {n} ROWS ONLY` (MSSQL, DB2) — the injected `LIMIT` may cause a DB syntax error on those dialects, revealing error details.

---

## Impact

- If parser asymmetry is triggered: a SQL statement that `validate_sql` approved but `parse_one` would reject gets sent to the DB without LIMIT enforcement.
- In the worst case: a query that was approved as a SELECT by `validate_sql` but actually executes differently (due to dialect-specific parsing ambiguity) runs without any LIMIT on the result set.
- High confidence in the fallback existing; medium confidence in a realistic trigger (parse asymmetry exists but is rare in stable sqlglot versions).

---

## Exploit scenario

**Parser version skew scenario:**
1. User submits: `WITH cte AS (SELECT 1) SELECT * FROM cte` (a valid CTE).
2. `validate_sql` uses `sqlglot.parse` — parses successfully, returns `ok=True`.
3. `inject_limit` uses `sqlglot.parse_one` — in a hypothetical version where CTE parsing is broken for a specific dialect, raises `Exception`.
4. Fallback: `"WITH cte AS (SELECT 1) SELECT * FROM cte LIMIT 10000"` — string concat.
5. This is correct SQL but the LIMIT is appended as text, not AST-injected. For a more complex CTE, the appended LIMIT might attach to the wrong subquery.

**No current known exploit** — this is a defense-in-depth issue. The validator has already approved the SQL before this path runs.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/engine/__init__.py:146-149`
- Endpoints: `POST /api/query`, MCP `execute_query` tool
- Auth modes: Cloud and local (any authenticated user)

---

## Proposed fix

Fail closed — if `parse_one` fails after `validate_sql` passed, raise instead of concatenating:

```python
# engine/__init__.py:inject_limit — updated:
def inject_limit(sql: str, max_rows: int = 10_000, dialect: str = "postgres") -> str:
    sql = sql.strip().rstrip(";")

    if not HAS_SQLGLOT:
        raise RuntimeError("SQL validation engine not available")

    try:
        parsed = sqlglot.parse_one(sql, dialect=dialect)
    except Exception as exc:
        # Fail closed: do not concatenate unvalidated SQL.
        # validate_sql already verified the SQL — a parse_one failure indicates
        # parser asymmetry. Raise to surface the inconsistency.
        raise ValueError(
            f"SQL passed validation but could not be parsed by inject_limit: {exc}"
        ) from exc

    if parsed is None:
        raise ValueError("SQL produced no parse tree in inject_limit")
    ...
```

The caller of `inject_limit` (in the query execution path) should catch `ValueError` and return an appropriate error to the user.

---

## Verification / test plan

**Unit tests:**
1. `test_inject_limit_parse_failure_raises` — mock `sqlglot.parse_one` to raise, assert `ValueError` (not a returned SQL string).
2. `test_inject_limit_normal_cte` — CTE query, assert `LIMIT` injected at correct position.
3. `test_inject_limit_existing_limit_clamped` — query with `LIMIT 1000000` and `max_rows=10000`, assert limit is clamped.

**Manual checklist:**
- Use a dialect where `parse_one` is known to be stricter than `parse` (if applicable).
- Verify that the error is surfaced to the API caller as a 400, not a 500.

---

## Rollout / migration notes

- Queries that currently hit the fallback path (if any exist in production) will start returning 400 errors. Monitor error rates after deploy.
- No data migration.
- Rollback: restore the `return f"{sql} LIMIT {max_rows}"` line.
