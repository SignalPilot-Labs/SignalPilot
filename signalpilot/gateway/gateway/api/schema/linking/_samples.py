"""Best-effort sample value fetching for schema linking — populates schema_cache as a side effect."""

from __future__ import annotations

from typing import Any

from gateway.api.schema.linking._data import _STRING_TYPES
from gateway.connectors.pool_manager import pool_manager
from gateway.connectors.schema_cache import schema_cache

# Hold strong refs to in-flight proactive sample tasks so the event loop does not
# garbage-collect them mid-run ("Task was destroyed but it is pending").
_bg_sample_tasks: set = set()


async def maybe_fetch_missing_samples(
    store: Any,
    info: Any,
    name: str,
    linked_keys: set[str],
    filtered: dict[str, Any],
    schema_cache_ref: Any = None,
) -> None:
    """Proactively fetch sample values for linked tables that lack cached samples.

    Pure side effect on schema_cache — never raises. Next schema_link call will
    include inline samples in DDL annotations.

    Args:
        store: The Store instance (used for get_connection_string / get_credential_extras).
        info: Connection info object (has db_type attribute).
        name: Connection name.
        linked_keys: Set of table keys to check.
        filtered: Full filtered schema dict.
        schema_cache_ref: Unused; present for interface symmetry (schema_cache is module-level).
    """
    missing_samples = []
    for key in linked_keys:
        if key not in filtered:
            continue
        if schema_cache.get_sample_values(name, key) is not None:
            continue  # Already cached
        t = filtered[key]
        sample_cols = [
            c["name"]
            for c in t.get("columns", [])
            if c.get("type", "") in _STRING_TYPES or "char" in c.get("type", "").lower()
        ]
        if sample_cols:
            missing_samples.append((key, t, sample_cols[:10]))

    if not missing_samples:
        return

    # This fetch is PURELY PROACTIVE — it populates schema_cache so the NEXT
    # schema_link call can inline samples. It does NOT affect the current
    # response, so we must not block on it (sampling a view forces full
    # execution and can take many seconds). Resolve the store-dependent values
    # now (the session is alive here), then run the slow sampling as a
    # fire-and-forget background task with a per-sample timeout.
    import asyncio

    try:
        conn_str = await store.get_connection_string(name)
    except Exception:
        return
    if not conn_str:
        return
    try:
        extras = await store.get_credential_extras(name)
    except Exception:
        return

    db_type = info.db_type
    targets = missing_samples[:5]  # cap at 5 tables

    async def _fetch_samples_bg() -> None:
        try:
            async with pool_manager.connection(
                db_type, conn_str, credential_extras=extras, connection_name=name
            ) as connector:
                for key, t, sample_cols in targets:
                    table_name = f"{t.get('schema', '')}.{t['name']}" if t.get("schema") else t["name"]
                    try:
                        values = await asyncio.wait_for(
                            connector.get_sample_values(table_name, sample_cols, limit=5),
                            timeout=2.0,  # skip tables (e.g. heavy views) too slow to sample
                        )
                        if values:
                            schema_cache.put_sample_values(name, key, values)
                    except Exception:
                        pass  # best-effort per table
        except Exception:
            pass  # best-effort — never affects a response

    # Schedule and return immediately; the task outlives this request on the loop.
    task = asyncio.create_task(_fetch_samples_bg())
    _bg_sample_tasks.add(task)
    task.add_done_callback(_bg_sample_tasks.discard)
