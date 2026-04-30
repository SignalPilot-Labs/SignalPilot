# Stacking detector strips comments but not string literals; `;` inside quoted string can confuse it

- Slug: sql-stacking-detection-regex-not-aware-of-string-literals
- Severity: Low
- Cloud impact: Yes
- Confidence: Medium
- Affected files / endpoints: `signalpilot/gateway/gateway/engine/__init__.py:79-83`

Back to [issues.md](issues.md)

---

## Problem

The statement stacking detector runs a regex on comment-stripped SQL:

```python
# engine/__init__.py:40-42
_STACKING_PATTERN = re.compile(r";\s*\w", re.IGNORECASE)

# engine/__init__.py:78-83
stripped = _strip_sql_comments(sql)
if _STACKING_PATTERN.search(stripped.rstrip(";")):
    return ValidationResult(
        ok=False,
        blocked_reason="Statement stacking detected ...",
    )
```

`_strip_sql_comments` removes `--` and `/* */` comments but does NOT strip string literals. A SQL string containing a semicolon followed by a word character triggers a false positive:

```sql
-- Legitimate query — should be allowed:
SELECT 'status;active' AS tag, id FROM users WHERE note = ';select trigger'
```

The regex `;\s*\w` matches on `';select` inside the string literal, causing a false positive rejection of a valid query. This is a **service availability issue**, not a security bypass.

The secondary concern (bypass) is theoretically possible if a SQL dialect uses `\;` escape sequences or non-standard literal quoting that survives comment stripping. In practice, sqlglot's `len(parse) > 1` check (line 97-101) provides a second layer of stacking detection that is literal-aware.

---

## Impact

- **False positives (availability):** Legitimate queries containing semicolons inside string literals are incorrectly rejected.
- **Bypass (low confidence):** An attacker who can construct a payload where the regex fires on a string literal but sqlglot `parse` sees only one statement could in theory have the regex check skip and sqlglot be confused. In practice, sqlglot would either reject or correctly parse, providing the backstop.

---

## Exploit scenario

**False positive (service disruption):**
```bash
curl https://gateway.signalpilot.ai/api/query \
  -H "X-API-Key: sp_valid_key" \
  -H "Content-Type: application/json" \
  -d '{
    "connection_name": "prod",
    "query": "SELECT id, tags FROM events WHERE tags LIKE '\''%status;active%'\''"
  }'
# Returns: {"detail": "Statement stacking detected"} — incorrectly
```

User cannot query tables with semicolons in literal values.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/engine/__init__.py:79-83`
- Endpoints: `POST /api/query`, MCP `execute_query` tool
- Auth modes: Cloud and local (any authenticated user)

---

## Proposed fix

**Option A — Rely solely on sqlglot multi-statement detection:**

Remove the regex entirely. The `len(statements) > 1` check at line 97-101 already provides stacking detection and is literal-aware (sqlglot parses string contents correctly):

```python
# engine/__init__.py — remove these lines:
# stripped = _strip_sql_comments(sql)
# if _STACKING_PATTERN.search(stripped.rstrip(";")):
#     return ValidationResult(ok=False, blocked_reason="Statement stacking detected ...")
```

Sqlglot's multi-statement check handles this correctly:
```python
statements = sqlglot.parse(sql, dialect=dialect)
if len(statements) > 1:
    return ValidationResult(ok=False, blocked_reason="Multiple statements ...")
```

**Option B — Run regex on literal-stripped SQL:**

Strip string literals before regex (complex, fragile). Not recommended.

**Recommended:** Option A. The sqlglot check is the authoritative stacking detector; the regex is redundant and causes false positives.

---

## Verification / test plan

**Unit tests:**
1. `test_semicolon_in_string_literal_not_blocked` — query with `';keyword'` literal, assert `ok=True`.
2. `test_stacking_still_blocked` — `SELECT 1; DROP TABLE users`, assert `ok=False` (caught by sqlglot).
3. `test_stacking_in_comment_still_blocked` — `SELECT 1 -- ; DROP TABLE`, assert `ok=True` (comment-stripped; only one statement).

---

## Rollout / migration notes

- Removing the regex reduces one layer of defense but sqlglot is the more accurate detector.
- No data migration.
- Rollback: restore the regex lines.
