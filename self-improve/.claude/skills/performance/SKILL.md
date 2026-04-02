---
description: "Use when optimizing performance, fixing connection pooling, reducing latency, or profiling. Covers the gateway, database connectors, and sandbox execution."
---

# Performance Optimization

## Known Hot Paths

1. **SQL validation** — every query goes through `validate_sql()`, must be fast
2. **Database connections** — currently creates a new pool per query (N+1 pool problem)
3. **Sandbox execution** — cold boot ~1600ms, snapshot restore ~200-300ms

## Connection Pooling Fix

The postgres connector creates a new pool per query and destroys it after. Fix:

```python
# Module-level pool, created once
_pools: dict[str, asyncpg.Pool] = {}

async def get_pool(dsn: str) -> asyncpg.Pool:
    if dsn not in _pools:
        _pools[dsn] = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
    return _pools[dsn]
```

## Profiling Commands

```bash
# Python profiling
python -m cProfile -s cumulative -m gateway.main
# or use py-spy for live profiling
pip install py-spy && py-spy top -- python -m gateway.main
```

## Database Performance

- Use `EXPLAIN ANALYZE` on slow queries
- Check for missing indexes on frequently-queried columns
- Use connection pooling (asyncpg pools, not per-query connections)
- Batch small operations instead of N individual queries

## Startup Time

- Lazy-load heavy dependencies (sqlglot, faker)
- Pre-warm connection pools on startup
- Use Firecracker snapshots over cold boots

## Benchmarking

Run the Spider2 benchmark to measure text-to-SQL accuracy:

```bash
python -m benchmark run --limit 5  # Quick test
python -m benchmark run            # Full suite
```
