# `test-credentials` does SSRF DNS check, then independent `socket.connect((host, port))` — DNS rebinding window

- Slug: connection-test-tcp-connect-toctou-vs-ssrf-check
- Severity: Medium
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/api/connections.py:802-858`

Back to [issues.md](issues.md)

---

## Problem

The `test_credentials` flow performs SSRF host validation and then makes an independent TCP connection using the hostname:

```python
# api/connections.py:806-812
try:
    validate_connection_params(conn.host, conn.port, conn.db_type, conn.connection_string)
except ValueError as e:
    return {"status": "error", ...}

# api/connections.py:844-857 (phase 1 — network check)
parsed = urlparse(conn_str if "://" in conn_str else f"dummy://{conn_str}")
host = parsed.hostname or conn.host or "localhost"
port = parsed.port or conn.port or 5432

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(5)
sock.connect((host, int(port)))  # Re-resolves hostname at this point
```

`validate_connection_params` resolves the hostname via DNS at time T and validates the resulting IPs. The subsequent `socket.connect((host, port))` triggers another DNS resolution at time T+Δ.

An attacker with control over a DNS server can exploit this Time-of-Check/Time-of-Use (TOCTOU) race:
1. First DNS resolution (SSRF check) → returns public IP → passes validation.
2. Between T and T+Δ, the DNS record (with a very short TTL, e.g., 0-1s) is swapped to point to `169.254.169.254` (AWS metadata) or `10.x.x.x` (internal).
3. Second DNS resolution (`socket.connect`) → gets private IP.
4. TCP connection is made to the internal/metadata address.

This is the classic DNS rebinding attack bypassing SSRF protections.

---

## Impact

- SSRF to AWS instance metadata service (`169.254.169.254/latest/meta-data/iam/security-credentials/`) — leaks instance IAM credentials, enabling full AWS account access from the gateway's IAM role.
- SSRF to internal services (Kubernetes API server, internal databases, Redis, etc.) accessible from the gateway pod network.
- In cloud deployments, the gateway likely has an IAM role with at least database access permissions — those credentials are the primary target.

---

## Exploit scenario

1. Attacker registers domain `attacker.com`.
2. DNS record: `db.attacker.com` → `1.2.3.4` (public IP), TTL=0.
3. Attacker sends `POST /api/connections/test-credentials` with `host=db.attacker.com`.
4. Gateway calls `validate_connection_params("db.attacker.com", ...)`.
5. DNS resolves to `1.2.3.4` (public) — SSRF check passes.
6. Attacker's DNS server switches to `db.attacker.com` → `169.254.169.254`.
7. Gateway calls `socket.connect(("db.attacker.com", 5432))`.
8. DNS resolves to `169.254.169.254` — socket connects to metadata server.
9. If a higher-layer connector (e.g., psycopg2) follows with an HTTP request to this address, it reaches the metadata service.

Note: the TCP connect itself to port 5432 on the metadata server may fail (metadata server listens on port 80/443 not 5432). However, for HTTP-based connectors (ClickHouse HTTP interface, Trino, etc.) where the connector makes an HTTP request to a configurable host, the exploit is more direct.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/api/connections.py:802-858`
- Endpoints: `POST /api/connections/test-credentials` (or similar test endpoint)
- Auth modes: Cloud (any authenticated user with write scope)

---

## Proposed fix

After SSRF validation, extract the resolved IP addresses and connect to the IP directly, using the hostname only as the TLS SNI/verification anchor:

```python
# api/connections.py — DNS-safe connect:
import socket
import ipaddress
from .network_validation import validate_connection_params, _resolve_and_validate

# Resolve once, validate, save the resolved IP:
validated_ips = _resolve_and_validate(host, allow_private)
# _resolve_and_validate returns a list of validated (non-private) IP strings

if not validated_ips:
    return {"status": "error", "message": "Host resolves to blocked address"}

# Connect to the IP directly — no re-resolution:
target_ip = validated_ips[0]
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(5)
try:
    sock.connect((target_ip, int(port)))  # IP, not hostname
    sock.close()
except ...:
    ...
```

For TLS connections, pass `server_hostname=host` to `ssl.wrap_socket()` so certificate verification uses the original hostname (not the IP). For non-TLS (plain TCP), connecting to the IP is sufficient.

Export `_resolve_and_validate` from `network_validation.py` to return the validated IP list for reuse.

---

## Verification / test plan

**Unit tests:**
1. `test_dns_rebinding_protection` — mock DNS to return different IPs on first and second resolution; assert connection uses the first-resolved (validated) IP.
2. `test_ssrf_validated_ip_used_for_connect` — verify `socket.connect` receives an IP address, not a hostname.

**Manual checklist:**
- Set up a local DNS server that rebinds after first query.
- Send test-credentials request.
- Before fix: may connect to rebind target. After fix: connects to originally resolved IP.

---

## Rollout / migration notes

- This change affects only the network connectivity phase of `test_credentials`. Connection string validation and actual DB authentication phases are unaffected.
- TLS hostname verification is not affected if `server_hostname` is passed correctly.
- Rollback: revert to `sock.connect((host, port))`.

**Related findings:** [bigquery-and-snowflake-skip-ssrf-validation](bigquery-and-snowflake-skip-ssrf-validation-proposal.md)
