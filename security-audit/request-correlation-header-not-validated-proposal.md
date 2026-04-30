# `X-Request-ID` is accepted from clients and logged unsanitized

- Slug: request-correlation-header-not-validated
- Severity: Low
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/middleware.py:174,200` (log lines with request ID)

Back to [issues.md](issues.md)

---

## Problem

The correlation middleware accepts the client-supplied `X-Request-ID` header and propagates it through the request lifecycle. If this value is logged unsanitized (which is common in correlation middleware patterns), an attacker can inject log entries.

Log injection via newlines in the `X-Request-ID` header:
- A crafted value containing `\n` or `\r\n` can inject fake log lines.
- These fake lines may impersonate other log entries (e.g., `INFO: Authentication successful for user admin`).
- In log aggregation systems (Datadog, Splunk), injected entries may corrupt searches, alert suppression, or incident timelines.

The `correlation.py` file was referenced in the spec but the exact log lines were cited at `middleware.py:174,200`. The `X-Request-ID` is forwarded in response headers (`expose_headers=["X-Request-ID"]` in CORS config), meaning it is also reflected back to clients — this creates a header injection risk in the response if the value is not stripped.

---

## Impact

- Log injection: attacker crafts fake log entries to confuse incident analysis.
- Header injection in response (if the value is reflected unsanitized): could potentially inject response headers or corrupt log pipelines.
- Impact is Low because log injection requires attacker to have network access (can send requests) and does not give additional data access.

---

## Exploit scenario

```bash
# Attacker injects fake log entry via X-Request-ID:
curl https://gateway.signalpilot.ai/api/query \
  -H "X-Request-ID: legitimate-id\nINFO: Authentication successful for user admin in org all-orgs" \
  -H "Content-Type: application/json" \
  -d '...'

# Gateway logs:
# INFO: Request received (x-request-id=legitimate-id)
# INFO: Authentication successful for user admin in org all-orgs  <-- injected
```

An analyst reviewing logs sees the fake authentication success and may dismiss a real anomaly.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/middleware.py:174,200`, `signalpilot/gateway/gateway/correlation.py`
- Endpoints: All endpoints (correlation middleware runs on all requests)
- Auth modes: Both cloud and local

---

## Proposed fix

Sanitize `X-Request-ID` at the boundary:

```python
# correlation.py (or RequestCorrelationMiddleware):
import re
import uuid

_REQUEST_ID_RE = re.compile(r'^[a-zA-Z0-9\-_]{1,64}$')

def _sanitize_request_id(value: str | None) -> str:
    """Return sanitized request ID, generating a new one if invalid."""
    if value and _REQUEST_ID_RE.match(value):
        return value
    # Generate a fresh ID — don't trust attacker-supplied values
    return str(uuid.uuid4())

# In middleware:
request_id = _sanitize_request_id(request.headers.get("x-request-id"))
```

If the client supplies an invalid `X-Request-ID`, generate a new UUID and use that. The response header should reflect the sanitized/generated ID.

Additionally, use structured logging (JSON) rather than string interpolation for log entries containing external data — this prevents newline injection:

```python
# Instead of: logger.info("Request %s received", request_id)
# Use: logger.info("Request received", extra={"request_id": request_id})
# JSON formatter: {"message": "Request received", "request_id": "abc-123"}
```

---

## Verification / test plan

**Unit tests:**
1. `test_request_id_newline_stripped` — header with `\n`, assert sanitized ID returned (no newlines).
2. `test_request_id_valid_passthrough` — `abc-123`, assert passthrough.
3. `test_request_id_too_long_regenerated` — 200-char value, assert UUID generated.
4. `test_request_id_empty_generates_uuid` — no header, assert UUID in response.

**Manual checklist:**
- Send request with `X-Request-ID: abc\nfake-log-entry`.
- Inspect gateway logs — fake entry should not appear.
- Inspect response header — should contain a UUID, not the injected value.

---

## Rollout / migration notes

- No data migration.
- This may change the `X-Request-ID` echo behavior for clients that supply IDs — they will now receive a UUID if their ID is invalid.
- Rollback: remove the sanitization step.
