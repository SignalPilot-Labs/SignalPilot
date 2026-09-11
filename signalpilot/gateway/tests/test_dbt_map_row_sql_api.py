"""dbt-map row TTL cache and the per-model SQL endpoint."""

from __future__ import annotations

import asyncio
import gzip
import json
from types import SimpleNamespace

from gateway.dbt_map import row_cache as row_cache_mod
from gateway.dbt_map.graph_cache import SqlMapCache, sql_map_cache
from gateway.dbt_map.row_cache import RowCache, row_cache
from gateway.dbt_map.sql_slices import SQL_CAP_BYTES, extract_sql_map, sql_payload

from .test_dbt_map_api import URL, harness  # pytest fixture import

POLL = {"include_graph": "false"}


# ── row TTL cache ─────────────────────────────────────────────────────────────


def test_second_poll_within_ttl_skips_the_database(harness):
    client, _graph, storage, _insert = harness
    first = client.get(URL, params=POLL)
    assert first.status_code == 200
    assert storage.db_calls == 2  # project lookup + latest-row query
    again = client.get(URL, params=POLL)
    assert again.status_code == 200 and again.json() == first.json()
    assert storage.db_calls == 2
    # The 304 decision is made from the snapshot alone.
    cached = client.get(URL, params=POLL, headers={"If-None-Match": first.headers["etag"]})
    assert cached.status_code == 304
    assert storage.db_calls == 2
    # An explicit request for the default branch reuses the same snapshot.
    client.get(URL, params={**POLL, "branch": "main"})
    assert storage.db_calls == 2


def test_ttl_expiry_refetches(harness, monkeypatch):
    client, _graph, storage, _insert = harness
    clock = [1000.0]
    monkeypatch.setattr(row_cache_mod, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    client.get(URL, params=POLL)
    assert storage.db_calls == 2
    clock[0] += 4.9
    client.get(URL, params=POLL)
    assert storage.db_calls == 2
    clock[0] += 0.2
    client.get(URL, params=POLL)
    assert storage.db_calls == 4


def test_compile_invalidates_the_row_cache(harness):
    client, _graph, storage, _insert = harness
    assert client.get(URL, params=POLL).json()["status"] == "success"
    asyncio.run(_insert(revision=2, graph_key=None, status="queued"))
    # Still the cached snapshot until a compile is scheduled.
    assert client.get(URL, params=POLL).json()["status"] == "success"
    assert client.post(f"{URL}/compile").status_code == 200
    assert row_cache.stats()["entries"] == 0
    assert client.get(URL, params=POLL).json()["status"] == "queued"


def test_ttl_zero_disables_the_cache(harness, monkeypatch):
    client, _graph, storage, _insert = harness
    monkeypatch.setenv("SP_DBT_MAP_ROW_CACHE_SECONDS", "0")
    client.get(URL, params=POLL)
    client.get(URL, params=POLL)
    assert storage.db_calls == 4
    assert row_cache.stats()["entries"] == 0


def test_row_cache_bounds_and_invalidation():
    cache = RowCache(max_keys=2)
    for i in range(3):
        cache.put(("org", f"p{i}", None), (f"b{i}", None))
    assert cache.get(("org", "p0", None)) is None
    assert cache.get(("org", "p2", None)) == ("b2", None)
    cache.put(("org", "p2", "main"), ("main", None))
    assert cache.invalidate_project("org", "p2") == 2
    assert cache.stats()["entries"] == 0


def test_ttl_env_parsing(monkeypatch):
    monkeypatch.delenv("SP_DBT_MAP_ROW_CACHE_SECONDS", raising=False)
    assert row_cache_mod.ttl_seconds() == 5.0
    monkeypatch.setenv("SP_DBT_MAP_ROW_CACHE_SECONDS", "12")
    assert row_cache_mod.ttl_seconds() == 12.0
    monkeypatch.setenv("SP_DBT_MAP_ROW_CACHE_SECONDS", "junk")
    assert row_cache_mod.ttl_seconds() == 5.0
    monkeypatch.setenv("SP_DBT_MAP_ROW_CACHE_SECONDS", "-3")
    assert row_cache_mod.ttl_seconds() == 0.0


# ── SQL endpoint ──────────────────────────────────────────────────────────────


def _sql_blob(sql_map: dict) -> bytes:
    return gzip.compress(json.dumps(sql_map).encode())


def test_sql_from_artifact(harness):
    client, _graph, storage, _insert = harness
    sql_key, manifest_key = "k/1-sql.json.gz", "k/1-manifest.json.gz"
    storage.blobs[sql_key] = _sql_blob(
        {
            "model.demo.orders": {"raw": "select * from {{ ref('stg_orders') }}", "compiled": "select * from stg", "language": "sql"},
            "model.demo.mart_b": {"raw": "import pandas", "compiled": None, "language": "python"},
        }
    )
    storage.blobs[manifest_key] = gzip.compress(b'{"nodes": {}}')
    asyncio.run(_insert(revision=2, sql_key=sql_key, manifest_key=manifest_key))
    row_cache.clear()

    resp = client.get(f"{URL}/model/model.demo.orders/sql")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "unique_id": "model.demo.orders",
        "name": "orders",
        "path": "orders.sql",
        "original_file_path": "models/orders.sql",
        "language": "sql",
        "raw_sql": "select * from {{ ref('stg_orders') }}",
        "compiled_sql": "select * from stg",
        "source": "artifact",
        "truncated": False,
    }
    assert resp.headers["cache-control"] == "private, max-age=0, must-revalidate"
    assert client.get(f"{URL}/model/model.demo.orders/sql", headers={"If-None-Match": resp.headers["etag"]}).status_code == 304

    python_model = client.get(f"{URL}/model/mart_b/sql").json()
    assert python_model["language"] == "python" and python_model["compiled_sql"] is None
    # Nodes absent from the artifact still answer, with null code.
    assert client.get(f"{URL}/model/dim_x/sql").json()["raw_sql"] is None

    # graph + sql artifact = two S3 reads in total; repeats are memoized.
    assert storage.calls == 2
    client.get(f"{URL}/model/model.demo.orders/sql")
    assert storage.calls == 2
    assert sql_map_cache.stats() == {"entries": 1, "loads": 1}


def test_sql_falls_back_to_manifest(harness):
    client, _graph, storage, _insert = harness
    manifest_key = "k/2-manifest.json.gz"
    manifest = {
        "metadata": {},
        "nodes": {
            "model.demo.mart_a": {"resource_type": "model", "raw_code": "select a", "compiled_code": None, "language": "sql"},
            "test.demo.unique_mart_a_id": {"resource_type": "test", "raw_code": "select bad", "language": "sql"},
        },
        "sources": {},
    }
    storage.blobs[manifest_key] = gzip.compress(json.dumps(manifest).encode())
    asyncio.run(_insert(revision=2, manifest_key=manifest_key))
    row_cache.clear()

    body = client.get(f"{URL}/model/mart_a/sql").json()
    assert body["source"] == "manifest"
    assert body["raw_sql"] == "select a" and body["compiled_sql"] is None
    cached = sql_map_cache.get(manifest_key)
    assert set(cached) == {"model.demo.mart_a"}  # tests are never extracted
    assert storage.calls == 2
    client.get(f"{URL}/model/mart_a/sql")
    assert storage.calls == 2


def test_sql_error_cases(harness):
    client, _graph, storage, _insert = harness
    # Default row: no sql_key and no manifest_key.
    assert client.get(f"{URL}/model/mart_a/sql").status_code == 404
    assert client.get(f"{URL}/model/nothing/sql").status_code == 404
    ambiguous = client.get(f"{URL}/model/orders/sql")
    assert ambiguous.status_code == 409
    assert ambiguous.json()["detail"]["candidates"] == ["model.demo.orders", "model.other.orders"]
    source = client.get(f"{URL}/model/source.demo.raw.orders/sql")
    assert source.status_code == 404 and "source" in source.json()["detail"]
    test_node = client.get(f"{URL}/model/test.demo.unique_mart_a_id/sql")
    assert test_node.status_code == 404 and "not a model" in test_node.json()["detail"]


def test_sql_payload_caps_each_string():
    node = {"name": "big", "path": "big.sql", "original_file_path": "models/big.sql"}
    entry = {"raw": "x" * (SQL_CAP_BYTES + 10), "compiled": "ok", "language": "sql"}
    body = sql_payload("model.demo.big", node, entry, "artifact")
    assert body["truncated"] is True
    assert len(body["raw_sql"].encode()) == SQL_CAP_BYTES
    assert body["compiled_sql"] == "ok"
    small = sql_payload("model.demo.big", node, {"raw": "select 1"}, "artifact")
    assert small["truncated"] is False and small["language"] == "sql"


def test_extract_sql_map_shape():
    nodes = {
        "model.demo.a": {"resource_type": "model", "raw_code": "r", "compiled_code": "c", "language": "sql"},
        "seed.demo.s": {"resource_type": "seed", "raw_code": ""},
        "test.demo.t": {"resource_type": "test", "raw_code": "t"},
        "unit_test.demo.u": {"resource_type": "unit_test"},
    }
    assert extract_sql_map(nodes) == {
        "model.demo.a": {"raw": "r", "compiled": "c", "language": "sql"},
        "seed.demo.s": {"raw": "", "compiled": None, "language": "sql"},
    }


def test_sql_map_cache_lru_and_budget():
    async def _run():
        blob = _sql_blob({"m": {"raw": "select 1", "compiled": None, "language": "sql"}})

        async def _load():
            return blob

        cache = SqlMapCache(max_entries=2)
        for key in ("a", "b", "c"):
            await cache.get_or_load(key, _load, json.loads)
        assert cache.get("a") is None and cache.get("c") is not None

        async def _none():
            return None

        assert await cache.get_or_load("missing", _none, json.loads) is None
        assert cache.stats()["entries"] == 2

    asyncio.run(_run())
