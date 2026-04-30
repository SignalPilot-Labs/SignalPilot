# `signalpilot-shared` volume carries the local API key between gateway and web containers — broad blast radius if either is compromised

**Status:** DEPRIORITIZED — feature disabled in cloud as of 2026-04-30; owner not actively maintaining. Severity rating retained to reflect technical risk; treat as low-priority until the feature is re-enabled.

- Slug: shared-volume-leaks-local-api-key-between-containers
- Severity: Low
- Cloud impact: No (local stack only)
- Confidence: High
- Affected files / endpoints: `docker-compose.yml:38-46,55-58`

Back to [issues.md](issues.md)

---

## Problem

```yaml
# docker-compose.yml:38-46 (gateway)
volumes:
  - signalpilot-data:/data
  - signalpilot-shared:/shared
command: >
  sh -c "python3 -c \"from gateway.store import get_local_api_key;
  open('/shared/local_api_key','w').write(get_local_api_key())\" &&
  uvicorn gateway.main:app --host 0.0.0.0 --port 3300"

# docker-compose.yml:55-58 (web)
volumes:
  - signalpilot-shared:/shared:ro
```

The gateway writes the local API key (32 hex chars after `sp_local_`) to a Docker named volume which the web container mounts read-only. The web container reads the key and serves it over `/api/local-key` (finding 32) for in-browser auth.

Two issues:

1. **Volume persists across stack restarts.** The local API key is generated once and written to `/shared/local_api_key`. If the operator runs `docker compose down` (without `-v`), the volume — and key — survives. If the operator later attaches a forensic container or another tool that mounts `signalpilot-shared`, the key is exposed.
2. **Plaintext on disk.** The file has no permission mode set explicitly; it inherits Docker's default (root, 0644). Any process inside either container can read it. Combined with finding 38 (gateway runs as root), an RCE in either container yields the key in cleartext.

This is a defense-in-depth concern that pairs with finding 32 (`/api/local-key` returns the key with no auth).

---

## Impact

- An attacker with shell on the web container reads `/shared/local_api_key` and authenticates to the gateway as `local`/`local`.
- The shared volume is a covert channel: anything either container writes to `/shared` is readable by the other.
- Operators who copy the compose file into a CI environment may inadvertently persist the key in CI's volume retention.

---

## Exploit scenario

1. Compromised web container (e.g. via XSS-induced SSRF to a malicious npm package's postinstall script).
2. Read `/shared/local_api_key`.
3. Authenticate to `http://gateway:3300/api/keys` and create a long-lived key with `admin` scope.
4. Persist the key off-cluster.

---

## Affected surface

- Files: `docker-compose.yml:38-46,55-58`.
- Auth modes: local docker-compose only.

---

## Proposed fix

- Stop putting the key on disk. Use a Docker secret (`secrets:` block in compose) or have the web container fetch the key once at startup via a private gateway endpoint protected by a startup token.
- Alternatively: write the key to `/shared/local_api_key` with `umask 0077`, rotate on every gateway restart, and `chmod 0400` after write.
- Document that `docker compose down -v` must be run when offloading the stack.
- Strip the key from any docker volume backups.

---

## Verification / test plan

- Manual: `docker compose down`, `docker compose up`; verify a fresh key is generated.
- Manual: `docker exec web cat /shared/local_api_key` should fail (file no longer readable as web's user) once fix is in place.
- Unit: integration test that ensures the gateway rejects a stale local key after restart.

---

## Rollout / migration notes

- Local-only; no production impact.
- Rollback: revert volume strategy; non-destructive.
