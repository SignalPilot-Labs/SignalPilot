# `POST /api/dbt-cloud/projects` accepts user-supplied `host` and SSRFs the gateway

**Status:** DEPRIORITIZED — feature disabled in cloud as of 2026-04-30; owner not actively maintaining. Severity rating retained to reflect technical risk; treat as low-priority until the feature is re-enabled.

- Slug: dbt-cloud-discover-host-ssrf
- Severity: Medium
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/api/projects.py:84-105`

Back to [issues.md](issues.md)

---

## Problem

The dbt Cloud project discovery endpoint takes a `host` field from the request body and interpolates it directly into a URL passed to `httpx.AsyncClient.get`:

```python
# api/projects.py:84-97
class DbtCloudDiscoverRequest(BaseModel):
    token: str = Field(..., min_length=1)
    account_id: str = Field(..., min_length=1, pattern=r"^[0-9]+$")
    host: str = Field(default="cloud.getdbt.com", max_length=255)

@router.post("/dbt-cloud/projects", dependencies=[RequireScope("admin")])
async def discover_dbt_cloud_projects(req: DbtCloudDiscoverRequest):
    url = f"https://{req.host}/api/v2/accounts/{req.account_id}/projects/"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers={"Authorization": f"Token {req.token}"})
```

`host` defaults to `cloud.getdbt.com` but is fully attacker-controlled — no allowlist, no SSRF check via `network_validation.py`. The string is interpolated into an `https://` URL, then `httpx` resolves DNS and connects.

This is a textbook SSRF: an authenticated user with `admin` scope can point the request at:

- `169.254.169.254` (AWS instance metadata)
- `metadata.google.internal` (GCP)
- `localhost:9200` (gateway-internal Elasticsearch / Postgres)
- `internal-svc.cluster.local:8080`
- A tenant-controlled domain that returns large bodies for DoS.

The `Authorization: Token <token>` header is also forwarded, leaking attacker-supplied tokens to whatever the gateway resolves to. (Less interesting because tokens are also attacker-supplied.)

The route uses `httpx.AsyncClient` with default settings — no `transport` constraint, no `follow_redirects=False` is shown in the snippet (httpx defaults to `follow_redirects=False`, which is good, but should be made explicit).

---

## Impact

- Cross-perimeter information disclosure: gateway pod can be coerced into reading arbitrary internal HTTP endpoints, including cloud-provider metadata services.
- If gateway runs on EC2 with IMDSv1, attacker fetches `iam/security-credentials/<role>` and obtains short-lived AWS credentials with whatever scope the gateway role has.
- If the gateway can reach internal services (Postgres exporter, Prometheus, Vault sidecar), attacker can enumerate them.
- DoS: pointing host at a slow or large endpoint ties up gateway worker for `timeout=15` plus body read.

---

## Exploit scenario

```bash
curl -X POST https://gateway.signalpilot.ai/api/dbt-cloud/projects \
  -H "Authorization: Bearer sp_..." \
  -H "Content-Type: application/json" \
  -d '{
    "token": "fake",
    "account_id": "1",
    "host": "169.254.169.254/latest/meta-data/iam/security-credentials"
  }'
```

The request becomes `https://169.254.169.254/latest/meta-data/iam/security-credentials/api/v2/accounts/1/projects/`. AWS IMDS may still respond on `https://169.254.169.254/...` for IMDSv2 if no token is required (default in older configs). The response body is exposed in the JSON parsing error or downstream logs.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/api/projects.py:84-105`.
- Endpoints: `POST /api/dbt-cloud/projects`.
- Auth modes: requires `admin` scope — exploitable by any tenant admin.

---

## Proposed fix

- Reject `host` values that don't match `^([a-z0-9-]+\.)+(getdbt\.com|cloud\.getdbt\.com)$`. Default to `cloud.getdbt.com` and refuse anything else unless `SP_DBT_CLOUD_ALLOWED_HOSTS` is configured.
- Resolve `host` via `network_validation._resolve_and_check` before constructing the URL (consistent with how connection test SSRF check works).
- Pass `httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(local_address="0.0.0.0", retries=0))` and explicitly `follow_redirects=False`.
- Strip path components from `host` (anything containing `/` or `?` should be rejected).

---

## Verification / test plan

- Unit: parameterize `host` with `["169.254.169.254", "localhost", "metadata.google.internal", "evil.com"]`; assert each returns HTTP 400.
- Unit: `host="cloud.getdbt.com"` succeeds (mock httpx).
- Integration: confirm the SSRF deny list is shared with the connection-test path so behavior is consistent.

---

## Rollout / migration notes

- Customers using non-default dbt Cloud regions (`emea.dbt.com`, `au.dbt.com`) need their hosts added to the allowlist.
- Rollback: relax allowlist; non-destructive.
