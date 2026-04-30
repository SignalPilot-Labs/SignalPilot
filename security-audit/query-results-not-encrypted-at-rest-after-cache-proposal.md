# `schema_cache` and result caches store potentially-sensitive query output in process memory (and possibly disk) without encryption

- Slug: query-results-not-encrypted-at-rest-after-cache
- Severity: Low
- Cloud impact: Yes
- Confidence: Medium
- Affected files / endpoints: `signalpilot/gateway/gateway/connectors/schema_cache.py`, `signalpilot/gateway/gateway/governance/cache.py`

Back to [issues.md](issues.md)

---

## Problem

Schema information (column names, table names, potentially sample values) and query result metadata are cached in process memory. Two caches were cited for review:

1. **`schema_cache.py`:** Caches schema information (table names, column names, data types) per connection per org. Schema information may include column names that reveal business context (e.g., `salary`, `ssn`, `credit_card_number`), and some schema discovery queries return sample data.

2. **`governance/cache.py`:** Caches governance-related data including query validation results, budget state, and potentially query results for repeated identical queries.

Issues:
1. **Memory-only is acceptable for ephemeral containers**, but containers without `prctl(PR_SET_DUMPABLE, 0)` can leak memory via `/proc/{pid}/mem` if a process-level vulnerability allows arbitrary read.
2. **No cross-tenant isolation check.** If the cache uses connection name as the key without including `org_id`, two different orgs with the same connection name (e.g., both named `"prod"`) could share cached schema data.
3. **Core dumps.** If `ulimit -c unlimited` is set (the default in some container environments), a crash produces a core dump containing all cached plaintext data.

Confidence is Medium because the full cache implementation was not read in detail.

---

## Impact

- A process-level memory read vulnerability (or a core dump) exposes cached schema data.
- Cross-tenant schema cache sharing (if org_id is not part of the cache key) leaks one tenant's schema to another.
- The risk is low for typical containers but non-trivial for long-running gateway processes with many active connections.

---

## Exploit scenario

**Core dump scenario:**
1. A memory corruption bug (hypothetical) in a Python C extension (e.g., `duckdb`, `pyarrow`) causes a segfault.
2. If `ulimit -c unlimited` is set, a core dump is written to disk.
3. Attacker (or a compromised sidecar) reads the core dump.
4. Core dump contains all in-memory cached schema data and query results in plaintext.

**Cross-tenant cache scenario (if org_id not in key):**
1. Org A has a connection named `"prod"` pointing to their Postgres.
2. Org B also has a connection named `"prod"` pointing to their Postgres.
3. Both connections are cached. If the cache key is only `"prod"` without org_id, Org B sees Org A's schema.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/connectors/schema_cache.py`, `signalpilot/gateway/gateway/governance/cache.py`
- Endpoints: All query endpoints (caches serve query infrastructure)
- Auth modes: Cloud and local

---

## Proposed fix

1. **Disable core dumps in the container entrypoint:**

```dockerfile
# Dockerfile.gateway:
ENTRYPOINT ["/bin/sh", "-c", "ulimit -c 0 && exec uvicorn gateway.main:app --host 0.0.0.0 --port 3300"]
```

Or in Kubernetes:

```yaml
securityContext:
  allowPrivilegeEscalation: false
  # Core dumps disabled via ulimit in entrypoint
```

2. **Verify the schema cache key includes `org_id`:**

```python
# schema_cache.py — verify key format:
def _cache_key(self, org_id: str, connection_name: str) -> str:
    return f"{org_id}:{connection_name}"  # org_id must be included
```

Review `cache.py:42` (referenced in the spec) to confirm the org_id refactor is complete.

3. **Set a TTL on cached schema data** to limit the window of exposure:

```python
SCHEMA_CACHE_TTL_SECONDS = 300  # 5 minutes
```

---

## Verification / test plan

**Unit tests:**
1. `test_schema_cache_key_includes_org_id` — assert cache key format is `{org_id}:{connection_name}`.
2. `test_cross_tenant_cache_isolation` — two orgs with same connection name, assert distinct cache entries.

**Manual checklist:**
- Start gateway container.
- Check `ulimit -c` inside container: should return `0` after fix.
- Simulate cache key: confirm org_id is part of every cache lookup key.

---

## Rollout / migration notes

- Setting `ulimit -c 0` has no performance impact and does not affect functionality.
- Cache key changes invalidate existing cache entries (empty cache on deploy) — negligible performance impact.
- Rollback: remove `ulimit -c 0` from entrypoint; revert cache key changes.
