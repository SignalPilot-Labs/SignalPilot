---
description: "Use when addressing security vulnerabilities, reviewing auth, fixing CORS, credential exposure, or SQL injection. Covers the known SECURITY_AUDIT.md findings and remediation patterns."
---

# Security Audit Remediation

## Known Findings Location

The full audit is at `/workspace/testing/SECURITY_AUDIT.md`. Read it first.

## Priority Order

1. **CRITICAL** — Fix immediately (sqlglot fallback bypass, unauthenticated endpoints)
2. **HIGH** — Fix next (CORS wildcard, statement stacking bypass, credential vault)
3. **MEDIUM/LOW** — Fix if time permits

## Common Patterns

### Adding Authentication to FastAPI Endpoints

```python
from fastapi import Depends, HTTPException, Header

async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key

@app.get("/api/protected", dependencies=[Depends(verify_api_key)])
async def protected_endpoint():
    ...
```

### Fixing CORS

Replace `allow_origins=["*"]` with explicit origins:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3200"],
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "X-API-Key"],
)
```

### SQL Validation Hardening

The sqlglot fallback silently passes all queries. Fix:

```python
if not HAS_SQLGLOT:
    return ValidationResult(ok=False, error="SQL validation unavailable")
```

### Error Message Sanitization

Never leak internal details:

```python
# BAD
raise HTTPException(status_code=500, detail=str(e))
# GOOD
logger.error(f"Internal error: {e}")
raise HTTPException(status_code=500, detail="Internal server error")
```

## Testing Security Fixes

- Verify endpoints return 401 without auth header
- Verify CORS preflight only allows expected origins
- Verify SQL injection attempts are blocked
- Verify error messages don't leak stack traces
