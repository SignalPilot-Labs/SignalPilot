# 2 MB request limit interacts with 100 KB SQL limit — allows ~20x over-limit body

- Slug: request-body-2mb-limit-may-allow-large-sql-payloads
- Severity: Info
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/main.py:287`, `signalpilot/gateway/gateway/engine/__init__.py:74`

Back to [issues.md](issues.md)

---

## Problem

The gateway applies a 2 MB body size limit globally:

```python
# main.py:287
app.add_middleware(RequestBodySizeLimitMiddleware, max_body_bytes=2_097_152)  # 2 MB
```

Individual SQL queries are capped at 100 KB:

```python
# engine/__init__.py:74
if len(sql) > 100_000:
    return ValidationResult(ok=False, blocked_reason="Query exceeds maximum length (100KB)")
```

The gap is intentional — the 2 MB limit accommodates file uploads (BYOK key imports, connection credential imports). However, this creates a 20x ratio between the body limit and the SQL limit:

1. A request with a 2 MB JSON body can be sent to the query endpoint even though only 100 KB of SQL is permitted. The remaining ~1.9 MB of request body is parsed (with JSON overhead) before the 100 KB SQL check runs.
2. Malformed JSON at 2 MB is parsed by the Python JSON parser before any validation — this is a potential DoS vector if the JSON parser has a quadratic-time edge case.
3. The 100 KB SQL limit is enforced inside the validation function, not at the middleware level. If an endpoint fails to call `validate_sql` before using the SQL, the limit is bypassed.

This is an Info-level finding because:
- The intentional design is valid (file uploads need 2 MB).
- The 100 KB SQL limit is consistently enforced in `validate_sql`.
- No current bypass is identified.

---

## Impact

- DoS via large JSON bodies to the query endpoint (2 MB parsed before rejection).
- If any endpoint fails to call `validate_sql`, it accepts 2 MB of unvalidated SQL.
- Documentation gap: the intentional design is not documented anywhere.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/main.py:287`, `signalpilot/gateway/gateway/engine/__init__.py:74`
- Endpoints: `POST /api/query` and all other endpoints
- Auth modes: Cloud and local

---

## Proposed fix

1. **Document the design decision** in `main.py`:

```python
# main.py:
# Body size limit: 2 MB to accommodate BYOK key imports and connection credential imports.
# SQL queries within this body are further limited to 100 KB in validate_sql().
# The gap is intentional.
app.add_middleware(RequestBodySizeLimitMiddleware, max_body_bytes=2_097_152)
```

2. **Add a per-endpoint body limit** for the query endpoint (optional — more work):

```python
# api/query.py — add explicit check at the endpoint level:
@router.post("/query")
async def run_query(request: Request, ...):
    # Lightweight pre-check before full body parse:
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 200_000:  # 200 KB for query endpoint
        raise HTTPException(status_code=413, detail="Request body too large for query endpoint")
```

3. **Add a CI check** that verifies all query endpoints call `validate_sql`:

```bash
# In CI:
grep -rn "execute_query\|run_query" signalpilot/gateway/gateway/api/ | \
  xargs grep -L "validate_sql" | \
  { read -r files; [ -z "$files" ] || { echo "Query endpoint missing validate_sql"; exit 1; }; }
```

---

## Verification / test plan

**Unit tests:**
1. `test_2mb_body_to_query_endpoint_rejected_by_sql_limit` — send 2 MB body with 2 MB SQL field, assert 400 (SQL too long).
2. `test_100kb_sql_rejected` — SQL exactly 100,001 bytes, assert `blocked_reason` in response.

---

## Rollout / migration notes

- No data migration.
- Documentation-only change in the first phase.
- The per-endpoint limit (option 2) is an optional hardening step.
- Rollback: remove the documentation comments.
