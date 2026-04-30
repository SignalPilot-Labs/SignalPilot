# `docker-compose.yml` ships `POSTGRES_USER=signalpilot / PASSWORD=signalpilot` and exposes 5432→5601 on host

- Slug: docker-compose-default-postgres-credentials
- Severity: Low
- Cloud impact: Partial
- Confidence: High
- Affected files / endpoints: `docker-compose.yml:11-26`

Back to [issues.md](issues.md)

---

## Problem

The development `docker-compose.yml` ships hardcoded weak credentials and exposes the Postgres port on the host:

```yaml
# docker-compose.yml:11-26
services:
  db:
    image: postgres:17
    environment:
      POSTGRES_USER: signalpilot
      POSTGRES_PASSWORD: signalpilot
      POSTGRES_DB: signalpilot
    ports:
      - "5601:5432"  # Host port 5601 mapped to Postgres
```

Problems:
1. **Hardcoded predictable credentials.** `signalpilot/signalpilot` is the first credential an attacker will try after recognizing this is a SignalPilot deployment.
2. **Host port exposure.** Port 5601 is bound on all interfaces (`0.0.0.0:5601`). Any device that can reach the host can connect to Postgres with the default credentials.
3. **Copy-paste risk.** Operators commonly copy `docker-compose.yml` as the basis for production deployments (`docker-compose.prod.yml`). If they forget to change credentials and remove the port mapping, the production DB is exposed.
4. **No `docker-compose.prod.yml` provided.** Without a production template, operators have no reference for what must be changed.

---

## Impact

- **Local mode:** Low risk — developer machine likely has a firewall blocking port 5601 from external access. But on a shared corporate network or cloud VM, port 5601 is accessible to all.
- **Cloud misconfig:** If an operator deploys the `docker-compose.yml` directly to a cloud VM, Postgres is exposed on the internet with known credentials. An attacker can access all gateway data including encrypted credentials (and attempt to crack the Fernet key).

---

## Exploit scenario

1. Operator deploys SignalPilot to a cloud VM using the provided `docker-compose.yml` without changes.
2. VM's security group allows inbound port 5601 (operator forgot to restrict it).
3. Attacker runs:

```bash
psql -h victim-vm-ip -p 5601 -U signalpilot -d signalpilot
# Password: signalpilot
# Full DB access — reads all encrypted credentials, audit logs, API key hashes
```

4. Attacker reads `gateway_api_keys` table and extracts key hashes and prefixes.
5. Attacker reads `gateway_connections` and `gateway_byok_keys` encrypted columns.
6. If `SP_ENCRYPTION_KEY` is also weak (see finding [sp-encryption-key-derivation-allows-passphrase-with-deterministic-salt](sp-encryption-key-derivation-allows-passphrase-with-deterministic-salt-proposal.md)), credentials can be decrypted.

---

## Affected surface

- Files: `docker-compose.yml:11-26`
- Endpoints: Postgres port 5601
- Auth modes: Not applicable (DB direct access)

---

## Proposed fix

1. **Change the default dev credentials** to something non-trivial:

```yaml
# docker-compose.yml:
environment:
  POSTGRES_USER: ${POSTGRES_USER:-sp_dev}
  POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}
  POSTGRES_DB: ${POSTGRES_DB:-signalpilot_dev}
```

Or use a generated password:
```yaml
  POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-$(openssl rand -hex 16)}
```

2. **Restrict the port binding to localhost:**

```yaml
ports:
  - "127.0.0.1:5601:5432"  # Loopback only
```

3. **Provide a `docker-compose.prod.yml`** with no port bindings, secrets-required, and explicit instructions:

```yaml
# docker-compose.prod.yml:
services:
  db:
    ports: []  # No host port binding in production
    environment:
      POSTGRES_USER: ${POSTGRES_USER:?}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?}
      POSTGRES_DB: ${POSTGRES_DB:?}
```

4. **Add a warning comment** in `docker-compose.yml`:

```yaml
# WARNING: This file is for LOCAL DEVELOPMENT ONLY.
# Do NOT use in production without:
# 1. Changing POSTGRES_PASSWORD to a strong random value
# 2. Removing the `ports` mapping for the db service
# 3. Using docker-compose.prod.yml as your production base
```

---

## Verification / test plan

**Manual checklist:**
- Start stack with defaults.
- Attempt `psql -h 127.0.0.1 -p 5601 -U sp_dev signalpilot_dev` — should prompt for password.
- Attempt from external network — should be refused (loopback bind).

---

## Rollout / migration notes

- Existing local deployments with the old credentials must update their `.env` files.
- The `DATABASE_URL` in the gateway service must be updated to match new credentials.
- Rollback: revert credential and port binding changes.
