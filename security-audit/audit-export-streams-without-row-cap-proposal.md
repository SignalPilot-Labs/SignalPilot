# `POST /api/audit/export` may stream unbounded rows

- Slug: audit-export-streams-without-row-cap
- Severity: Low
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/api/audit.py:70-120`

Back to [issues.md](issues.md)

---

## Problem

The audit export endpoint uses `limit=1_000_000` as a hard-coded cap:

```python
# api/audit.py:82-87
entries = await store.read_audit(
    limit=1_000_000,
    offset=0,
    connection_name=connection_name,
    event_type=event_type,
)
```

While `1_000_000` is a hard cap (not truly unbounded), problems remain:

1. **1 million rows is a de-facto DoS.** A large org that has executed 1 million queries can trigger this endpoint and cause:
   - 1 million DB rows loaded into Python memory simultaneously.
   - All rows serialized to JSON or CSV in memory.
   - The result streamed to the client as a single `StreamingResponse` (but `iter([content])` — the entire content is computed in memory before streaming begins).
2. **No server-side pagination for exports.** The caller cannot request a page of the export; the entire export is computed in one pass.
3. **No timeout.** A 1-million-row query may run for minutes, holding an async DB connection and memory for the duration.
4. **`iter([content])` is not truly streaming.** The CSV content is built in memory (`io.StringIO`), then wrapped in `iter(...)`. For very large exports, this is a memory spike, not a stream.

---

## Impact

- An admin user (with `admin` scope) can trigger a memory-intensive operation that blocks gateway resources for several minutes.
- For orgs with very large audit logs: OOM in the gateway process; affects all other tenants sharing the process.
- Not a privilege escalation — requires `admin` scope — but is a Denial of Service.

---

## Exploit scenario

1. Attacker has admin-level API key for their own org (legitimate).
2. Org has 800,000 audit log entries.
3. Attacker calls `GET /api/audit/export`:

```bash
curl https://gateway.signalpilot.ai/api/audit/export \
  -H "X-API-Key: sp_admin_key"
# Gateway loads 800,000 rows into memory, serializes ~500MB of CSV
# Gateway process memory spikes, potentially causing OOM
# All other tenants experience 503 during this window
```

---

## Affected surface

- Files: `signalpilot/gateway/gateway/api/audit.py:70-120`
- Endpoints: `GET /api/audit/export`
- Auth modes: Requires `admin` scope

---

## Proposed fix

1. **Add a hard row cap per export request** with a client-side pagination option:

```python
# api/audit.py — updated:
MAX_EXPORT_ROWS = 50_000  # Configurable via env var

@router.get("/audit/export", dependencies=[RequireScope("admin")])
async def export_audit(
    store: StoreD,
    limit: int = Query(default=MAX_EXPORT_ROWS, ge=1, le=MAX_EXPORT_ROWS),
    offset: int = Query(default=0, ge=0),
    connection_name: str | None = Query(default=None, max_length=64),
    event_type: str | None = Query(default=None, max_length=64),
    format: str = Query(default="json", pattern=r"^(json|csv)$"),
):
    entries = await store.read_audit(
        limit=limit,
        offset=offset,
        connection_name=connection_name,
        event_type=event_type,
    )
```

2. **Use true server-side streaming** for CSV export instead of building in memory:

```python
# True streaming CSV generation:
async def _stream_csv(rows) -> AsyncIterator[str]:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([...header...])
    yield output.getvalue()
    output = io.StringIO()

    for row in rows:
        writer = csv.writer(output)
        writer.writerow([...row data...])
        yield output.getvalue()
        output = io.StringIO()

return StreamingResponse(_stream_csv(entries), media_type="text/csv", ...)
```

3. **Add a timeout** on the export query:

```python
async with asyncio.timeout(30):  # 30-second timeout for export
    entries = await store.read_audit(...)
```

---

## Verification / test plan

**Unit tests:**
1. `test_export_limited_to_max_rows` — org with 100k entries, assert response has ≤50k rows.
2. `test_export_pagination_offset` — offset=50000, assert correct slice returned.
3. `test_export_timeout` — mock slow DB, assert 504 after timeout.

**Manual checklist:**
- Create org with 60k audit entries.
- Call export with default `limit`.
- Verify response contains ≤50k rows (not 60k).
- Verify `X-Total-Count` response header shows 60k (pagination metadata).

---

## Rollout / migration notes

- The row cap changes behavior for orgs with large audit logs. Communicate via release notes.
- Provide guidance on using `offset` for full exports.
- Rollback: revert to `limit=1_000_000`.
