# `_extract_client_ip` and rate-limit IP take rightmost X-Forwarded-For value but no trusted proxy validation

- Slug: client-ip-trust-x-forwarded-for-without-trusted-proxy-list
- Severity: Low
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/mcp_auth.py:255-269`, `signalpilot/gateway/gateway/middleware.py:276-282`

Back to [issues.md](issues.md)

---

## Problem

Two separate locations read `X-Forwarded-For` to extract the client IP, but with different strategies:

```python
# mcp_auth.py:259-261 — takes the FIRST IP (leftmost)
if name.lower() == b"x-forwarded-for":
    return value.decode("latin-1").split(",")[0].strip()

# middleware.py:277-281 — takes the LAST IP (rightmost)
forwarded = request.headers.get("x-forwarded-for")
if forwarded:
    return forwarded.split(",")[-1].strip()
```

**Inconsistency:** `mcp_auth.py` uses the leftmost (client-claimed) IP, while `middleware.py` uses the rightmost (closest proxy). The rightmost approach is more attack-resistant, but only if the gateway is always behind a trusted proxy. The leftmost approach is completely spoofable by any client.

**No trusted proxy validation:** Neither location validates that the `X-Forwarded-For` header was added by a trusted proxy. Without this validation:
- In `mcp_auth.py`: any client can spoof the IP (e.g., add `X-Forwarded-For: 192.168.1.1` to appear as an internal IP).
- In `middleware.py`: if the gateway is briefly exposed without a proxy (e.g., during a maintenance window), attackers control the entire `X-Forwarded-For` chain.

The spoofed IP is used for:
- Audit log attribution (wrong IP in audit log).
- Rate limiting (bypass per-IP rate limits by spoofing different IPs).
- Geographic or network-based access controls (if implemented in the future).

---

## Impact

- **Rate limit bypass:** Attacker sends different `X-Forwarded-For` headers to appear as different IPs, bypassing per-IP rate limits.
- **Audit log poisoning:** Audit entries show attacker-chosen IPs instead of the real client IP.
- **IP-based access control bypass:** If the gateway adds IP allowlists in the future, the existing spoofable IP extraction makes them bypassable.

---

## Exploit scenario

**Rate limit bypass (middleware.py — leftmost variant):**
```bash
# Attacker cycles through fake IPs to bypass per-IP rate limit:
for i in $(seq 1 1000); do
  curl https://gateway.signalpilot.ai/api/query \
    -H "X-Forwarded-For: 10.0.0.$i" \
    -H "X-API-Key: sp_stolen_key" \
    -H "Content-Type: application/json" \
    -d '...'
done
# Each request appears to come from a different IP
```

**IP spoofing in mcp_auth.py (takes leftmost):**
```bash
curl https://gateway.signalpilot.ai/mcp \
  -H "X-Forwarded-For: 127.0.0.1" \
  -H "X-API-Key: sp_key"
# Audit log shows client IP = 127.0.0.1 (loopback)
```

---

## Affected surface

- Files: `signalpilot/gateway/gateway/mcp_auth.py:255-269`, `signalpilot/gateway/gateway/middleware.py:276-282`
- Endpoints: All endpoints (rate limiting applies globally; MCP audit applies to MCP requests)
- Auth modes: Cloud and local

---

## Proposed fix

Implement trusted proxy validation:

```python
# network_validation.py (or new module) — add:
import ipaddress

def _get_trusted_proxy_cidrs() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Load trusted proxy CIDRs from SP_TRUSTED_PROXIES env var."""
    raw = os.environ.get("SP_TRUSTED_PROXIES", "")
    if not raw:
        return []
    cidrs = []
    for cidr in raw.split(","):
        cidr = cidr.strip()
        try:
            cidrs.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            logger.warning("Invalid CIDR in SP_TRUSTED_PROXIES: %s", cidr)
    return cidrs

def extract_real_client_ip(
    direct_ip: str,
    x_forwarded_for: str | None,
    trusted_cidrs: list[...],
) -> str:
    """Return the real client IP, peeling off trusted proxy hops."""
    if not x_forwarded_for or not trusted_cidrs:
        return direct_ip
    
    parts = [p.strip() for p in x_forwarded_for.split(",")]
    # Walk from right (closest proxy) to left, skip trusted proxies
    while parts:
        rightmost = parts[-1]
        try:
            addr = ipaddress.ip_address(rightmost)
            if any(addr in cidr for cidr in trusted_cidrs):
                parts.pop()  # Trusted proxy, skip
                continue
        except ValueError:
            pass
        return rightmost  # First non-trusted address from the right
    return direct_ip  # All hops were trusted proxies — use direct IP
```

Update both `mcp_auth.py` and `middleware.py` to use this common function.

**Env var:** `SP_TRUSTED_PROXIES=10.0.0.0/8,172.16.0.0/12,100.64.0.0/10` (Kubernetes pod CIDR, internal LB CIDR).

---

## Verification / test plan

**Unit tests:**
1. `test_real_ip_from_untrusted_proxy` — direct IP not in trusted CIDRs, no XFF trust.
2. `test_real_ip_peels_trusted_proxy` — `XFF: client,trusted-proxy`, direct IP = trusted proxy → returns client.
3. `test_ip_spoofing_blocked` — `XFF: spoofed-ip`, direct IP not trusted → returns direct IP (not spoofed).

---

## Rollout / migration notes

- Set `SP_TRUSTED_PROXIES` to the gateway's load balancer / ingress controller CIDR.
- In Kubernetes: use the pod CIDR of the ingress controller namespace.
- Without configuration, behavior defaults to using the direct connection IP (safe but loses X-Forwarded-For information).
- Rollback: revert to current leftmost/rightmost approaches.
