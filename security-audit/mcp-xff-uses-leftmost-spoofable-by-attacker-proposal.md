# MCP audit logs trust leftmost X-Forwarded-For — attacker-controlled value goes straight into the audit trail

- Slug: mcp-xff-uses-leftmost-spoofable-by-attacker
- Severity: Medium
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/mcp_auth.py:255-269`, `signalpilot/gateway/gateway/middleware.py:276-282`

Back to [issues.md](issues.md)

---

## Problem

Two locations extract the client IP and they disagree on which side of the `X-Forwarded-For` chain to trust:

```python
# mcp_auth.py:259-261 — LEFTMOST (client-controlled)
if name.lower() == b"x-forwarded-for":
    return value.decode("latin-1").split(",")[0].strip()

# middleware.py:280-281 — RIGHTMOST (closest proxy)
if forwarded:
    return forwarded.split(",")[-1].strip()
```

The MCP path uses the leftmost value, which is the original client-claimed IP. Any client can prepend an arbitrary first hop:

```
X-Forwarded-For: 8.8.8.8, real-client-ip
```

The MCP middleware records `8.8.8.8` as the client IP and writes it into:

- The MCP audit log entry (`sandbox_audit` log lines via `mcp_client_ip_var`).
- Per-IP rate limit buckets in MCP-adjacent code paths.
- Any audit row created via `store.append_audit` from MCP tool handlers (carries `client_ip` field).

Round-1 finding 46 noted the inconsistency in passing, but did not call out that the MCP side is *attacker-controllable* (not just trusted-proxy-dependent). This is a separate, higher-confidence issue: even with a trusted proxy in front, the MCP code still picks the wrong end of the chain.

---

## Impact

- Audit trail integrity: MCP-tool actions can be attributed to a forged IP. A malicious tenant can blame an arbitrary IP for every action they take, undermining incident response and forensic correlation.
- Rate limit bypass: if any MCP-adjacent rate limiter keys on `_extract_client_ip(scope)`, an attacker varies the leftmost XFF token to spread requests across many synthetic "clients."
- Compliance: SOC 2 / HIPAA / PCI logs become unreliable for the MCP transport; an auditor checking source-IP can be misled.

---

## Exploit scenario

1. Attacker authenticates to `gateway.signalpilot.ai/mcp` with a stolen API key.
2. Each tool invocation includes `X-Forwarded-For: <victim-ip>, ...`.
3. MCP audit rows show the queries originated from `<victim-ip>`.
4. When the breach is discovered, the victim's IP appears in the audit trail and the attacker's real IP does not — even though the gateway sits behind a trusted proxy that appended the real IP to the right side.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/mcp_auth.py:255-269`.
- Endpoints: anything routed through `MCPAuthMiddleware`, which is mounted at the root (`main.py:331`) — i.e. all MCP tool calls.
- Auth modes: any authenticated MCP request.

---

## Proposed fix

- Unify XFF parsing into a single helper module (`gateway/client_ip.py`) used by both `middleware.py` and `mcp_auth.py`.
- The helper takes the *rightmost* XFF entry, but only after asserting `scope["client"]` (the immediate peer) is in a trusted proxy CIDR list (`SP_TRUSTED_PROXIES`).
- If the peer is not trusted, ignore XFF entirely and use the peer IP.
- Document the deployment expectation: gateway is always reached via a known proxy whose CIDR is in `SP_TRUSTED_PROXIES`.

This finding pairs with finding 46 (no trusted-proxy-list at all). They should be fixed together.

---

## Verification / test plan

- Unit: `tests/test_client_ip.py::test_mcp_picks_rightmost_when_peer_trusted`.
- Unit: assert leftmost value is never returned when XFF has `>1` entry.
- Integration: send a request with `X-Forwarded-For: 1.1.1.1, 2.2.2.2` from a peer outside `SP_TRUSTED_PROXIES`; assert audit row records the peer IP, not `1.1.1.1`.

---

## Rollout / migration notes

- Requires operators to set `SP_TRUSTED_PROXIES` (CIDR list) for the platform LB / ingress.
- Cloud deploy step: roll out trusted proxies env var first, then ship the new helper.
- Rollback: revert helper; the inconsistency returns but no data is lost.
