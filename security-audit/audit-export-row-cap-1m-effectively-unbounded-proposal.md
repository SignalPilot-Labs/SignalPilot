# `/api/audit/export` passes `limit=1_000_000` — effectively unbounded for any active org

- Slug: audit-export-row-cap-1m-effectively-unbounded
- Severity: Low
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/api/audit.py:80-97`

Back to [issues.md](issues.md)

---

## Problem

```python
# api/audit.py:80-87
entries = await store.read_audit(
    limit=1_000_000,
    offset=0,
    connection_name=connection_name,
    event_type=event_type,
)
```

The hard-coded `limit=1_000_000` is treated as "unbounded" but in fact it materializes up to a million `AuditEntry` rows in process memory, then serializes them into JSON / CSV via `iter([content])` — a single chunk in a `StreamingResponse`. The response is *not* actually streamed; it is fully built before being yielded.

For a 100k-row org, the gateway holds the full audit set in RAM twice (once as ORM rows, once as the JSON string). For a 1M-row org, this OOMs the gateway worker. There is no per-org row count check, no Content-Length-based abort, and no time-budget.

This expands round-1 finding 55 with the specific limit value and the non-streaming behavior.

---

## Impact

- Self-DoS by any tenant admin: a single export call by a customer with a large audit history can crash the gateway pod (depending on memory limits).
- Memory pressure across replicas: when one worker OOMs, the load shifts to siblings; cascading restarts.
- No graceful pagination: customers cannot reliably export.

---

## Exploit scenario

1. Tenant admin writes a script that runs `INSERT INTO ...` on a connection or simply executes 50k MCP tool calls (each adds one audit row).
2. Same admin calls `POST /api/audit/export?format=json`.
3. Gateway worker memory grows until OOMKill; `/api/audit/export` returns 502 from the LB.
4. Repeat to keep one replica in restart loop.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/api/audit.py:80-97`.
- Endpoints: `GET /api/audit/export`.
- Auth modes: requires `admin` scope.

---

## Proposed fix

- Replace the in-memory build with a true streaming response: yield rows from a server-side cursor, write JSON/CSV chunk-by-chunk via `aiofiles`-style or `asyncpg.Cursor`.
- Cap exports per request to e.g. 100k rows; for larger exports require a date range.
- Return `Content-Disposition` with a hash of the filters so clients can resume.
- Add a per-org rate limit (`SP_AUDIT_EXPORT_RPM`, default 1/hour).
- Surface a `total_available` counter so clients know to paginate.

---

## Verification / test plan

- Unit: `tests/test_audit_export.py::test_export_streams_without_loading_all` — assert peak memory under e.g. 50 MB for a synthetic 1M-row org.
- Manual: seed 250k rows, call export, watch RSS.
- Fixed when: peak memory grows linearly with output buffer size, not with row count.

---

## Rollout / migration notes

- Customer-visible: the export endpoint may now require pagination; document the new shape (`?cursor=...`).
- Rollback: revert to in-memory build; existing customers unaffected.
