"""dbt-map read API: ETag/304, gzip envelopes, payload variants, graph cache."""

from __future__ import annotations

import asyncio
import gzip
import json
import time
import uuid

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.middleware.base import BaseHTTPMiddleware

from gateway.api import dbt_map as dbt_map_api
from gateway.api.deps import get_store, require_projects_feature
from gateway.db.models import GatewayBase, GatewayDbtManifest
from gateway.dbt_map.graph_cache import GraphCache, graph_cache, sql_map_cache
from gateway.dbt_map.row_cache import row_cache
from gateway.dbt_map.runner import distill_graph
from gateway.dbt_map.slices import build_cone, build_skeleton, resolve_ref
from gateway.http.middleware.security_headers import SecurityHeadersMiddleware
from gateway.security.scope_guard import _resolve_user_id as scope_resolve_user_id

ORG = "org-dbt-map"
PROJECT = "proj-1"


# ── synthetic distilled graph ─────────────────────────────────────────────────


def _node(name, rtype="model", columns=None, **extra):
    return {
        "name": name,
        "resource_type": rtype,
        "path": f"{name}.sql",
        "original_file_path": f"models/{name}.sql",
        "fqn": ["demo", name],
        "schema": "main",
        "database": "db",
        "description": f"{name} desc",
        "tags": [],
        "config": {"materialized": "table"},
        "columns": {
            c: {"name": c, "description": f"{c} d", **({"data_type": "int"} if c == "id" else {})}
            for c in (columns or [])
        },
        **extra,
    }


def _test(name, column):
    return {
        "name": name,
        "resource_type": "test",
        "test_metadata": {"name": "not_null", "kwargs": {"column_name": column, "model": "x"}},
        "columns": {},
    }


def synthetic_graph() -> dict:
    """raw source -> stg_orders -> orders -> (mart_a, mart_b); dim_x isolated."""
    nodes = {
        "model.demo.stg_orders": _node("stg_orders", columns=["id", "amount"]),
        "model.demo.orders": _node("orders", columns=["id", "amount", "customer"]),
        "model.demo.mart_a": _node("mart_a", columns=["id"]),
        "model.demo.mart_b": _node("mart_b", columns=["id", "total"]),
        "model.demo.dim_x": _node("dim_x", columns=["id"]),
        "model.other.orders": _node("orders", columns=["id"]),
        "test.demo.not_null_orders_id": _test("not_null_orders_id", "id"),
        "test.demo.not_null_orders_amount": _test("not_null_orders_amount", "amount"),
        "test.demo.unique_mart_a_id": _test("unique_mart_a_id", "id"),
    }
    sources = {"source.demo.raw.orders": _node("orders", rtype="source", columns=["id"])}
    parent_map = {
        "model.demo.stg_orders": ["source.demo.raw.orders"],
        "model.demo.orders": ["model.demo.stg_orders"],
        "model.demo.mart_a": ["model.demo.orders"],
        "model.demo.mart_b": ["model.demo.orders"],
        "model.demo.dim_x": [],
        "model.other.orders": ["source.demo.raw.missing"],
        "test.demo.not_null_orders_id": ["model.demo.orders"],
        "test.demo.not_null_orders_amount": ["model.demo.orders"],
        "test.demo.unique_mart_a_id": ["model.demo.mart_a"],
        "source.demo.raw.orders": [],
    }
    child_map: dict[str, list[str]] = {k: [] for k in parent_map}
    for child, parents in parent_map.items():
        for parent in parents:
            child_map.setdefault(parent, []).append(child)
    return {
        "metadata": {"dbt_version": "1.8.0", "project_name": "demo", "generated_at": "g"},
        "nodes": nodes,
        "sources": sources,
        "parent_map": parent_map,
        "child_map": child_map,
    }


# ── app fixture ───────────────────────────────────────────────────────────────


class _FakeStorage:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self.blobs = blobs
        self.enabled = True
        self.calls = 0
        self.db_calls = 0  # project lookups + row queries, bumped by the fake store

    async def get_bytes(self, key: str) -> bytes | None:
        self.calls += 1
        return self.blobs.get(key)


class _FakeProject:
    default_branch = "main"


class _CountingSession:
    """Delegates to the real session; counts execute() so tests can prove cache hits."""

    def __init__(self, session: AsyncSession, storage: _FakeStorage) -> None:
        self._session = session
        self._storage = storage

    async def execute(self, *args, **kwargs):
        self._storage.db_calls += 1
        return await self._session.execute(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._session, name)


class _FakeStore:
    def __init__(self, session: AsyncSession, storage: _FakeStorage) -> None:
        self.session = _CountingSession(session, storage)
        self.org_id = ORG
        self._storage = storage

    async def get_workspace_project(self, project_id: str):
        self._storage.db_calls += 1
        return _FakeProject()


class _LocalAuth(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.auth = {"auth_method": "local_key"}
        return await call_next(request)


@pytest.fixture
def harness(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    async def _create_all():
        async with engine.begin() as conn:
            await conn.run_sync(GatewayBase.metadata.create_all)

    asyncio.run(_create_all())
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    graph = synthetic_graph()
    graph_key = f"org/proj/dbt/{uuid.uuid4().hex}-graph.json.gz"
    storage = _FakeStorage({graph_key: gzip.compress(json.dumps(graph).encode())})
    monkeypatch.setattr(dbt_map_api, "workspace_object_storage", lambda: storage)
    monkeypatch.setattr(dbt_map_api, "schedule_compile", lambda *a, **k: None)
    monkeypatch.delenv("SP_DBT_MAP_ROW_CACHE_SECONDS", raising=False)
    graph_cache.clear()
    row_cache.clear()
    sql_map_cache.clear()

    now = time.time()

    async def _insert(**overrides):
        async with factory() as session:
            row = GatewayDbtManifest(
                id=str(uuid.uuid4()),
                org_id=ORG,
                project_id=PROJECT,
                branch="main",
                revision=overrides.pop("revision", 1),
                status=overrides.pop("status", "success"),
                trigger="manual",
                graph_key=overrides.pop("graph_key", graph_key),
                node_count=len(graph["nodes"]),
                created_at=now,
                updated_at=now,
                **overrides,
            )
            session.add(row)
            await session.commit()

    asyncio.run(_insert())

    app = FastAPI()
    app.include_router(dbt_map_api.router)
    app.add_middleware(_LocalAuth)
    app.add_middleware(SecurityHeadersMiddleware)

    async def _store():
        async with factory() as session:
            yield _FakeStore(session, storage)

    async def _user() -> str:
        return "u"

    async def _no_gate() -> None:
        return None

    app.dependency_overrides[get_store] = _store
    app.dependency_overrides[scope_resolve_user_id] = _user
    app.dependency_overrides[require_projects_feature] = _no_gate

    client = TestClient(app)
    yield client, graph, storage, _insert
    graph_cache.clear()
    row_cache.clear()
    sql_map_cache.clear()
    asyncio.run(engine.dispose())


URL = f"/api/workspace-projects/{PROJECT}/dbt-map"


def _raw_body(client: TestClient, url: str, **kwargs) -> tuple[int, dict, bytes]:
    with client.stream("GET", url, **kwargs) as resp:
        return resp.status_code, dict(resp.headers), b"".join(resp.iter_raw())


# ── caching headers ───────────────────────────────────────────────────────────


def test_full_identity_response_matches_legacy_shape(harness):
    client, graph, _storage, _insert = harness
    resp = client.get(URL, headers={"Accept-Encoding": "identity"})
    assert resp.status_code == 200
    assert "content-encoding" not in resp.headers
    body = resp.json()
    assert body["status"] == "success"
    assert body["map"]["project_id"] == PROJECT
    assert body["graph"] == graph
    assert resp.headers["cache-control"] == "private, max-age=0, must-revalidate"
    assert resp.headers["etag"].startswith('W/"')
    assert resp.headers["vary"] == "Accept-Encoding"


def test_gzip_when_accepted_decompresses_to_full_json(harness):
    client, graph, _storage, _insert = harness
    status, headers, raw = _raw_body(client, URL, headers={"Accept-Encoding": "gzip"})
    assert status == 200
    assert headers["content-encoding"] == "gzip"
    identity = client.get(URL, headers={"Accept-Encoding": "identity"}).content
    assert len(raw) < len(identity) // 3
    assert json.loads(gzip.decompress(raw)) == json.loads(identity)
    assert json.loads(gzip.decompress(raw))["graph"] == graph


def test_etag_round_trip_returns_304(harness):
    client, _graph, _storage, _insert = harness
    first = client.get(URL)
    etag = first.headers["etag"]
    again = client.get(URL, headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.headers["etag"] == etag
    assert again.headers["cache-control"] == "private, max-age=0, must-revalidate"
    assert again.content == b""
    # A new revision changes the ETag, so the stale tag no longer matches.
    # The compile call drops the row cache so the new row is visible at once.
    asyncio.run(_insert(revision=2, graph_key=None, status="running"))
    assert client.post(f"{URL}/compile").status_code == 200
    fresh = client.get(URL, headers={"If-None-Match": etag})
    assert fresh.status_code == 200
    assert fresh.json()["status"] == "running"
    assert fresh.json()["graph"] is None


def test_poll_without_graph_is_small_and_tagged(harness):
    client, _graph, storage, _insert = harness
    resp = client.get(URL, params={"include_graph": "false"})
    assert resp.status_code == 200
    assert resp.json()["graph"] is None
    assert resp.headers["etag"]
    assert len(resp.content) < 600
    assert storage.calls == 0


def test_security_middleware_keeps_route_cache_control(harness):
    client, _graph, _storage, _insert = harness
    resp = client.get(URL)
    assert resp.headers["cache-control"] != "no-store"
    assert resp.headers["x-content-type-options"] == "nosniff"
    # Unrelated paths still get the blanket no-store.
    other = client.get("/api/workspace-projects/x/dbt-mapper")
    assert other.headers["cache-control"] == "no-store"


def test_none_status_when_no_row(harness):
    client, _graph, _storage, _insert = harness
    resp = client.get("/api/workspace-projects/other/dbt-map")
    assert resp.status_code == 200
    assert resp.json() == {"status": "none", "map": None, "graph": None}
    assert resp.headers["etag"] == 'W/"none"'


# ── cache ─────────────────────────────────────────────────────────────────────


def test_second_request_does_not_touch_storage(harness):
    client, _graph, storage, _insert = harness
    client.get(URL)
    client.get(URL, params={"graph": "skeleton"})
    client.get(f"{URL}/columns", params={"nodes": "model.demo.orders"})
    client.get(f"{URL}/model/orders")
    assert storage.calls == 1
    assert graph_cache.stats()["entries"] == 1
    assert graph_cache.stats()["misses"] == 1


def test_cache_never_stores_misses():
    async def _run():
        cache = GraphCache()

        async def _none():
            return None

        assert await cache.get_or_load("k", _none) is None
        assert cache.stats()["entries"] == 0

        async def _boom():
            raise RuntimeError("s3 down")

        with pytest.raises(RuntimeError):
            await cache.get_or_load("k", _boom)
        assert cache.stats()["entries"] == 0

    asyncio.run(_run())


def test_cache_evicts_by_entry_count_and_budget():
    async def _run():
        blob = gzip.compress(json.dumps(synthetic_graph()).encode())

        async def _load():
            return blob

        cache = GraphCache(max_entries=2)
        for key in ("a", "b", "c"):
            await cache.get_or_load(key, _load)
        assert cache.get("a") is None
        assert cache.get("c") is not None

        tiny = GraphCache(max_entries=8, byte_budget=10)
        await tiny.get_or_load("a", _load)
        await tiny.get_or_load("b", _load)
        assert tiny.stats()["entries"] == 1  # never evicts the newest entry

    asyncio.run(_run())


def test_concurrent_fill_loads_once():
    async def _run():
        blob = gzip.compress(json.dumps(synthetic_graph()).encode())
        calls = 0

        async def _load():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            return blob

        cache = GraphCache()
        entries = await asyncio.gather(*(cache.get_or_load("k", _load) for _ in range(5)))
        assert calls == 1
        assert all(e is entries[0] for e in entries)

    asyncio.run(_run())


# ── skeleton variant ──────────────────────────────────────────────────────────


def test_skeleton_drops_tests_and_columns(harness):
    client, graph, _storage, _insert = harness
    resp = client.get(URL, params={"graph": "skeleton"}, headers={"Accept-Encoding": "identity"})
    assert resp.status_code == 200
    body = resp.json()
    skel = body["graph"]
    assert skel["metadata"]["variant"] == "skeleton"
    assert skel["metadata"]["dbt_version"] == "1.8.0"
    assert not any(uid.startswith("test.") for uid in skel["nodes"])
    orders = skel["nodes"]["model.demo.orders"]
    assert "columns" not in orders
    assert orders["column_count"] == 3
    assert orders["tests"] == [
        {"name": "not_null_orders_id", "test_metadata": {"name": "not_null", "kwargs": {"column_name": "id"}}},
        {
            "name": "not_null_orders_amount",
            "test_metadata": {"name": "not_null", "kwargs": {"column_name": "amount"}},
        },
    ]
    assert skel["nodes"]["model.demo.dim_x"]["tests"] == []
    assert skel["child_map"]["model.demo.orders"] == ["model.demo.mart_a", "model.demo.mart_b"]
    assert not any(k.startswith("test.") for k in skel["parent_map"])
    assert skel["sources"] == graph["sources"]
    assert len(resp.content) < len(client.get(URL, headers={"Accept-Encoding": "identity"}).content)


def test_skeleton_caps_tests_per_node():
    graph = synthetic_graph()
    for i in range(60):
        uid = f"test.demo.t{i}"
        graph["nodes"][uid] = _test(f"t{i}", "id")
        graph["parent_map"][uid] = ["model.demo.dim_x"]
        graph["child_map"]["model.demo.dim_x"].append(uid)
    skel = build_skeleton(graph)
    assert len(skel["nodes"]["model.demo.dim_x"]["tests"]) == 40


def test_skeleton_is_gzipped_when_accepted(harness):
    client, _graph, _storage, _insert = harness
    status, headers, raw = _raw_body(client, URL, params={"graph": "skeleton"}, headers={"Accept-Encoding": "gzip"})
    assert status == 200 and headers["content-encoding"] == "gzip"
    assert json.loads(gzip.decompress(raw))["graph"]["metadata"]["variant"] == "skeleton"


def test_invalid_graph_variant_is_422(harness):
    client, _graph, _storage, _insert = harness
    assert client.get(URL, params={"graph": "bogus"}).status_code == 422


# ── columns endpoint ──────────────────────────────────────────────────────────


def test_columns_endpoint_returns_known_ids_only(harness):
    client, _graph, _storage, _insert = harness
    resp = client.get(
        f"{URL}/columns",
        params={"nodes": "model.demo.orders, model.demo.nope,source.demo.raw.orders,model.demo.orders"},
    )
    assert resp.status_code == 200
    cols = resp.json()["columns"]
    assert set(cols) == {"model.demo.orders", "source.demo.raw.orders"}
    assert cols["model.demo.orders"][0] == {"name": "id", "description": "id d", "data_type": "int"}
    assert cols["model.demo.orders"][1] == {"name": "amount", "description": "amount d"}
    assert resp.headers["etag"] and resp.headers["cache-control"].startswith("private")


def test_columns_endpoint_caps_at_50(harness):
    client, _graph, _storage, _insert = harness
    ok = ",".join(f"model.demo.m{i}" for i in range(50))
    assert client.get(f"{URL}/columns", params={"nodes": ok}).status_code == 200
    too_many = ",".join(f"model.demo.m{i}" for i in range(51))
    assert client.get(f"{URL}/columns", params={"nodes": too_many}).status_code == 422


def test_columns_endpoint_404_without_graph(harness):
    client, _graph, _storage, _insert = harness
    resp = client.get("/api/workspace-projects/other/dbt-map/columns", params={"nodes": "x"})
    assert resp.status_code == 404


# ── model endpoint ────────────────────────────────────────────────────────────


def test_model_endpoint_exact_id_and_cone(harness):
    client, _graph, _storage, _insert = harness
    resp = client.get(f"{URL}/model/model.demo.orders")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success" and body["map"]["project_id"] == PROJECT
    model = body["model"]
    assert model["unique_id"] == "model.demo.orders"
    assert model["name"] == "orders"
    assert "columns" in model and [c["name"] for c in model["columns"]] == ["id", "amount", "customer"]
    assert model["column_count"] == 3
    assert len(model["tests"]) == 2
    g = body["graph"]
    assert g["metadata"]["variant"] == "cone"
    assert set(g["nodes"]) == {
        "source.demo.raw.orders",
        "model.demo.stg_orders",
        "model.demo.orders",
        "model.demo.mart_a",
        "model.demo.mart_b",
    }
    assert all("columns" not in n for n in g["nodes"].values())
    assert g["nodes"]["source.demo.raw.orders"]["resource_type"] == "source"
    assert set(g["sources"]) == {"source.demo.raw.orders"}
    assert g["parent_map"]["model.demo.orders"] == ["model.demo.stg_orders"]
    assert g["child_map"]["model.demo.orders"] == ["model.demo.mart_a", "model.demo.mart_b"]
    assert not any(k.startswith("test.") for k in g["child_map"])
    assert body["cone"] == {"upstream": 2, "downstream": 2}


def test_model_endpoint_hops_limits_cone(harness):
    client, _graph, _storage, _insert = harness
    body = client.get(f"{URL}/model/mart_a", params={"hops": 1}).json()
    assert set(body["graph"]["nodes"]) == {"model.demo.mart_a", "model.demo.orders"}
    assert body["cone"] == {"upstream": 1, "downstream": 0}
    zero = client.get(f"{URL}/model/mart_a", params={"hops": 0}).json()
    assert set(zero["graph"]["nodes"]) == {"model.demo.mart_a"}
    assert client.get(f"{URL}/model/mart_a", params={"hops": "-1"}).status_code == 422
    assert client.get(f"{URL}/model/mart_a", params={"hops": "many"}).status_code == 422


def test_model_endpoint_name_resolution(harness):
    client, _graph, _storage, _insert = harness
    assert client.get(f"{URL}/model/MART_A").json()["model"]["unique_id"] == "model.demo.mart_a"
    ambiguous = client.get(f"{URL}/model/orders")
    assert ambiguous.status_code == 409
    assert ambiguous.json()["detail"]["candidates"] == ["model.demo.orders", "model.other.orders"]
    assert client.get(f"{URL}/model/nothing").status_code == 404


def test_model_endpoint_stubs_sources_missing_from_graph(harness):
    client, _graph, _storage, _insert = harness
    body = client.get(f"{URL}/model/model.other.orders").json()
    stub = body["graph"]["nodes"]["source.demo.raw.missing"]
    assert stub == {"name": "missing", "resource_type": "source", "column_count": 0, "tests": []}
    assert body["graph"]["sources"] == {}


def test_model_endpoint_honors_etag(harness):
    client, _graph, _storage, _insert = harness
    first = client.get(f"{URL}/model/mart_b")
    assert client.get(f"{URL}/model/mart_b", headers={"If-None-Match": first.headers["etag"]}).status_code == 304


# ── slices unit checks ────────────────────────────────────────────────────────


def test_resolve_ref_and_cone_on_source():
    graph = synthetic_graph()
    assert resolve_ref(graph, "source.demo.raw.orders") == ("source.demo.raw.orders", [])
    assert resolve_ref(graph, "not_null_orders_id") == (None, [])  # tests never resolve by name
    cone = build_cone(graph, "source.demo.raw.orders", None)
    assert cone["cone"] == {"upstream": 0, "downstream": 4}
    assert cone["model"]["resource_type"] == "source"


def test_runner_distill_keeps_data_type_when_present():
    manifest = {
        "metadata": {},
        "nodes": {
            "model.demo.a": {
                "name": "a",
                "resource_type": "model",
                "columns": {
                    "id": {"name": "id", "description": "pk", "data_type": "integer"},
                    "note": {"name": "note", "description": ""},
                },
            }
        },
        "sources": {},
        "parent_map": {},
        "child_map": {},
    }
    cols = distill_graph(manifest)["nodes"]["model.demo.a"]["columns"]
    assert cols["id"] == {"name": "id", "description": "pk", "data_type": "integer"}
    assert cols["note"] == {"name": "note", "description": ""}


def test_measured_sizes_on_fixture(harness):
    """Documented sizes for the synthetic fixture; guards against regressions."""
    client, _graph, _storage, _insert = harness
    full = client.get(URL, headers={"Accept-Encoding": "identity"}).content
    _s, _h, full_gz = _raw_body(client, URL, headers={"Accept-Encoding": "gzip"})
    skel = client.get(URL, params={"graph": "skeleton"}, headers={"Accept-Encoding": "identity"}).content
    cone = client.get(f"{URL}/model/mart_a").content
    assert len(full_gz) < len(full)
    assert len(skel) < len(full)
    assert len(cone) < len(skel)
