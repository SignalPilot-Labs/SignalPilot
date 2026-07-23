"""Tests for schema-diff watches: diff rendering, due-scheduling, PR flow,
and the run_watch orchestration core (baseline, drift, suppression, errors)."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.db.models import GatewayBase, GatewaySchemaWatch
from gateway.schema_watch.runner import (
    _pr_title,
    diff_is_empty,
    new_watch,
    open_schema_diff_pr,
    render_diff_markdown,
    run_due_watches,
    run_watch,
    strip_schema,
)

ORG = "test-org"


@pytest_asyncio.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    f = async_sessionmaker(engine, expire_on_commit=False)
    yield f
    await engine.dispose()


@pytest_asyncio.fixture
async def session(factory):
    async with factory() as s:
        yield s


DIFF = {
    "has_changes": True,
    "added_tables": ["raw.new_events"],
    "removed_tables": ["raw.legacy"],
    "modified_tables": [
        {
            "table": "raw.orders",
            "added_columns": ["discount_code"],
            "removed_columns": ["old_flag"],
            "type_changes": [{"column": "amount", "old_type": "integer", "new_type": "numeric"}],
        }
    ],
}

SCHEMA_V1 = {
    "raw.orders": {
        "schema": "raw",
        "name": "orders",
        "type": "table",
        "columns": [{"name": "id", "type": "bigint", "nullable": False, "primary_key": True}],
        "foreign_keys": [],
        "row_count": 10,
        "size_mb": 1.0,
    }
}
SCHEMA_V2 = {
    **SCHEMA_V1,
    "raw.events": {
        "schema": "raw",
        "name": "events",
        "type": "table",
        "columns": [{"name": "event_id", "type": "bigint", "nullable": False, "primary_key": True}],
        "foreign_keys": [],
        "row_count": 5,
    },
}


class TestRendering:
    def test_markdown_contains_all_sections(self):
        md = render_diff_markdown(
            connection_name="warehouse", diff=DIFF, old_fp="a" * 64, new_fp="b" * 64, table_count=42
        )
        assert "`raw.new_events`" in md
        assert "Removed tables ⚠️" in md and "`raw.legacy`" in md
        assert "➕ column `discount_code`" in md
        assert "➖ column `old_flag` ⚠️" in md
        assert "`integer` → `numeric`" in md
        assert "42 tables" in md

    def test_pr_title_summary(self):
        assert _pr_title("wh", DIFF) == "Schema watch: wh — +1 table, -1 table, 1 modified"

    def test_empty_diff_note(self):
        md = render_diff_markdown(connection_name="wh", diff={}, old_fp=None, new_fp="b" * 64, table_count=1)
        assert "nullability, primary-key, or foreign-key drift" in md

    def test_diff_is_empty(self):
        assert diff_is_empty({}) and diff_is_empty({"added_tables": []})
        assert not diff_is_empty(DIFF)

    def test_strip_schema_drops_volatile_fields(self):
        stripped = strip_schema(SCHEMA_V1)
        t = stripped["raw.orders"]
        assert "row_count" not in t and "size_mb" not in t
        assert t["columns"][0] == {"name": "id", "type": "bigint", "nullable": False, "primary_key": True}


class TestPrFlow:
    @pytest.mark.asyncio
    async def test_open_pr_calls_sequence(self):
        client = AsyncMock()
        client.get_default_branch.return_value = "main"
        client.get_ref_sha.return_value = "abc123"
        client.create_pull_request.return_value = {"html_url": "https://github.com/o/r/pull/9"}
        url = await open_schema_diff_pr(
            client, repo="o/r", base_branch=None, connection_name="wh",
            markdown="# md", diff=DIFF, new_fp="f" * 64,
        )
        assert url == "https://github.com/o/r/pull/9"
        client.create_branch.assert_awaited_once()
        branch = client.create_branch.await_args.args[1]
        assert branch == f"schema-watch/wh-{'f' * 12}"
        client.put_file.assert_awaited_once()
        assert client.put_file.await_args.kwargs["branch"] == branch
        pr_kwargs = client.create_pull_request.await_args.kwargs
        assert pr_kwargs["base"] == "main" and pr_kwargs["head"] == branch
        assert "# md" in pr_kwargs["body"]

    @pytest.mark.asyncio
    async def test_existing_branch_treated_as_already_reported(self):
        import httpx

        client = AsyncMock()
        client.get_default_branch.return_value = "main"
        client.get_ref_sha.return_value = "abc"
        resp = httpx.Response(422, request=httpx.Request("POST", "https://api.github.com/x"))
        client.create_branch.side_effect = httpx.HTTPStatusError("exists", request=resp.request, response=resp)
        url = await open_schema_diff_pr(
            client, repo="o/r", base_branch=None, connection_name="wh",
            markdown="m", diff=DIFF, new_fp="e" * 64,
        )
        assert url == ""
        client.create_pull_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_explicit_base_branch_skips_default_lookup(self):
        client = AsyncMock()
        client.get_ref_sha.return_value = "abc"
        client.create_pull_request.return_value = {}
        await open_schema_diff_pr(
            client, repo="o/r", base_branch="develop", connection_name="wh",
            markdown="m", diff={}, new_fp="d" * 64,
        )
        client.get_default_branch.assert_not_awaited()
        assert client.create_pull_request.await_args.kwargs["base"] == "develop"


@asynccontextmanager
async def _fake_pool_conn(*a, **k):
    yield None  # connector unused — get_schema patched at runner level


def _patch_runner_deps(schema: dict, token: str | None = "tok"):
    """Patch run_watch's store/pool/github deps; returns (patches, pr_mock)."""

    class _FakeConnector:
        async def get_schema(self):
            return schema

    @asynccontextmanager
    async def fake_conn(*a, **k):
        yield _FakeConnector()

    class _FakeStore:
        def __init__(self, session, org_id=None, **kw):
            pass

        async def get_connection(self, name):
            class C:
                db_type = "postgres"

            return C()

        async def get_connection_string(self, name):
            return "postgresql://x"

        async def get_credential_extras(self, name):
            return {}

    pr_mock = AsyncMock(return_value="https://github.com/o/r/pull/1")
    patches = [
        patch("gateway.connectors.pool_manager.pool_manager.connection", fake_conn),
        patch("gateway.store.Store", _FakeStore),
        patch("gateway.schema_watch.runner._resolve_watch_token", new=AsyncMock(return_value=token)),
        patch("gateway.schema_watch.runner.open_schema_diff_pr", new=pr_mock),
        patch("gateway.github_bot.client.GitHubBotClient", return_value=AsyncMock()),
    ]
    return patches, pr_mock


class TestRunWatch:
    def _watch(self):
        return new_watch(org_id=ORG, connection_name="conn", github_repo="o/r")

    async def _seeded(self, session):
        w = self._watch()
        session.add(w)
        await session.commit()
        return w

    @pytest.mark.asyncio
    async def test_first_run_baselines_without_pr(self, session):
        w = await self._seeded(session)
        patches, pr_mock = _patch_runner_deps(SCHEMA_V1)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = await run_watch(session, w)
        assert result.get("baselined") is True
        assert w.last_fingerprint is not None
        assert w.last_schema == strip_schema(SCHEMA_V1)
        pr_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unchanged_schema_no_pr(self, session):
        w = await self._seeded(session)
        patches, pr_mock = _patch_runner_deps(SCHEMA_V1)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            await run_watch(session, w)
            result = await run_watch(session, w)
        assert result["changed"] is False
        pr_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_drift_opens_pr_and_updates_row(self, session):
        w = await self._seeded(session)
        p1, _ = _patch_runner_deps(SCHEMA_V1)
        with p1[0], p1[1], p1[2], p1[3], p1[4]:
            await run_watch(session, w)
        p2, pr_mock = _patch_runner_deps(SCHEMA_V2)
        with p2[0], p2[1], p2[2], p2[3], p2[4]:
            result = await run_watch(session, w)
        assert result["changed"] is True
        assert result["pr_url"] == "https://github.com/o/r/pull/1"
        assert w.last_pr_url == "https://github.com/o/r/pull/1"
        assert w.last_change_at is not None
        assert "raw.events" in (w.last_schema or {})

    @pytest.mark.asyncio
    async def test_fingerprint_only_drift_suppressed(self, session):
        """Nullability-only change: baseline advances, no PR."""
        w = await self._seeded(session)
        p1, _ = _patch_runner_deps(SCHEMA_V1)
        with p1[0], p1[1], p1[2], p1[3], p1[4]:
            await run_watch(session, w)
        nullable_flip = {
            "raw.orders": {
                **SCHEMA_V1["raw.orders"],
                "columns": [{"name": "id", "type": "bigint", "nullable": True, "primary_key": True}],
            }
        }
        p2, pr_mock = _patch_runner_deps(nullable_flip)
        with p2[0], p2[1], p2[2], p2[3], p2[4]:
            result = await run_watch(session, w)
        assert result.get("suppressed") == "no table-level differences"
        pr_mock.assert_not_awaited()
        # baseline advanced so it doesn't re-trigger forever
        assert w.last_schema == strip_schema(nullable_flip)

    @pytest.mark.asyncio
    async def test_missing_token_records_error(self, session):
        w = await self._seeded(session)
        p1, _ = _patch_runner_deps(SCHEMA_V1)
        with p1[0], p1[1], p1[2], p1[3], p1[4]:
            await run_watch(session, w)
        p2, pr_mock = _patch_runner_deps(SCHEMA_V2, token=None)
        with p2[0], p2[1], p2[2], p2[3], p2[4]:
            result = await run_watch(session, w)
        assert "no GitHub token" in result.get("error", "")
        assert "no GitHub token" in (w.last_error or "")
        # fingerprint NOT advanced — drift retries next run
        fp_row = (await session.execute(select(GatewaySchemaWatch.last_fingerprint))).scalar()
        from gateway.connectors.schema_cache import _schema_fingerprint

        assert fp_row == _schema_fingerprint(SCHEMA_V1)


class TestScheduling:
    @pytest.mark.asyncio
    async def test_due_watch_runs_and_not_due_skips(self, factory):
        async with factory() as s:
            due = new_watch(org_id=ORG, connection_name="conn", github_repo="o/r")
            due.last_run_at = time.time() - 999999
            fresh = new_watch(org_id=ORG, connection_name="conn2", github_repo="o/r")
            fresh.last_run_at = time.time()
            s.add_all([due, fresh])
            await s.commit()

        with patch("gateway.schema_watch.runner.run_watch", new=AsyncMock(return_value={})) as rw:
            ran = await run_due_watches(factory)
        assert ran == 1
        assert rw.await_args.args[1].connection_name == "conn"

    @pytest.mark.asyncio
    async def test_disabled_watch_skipped(self, factory):
        async with factory() as s:
            w = new_watch(org_id=ORG, connection_name="conn", github_repo="o/r", enabled=False)
            s.add(w)
            await s.commit()
        with patch("gateway.schema_watch.runner.run_watch", new=AsyncMock(return_value={})):
            assert await run_due_watches(factory) == 0

    @pytest.mark.asyncio
    async def test_never_run_watch_is_due(self, factory):
        async with factory() as s:
            s.add(new_watch(org_id=ORG, connection_name="conn", github_repo="o/r"))
            await s.commit()
        with patch("gateway.schema_watch.runner.run_watch", new=AsyncMock(return_value={})):
            assert await run_due_watches(factory) == 1

    def test_interval_floor(self):
        assert new_watch(org_id=ORG, connection_name="c", github_repo="o/r", interval_s=5).interval_s == 60
