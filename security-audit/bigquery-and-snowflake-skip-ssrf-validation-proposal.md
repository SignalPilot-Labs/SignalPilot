# SSRF allowlist excludes `snowflake`, `bigquery`, `databricks` — yet `account` / `host` come from user input

- Slug: bigquery-and-snowflake-skip-ssrf-validation
- Severity: Medium
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/network_validation.py:34-41`

Back to [issues.md](issues.md)

---

## Problem

`TCP_DB_TYPES` — the set of database types that undergo SSRF validation — explicitly excludes cloud warehouse connectors:

```python
# network_validation.py:34-41
TCP_DB_TYPES: frozenset[str] = frozenset({
    "postgres",
    "mysql",
    "mssql",
    "redshift",
    "clickhouse",
    "trino",
})
# snowflake, bigquery, databricks — NOT in TCP_DB_TYPES, so SSRF validation is skipped
```

The comment explains the rationale: these use HTTPS to external cloud endpoints. However, the destination URL for each connector is constructed from user-supplied fields:

- **Snowflake:** `account` parameter → SDK builds `https://{account}.snowflakecomputing.com` (or just `{account}` if no suffix). If `account = "metadata.google.internal"`, the SDK requests `https://metadata.google.internal.snowflakecomputing.com`... but what if `account = "attacker.com#"` or uses a custom domain?
- **Databricks:** `host` parameter → SDK connects to `https://{host}`. If `host = "169.254.169.254"`, the SDK makes an HTTPS request to the metadata server (connection may fail TLS but returns headers).
- **BigQuery:** `project_id` parameter — less direct SSRF risk, but `EXTERNAL_QUERY` can reference other connection strings.

The risk is highest for Databricks where `host` is a free-form hostname, and potentially for Snowflake if custom domains or the `#` trick can redirect the host.

---

## Impact

- **Databricks:** Attacker sets `host=169.254.169.254` → Databricks connector makes HTTPS request to metadata server. Even if TLS fails, the SDK may log response headers or attempt HTTP fallback.
- **Snowflake:** Lower risk due to `*.snowflakecomputing.com` domain enforcement in the official SDK, but a custom domain Snowflake setup (`privatelink.snowflakecomputing.com`) could be bypassed with a crafted `account` value.
- **Cloud:** This is a cloud-only issue since these connectors are primarily used in cloud mode.

---

## Exploit scenario

**Databricks SSRF:**
```bash
curl -X POST https://gateway.signalpilot.ai/api/connections \
  -H "Authorization: Bearer <jwt>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "attack-conn",
    "db_type": "databricks",
    "host": "169.254.169.254",
    "port": 443,
    "database": "default",
    "username": "token",
    "password": "dapi_fake"
  }'

# Then test credentials:
curl -X POST https://gateway.signalpilot.ai/api/connections/attack-conn/test-credentials
# The Databricks connector makes HTTPS to 169.254.169.254 — may leak AWS metadata
```

**Snowflake SSRF (lower confidence):**
```json
{"account": "attacker.com/path?#", "db_type": "snowflake"}
```
SDK builds `https://attacker.com/path?#.snowflakecomputing.com` — if the SDK does not sanitize, this becomes a request to `attacker.com`.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/network_validation.py:34-41`
- Endpoints: `POST /api/connections` (creation), `POST /api/connections/test-credentials`
- Auth modes: Cloud (authenticated users with write scope)

---

## Proposed fix

Add format validation for cloud warehouse connection parameters:

```python
# network_validation.py — add validators:
import re

_SNOWFLAKE_ACCOUNT_RE = re.compile(r'^[a-zA-Z0-9._-]{1,255}$')
_DATABRICKS_HOST_RE = re.compile(
    r'^[a-zA-Z0-9.-]+(\.cloud\.databricks\.com|\.azuredatabricks\.net|\.gcp\.databricks\.com)$'
)
_BIGQUERY_PROJECT_RE = re.compile(r'^[a-z0-9-]{6,30}$')

def validate_cloud_warehouse_params(db_type: str, params: dict) -> None:
    """Validate cloud warehouse connection parameters to prevent SSRF."""
    if db_type == "snowflake":
        account = params.get("account", "")
        if not _SNOWFLAKE_ACCOUNT_RE.match(account):
            raise ValueError(f"Invalid Snowflake account identifier: {account!r}")
    elif db_type == "databricks":
        host = params.get("host", "")
        if not _DATABRICKS_HOST_RE.match(host):
            raise ValueError(f"Invalid Databricks host: {host!r}. Must match *.cloud.databricks.com")
    elif db_type == "bigquery":
        project_id = params.get("project_id", "")
        if project_id and not _BIGQUERY_PROJECT_RE.match(project_id):
            raise ValueError(f"Invalid BigQuery project_id: {project_id!r}")
```

Call `validate_cloud_warehouse_params` in `validate_connection_params` for cloud warehouse types.

For enterprise/private link setups (Snowflake privatelink, Databricks custom domains), expose an allow-list env var `SP_ALLOWED_WAREHOUSE_DOMAINS`.

---

## Verification / test plan

**Unit tests:**
1. `test_snowflake_invalid_account_rejected` — `account="169.254.169.254"`, assert `ValueError`.
2. `test_databricks_non_databricks_host_rejected` — `host="attacker.com"`, assert `ValueError`.
3. `test_databricks_valid_host_accepted` — `host="adb-xxx.azuredatabricks.net"`, assert no error.
4. `test_bigquery_invalid_project_rejected` — `project_id="../../etc"`, assert `ValueError`.

---

## Rollout / migration notes

- Existing connections with valid hostnames are unaffected.
- Custom domain setups (enterprise Snowflake privatelink) may require adding to `SP_ALLOWED_WAREHOUSE_DOMAINS`.
- Rollback: remove the `validate_cloud_warehouse_params` call.

**Related findings:** [connection-test-tcp-connect-toctou-vs-ssrf-check](connection-test-tcp-connect-toctou-vs-ssrf-check-proposal.md)
