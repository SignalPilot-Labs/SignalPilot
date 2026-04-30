# `_extract_credential_extras` stores plaintext `password` in `extras_enc` JSON in addition to baking it into the connection string

- Slug: connector-credentials-extras-include-plaintext-password-twice
- Severity: Low
- Cloud impact: Yes
- Confidence: Medium
- Affected files / endpoints: `signalpilot/gateway/gateway/store.py:438-471`

Back to [issues.md](issues.md)

---

## Problem

When connector credentials are stored, the `_extract_credential_extras` function includes both the full connection string (which contains the password) and the password field separately in the `extras_enc` column:

The password ends up in two encrypted columns: once in the connection string field, and potentially again in the `extras` JSON blob. While both are encrypted at rest with Fernet, this creates two exposure surfaces:

1. Any code path that decrypts `extras_enc` for any purpose (e.g., dbt `profiles.yml` generation, connection testing) sees the plaintext password separately.
2. Log lines that accidentally print `extras` fields may leak the password twice.
3. A partial Fernet key compromise (e.g., one Fernet key rotation window where an old key is leaked) exposes two ciphertext blobs that both decrypt to the same password — doubling the exposure.

Confidence is Medium because this requires reading the full `_extract_credential_extras` implementation, which was not fully visible in the reviewed section.

---

## Impact

- Doubled exposure surface for plaintext passwords during decryption.
- Audit/debug log risk: if any code logs the decrypted `extras` dict, passwords appear.
- Defense-in-depth violation: the password should live in exactly one place (the connection string) and be pulled from there at use-time.

---

## Exploit scenario

Developer adds a debug log line to `_extract_credential_extras`:
```python
logger.debug("Extras for connection %s: %s", conn_id, extras)
# Log contains: {"password": "hunter2", "host": "prod.db.acme.com", ...}
```

The password appears in application logs, which are often shipped to a log aggregation service (Datadog, Splunk) with weaker access controls than the encrypted DB.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/store.py:438-471`
- Endpoints: Any endpoint that creates or updates connections; `test-credentials` path
- Auth modes: Cloud and local

---

## Proposed fix

Remove the `password` field from `extras` when it is already encoded in the connection string:

```python
# store.py:_extract_credential_extras — updated:
def _extract_credential_extras(conn: ConnectionData) -> dict[str, Any]:
    extras: dict[str, Any] = {}
    # Extract fields OTHER than password — password lives in the connection string
    if conn.ssh_host:
        extras["ssh_host"] = conn.ssh_host
        # ... other SSH fields ...
    # Explicitly do NOT add password to extras if it's already in the connection string
    # At use-site, pull password from the connection string instead
    return extras
```

If the password is needed separately at use-time (e.g., for dbt profiles), extract it from the connection string using `urllib.parse.urlparse`:

```python
from urllib.parse import urlparse
parsed = urlparse(conn_str)
password = parsed.password  # Extract at use-time, not at storage time
```

---

## Verification / test plan

**Unit tests:**
1. `test_extract_credential_extras_no_password` — assert `password` key is not present in returned extras dict.
2. `test_connection_string_contains_password` — assert password is accessible from connection string.

**Manual checklist:**
- Add a debug log line for `extras` in a test environment.
- Verify password does not appear in log output.

---

## Rollout / migration notes

- Existing rows in DB have the password in `extras_enc`. A migration can re-encrypt without the password field, or the field can simply be ignored at read time.
- No breaking changes to authentication behavior.
- Rollback: restore password field in extras.
