# `GatewayAuditLog.sql_text` stores full user SQL — may contain PII / customer data

- Slug: audit-log-stores-full-sql-text-including-pii
- Severity: Medium
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/store.py:1213-1235`, `signalpilot/gateway/gateway/db/models.py`

Back to [issues.md](issues.md)

---

## Problem

Every query executed through the gateway is logged to `GatewayAuditLog` with the full SQL text:

```python
# store.py:1213-1235 (approximate)
await session.execute(
    insert(GatewayAuditLog).values(
        id=entry.id,
        org_id=oid,
        event_type=entry.event_type,
        connection_name=entry.connection_name,
        sql_text=entry.sql_text,  # Full SQL string, including literal values
        ...
    )
)
```

If a user queries `SELECT * FROM users WHERE email = 'alice@acme.com' AND password = 'hunter2'`, both the email and password are stored verbatim in the audit log.

Problems:
1. **PII in audit logs:** Email addresses, phone numbers, SSNs, and other personal data embedded as SQL literals are stored indefinitely in the audit log. This violates GDPR/CCPA principles of data minimization and purpose limitation.
2. **Secrets in SQL:** Users occasionally embed secrets or passwords in queries (especially during onboarding when testing connections). These are permanently logged.
3. **Long retention:** Audit logs are typically retained longer than transactional data for compliance reasons, which extends PII exposure.
4. **Access control asymmetry:** Any `org:admin` user with `GET /api/audit` access sees all SQL, including queries by other org members that may contain their personal search parameters.

---

## Impact

- GDPR/CCPA compliance risk: PII in SQL literals is stored without explicit consent in the audit log.
- Secrets leakage: credentials embedded in SQL are permanently logged.
- Internal data access: org admins can read queries of other org members, potentially including sensitive filter values.

---

## Exploit scenario

1. User runs: `SELECT id, name FROM employees WHERE ssn = '123-45-6789'`.
2. The SSN is stored in `GatewayAuditLog.sql_text`.
3. Org admin calls `GET /api/audit` — sees the SSN in the log.
4. In a data breach, the audit log is compromised — attacker has SSNs from all queries.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/store.py:1213-1235`, `signalpilot/gateway/gateway/db/models.py` (GatewayAuditLog schema)
- Endpoints: All endpoints that append audit entries
- Auth modes: Cloud and local

---

## Proposed fix

Add a SQL literal redaction layer before storing:

```python
# engine/sql_redact.py — new module:
import sqlglot
import sqlglot.expressions as exp

def redact_sql_literals(sql: str, dialect: str = "postgres") -> str:
    """Replace string and numeric literals with redacted placeholders."""
    try:
        tree = sqlglot.parse_one(sql, dialect=dialect)
        if tree is None:
            return "<unredacted-parse-error>"
        
        # Replace all string literals
        for node in tree.find_all(exp.Literal):
            if node.is_string:
                node.replace(exp.Literal.string("<REDACTED>"))
            elif node.is_number:
                # Keep numeric literals — they're less likely to be PII
                # Consider redacting for financial data
                pass
        
        return tree.sql(dialect=dialect)
    except Exception:
        # If redaction fails, store a safe placeholder
        return "<sql-redacted-on-error>"
```

Use this in `append_audit`:

```python
# store.py:append_audit:
from .engine.sql_redact import redact_sql_literals

redacted_sql = redact_sql_literals(entry.sql_text or "") if entry.sql_text else None

await session.execute(
    insert(GatewayAuditLog).values(
        ...
        sql_text=redacted_sql,
        ...
    )
)
```

Provide a configuration option: `SP_AUDIT_REDACT_SQL=true/false` (default true in cloud mode).

---

## Verification / test plan

**Unit tests:**
1. `test_redact_sql_string_literals` — `SELECT * FROM users WHERE email = 'alice@example.com'` → `SELECT * FROM users WHERE email = '<REDACTED>'`.
2. `test_redact_sql_multiple_literals` — multiple literals, all redacted.
3. `test_redact_sql_parse_error_fallback` — malformed SQL, assert safe placeholder returned.
4. `test_audit_stores_redacted_sql` — end-to-end, verify `sql_text` in DB does not contain the original literal.

**Manual checklist:**
- Issue a query with a known PII value.
- Check `GET /api/audit` response.
- Before fix: PII visible in `sql_text`. After fix: `<REDACTED>` in place of literals.

---

## Rollout / migration notes

- **Existing audit log rows** contain unredacted SQL. A backfill migration can redact them, or they can be retained as-is with a retention policy (delete after N days).
- Redaction changes the behavior of audit log search — searching for a specific SQL pattern may now return `<REDACTED>` instead of the actual value. Document this tradeoff.
- Rollback: set `SP_AUDIT_REDACT_SQL=false`.
