"""Entitlement resolution: the one gating rule, tier mapping, cache, and the legacy-schema fallback."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from gateway.billing import entitlements as ent
from gateway.billing.entitlements import (
    OrgEntitlement,
    entitlement_from_row,
    free_entitlement,
    get_entitlement,
    invalidate,
    local_entitlement,
    normalize_tier,
)

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clear_cache():
    invalidate()
    yield
    invalidate()


@pytest.fixture
def cloud(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SP_BACKEND_URL", "http://backend.test")


@pytest.fixture
def local(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SP_BACKEND_URL", raising=False)


class TestIsBillable:
    @pytest.mark.parametrize("tier", ["team", "scale", "enterprise"])
    @pytest.mark.parametrize("status", ["active", "trialing"])
    def test_active_and_trialing_paid_tiers_are_billable(self, tier: str, status: str) -> None:
        assert OrgEntitlement(org_id="o", tier=tier, status=status).billable_at(NOW)

    def test_past_due_inside_grace_is_billable(self) -> None:
        e = OrgEntitlement(org_id="o", tier="team", status="past_due", grace_until=NOW + timedelta(days=1))
        assert e.billable_at(NOW)

    def test_past_due_after_grace_is_not_billable(self) -> None:
        e = OrgEntitlement(org_id="o", tier="team", status="past_due", grace_until=NOW - timedelta(seconds=1))
        assert not e.billable_at(NOW)

    def test_past_due_without_grace_is_not_billable(self) -> None:
        assert not OrgEntitlement(org_id="o", tier="team", status="past_due").billable_at(NOW)

    @pytest.mark.parametrize("status", ["canceled", "unpaid", "incomplete", "none"])
    def test_other_statuses_are_not_billable(self, status: str) -> None:
        assert not OrgEntitlement(org_id="o", tier="scale", status=status).billable_at(NOW)

    def test_free_tier_is_never_billable(self) -> None:
        assert not OrgEntitlement(org_id="o", tier="free", status="active").billable_at(NOW)
        assert not free_entitlement("o").is_billable

    def test_local_mode_is_billable_but_not_metered(self) -> None:
        e = local_entitlement("local")
        assert e.tier == "unlimited"
        assert e.is_billable
        assert not e.is_metered
        assert OrgEntitlement(org_id="o", tier="team", status="active").is_metered

    def test_to_dict_carries_computed_is_billable(self) -> None:
        e = OrgEntitlement(org_id="o", tier="team", status="active", included_seats=10, enterprise_flags={"sso": True})
        d = e.to_dict()
        assert d["is_billable"] is True
        assert d["included_seats"] == 10
        assert d["enterprise_flags"] == {"sso": True}
        assert d["grace_until"] is None


class TestTierAndRow:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("team", "team"),
            ("Scale", "scale"),
            ("enterprise", "enterprise"),
            ("pro", "team"),
            ("free", "free"),
            (None, "free"),
            ("weird", "free"),
        ],
    )
    def test_normalize_tier(self, raw: str | None, expected: str) -> None:
        assert normalize_tier(raw) == expected

    def test_full_row(self) -> None:
        period_end = NOW + timedelta(days=10)
        e = entitlement_from_row(
            "o",
            {
                "plan_tier": "scale",
                "status": "active",
                "current_period_end": period_end,
                "included_seats": 25,
                "included_models": 50,
                "included_eval_runs": 30,
                "included_credits": 12500,
                "managed": True,
                "billing_interval": "year",
                "enterprise_flags": '{"privatelink": true}',
                "grace_until": None,
            },
        )
        assert e.tier == "scale"
        assert (e.included_seats, e.included_models, e.included_eval_runs, e.included_credits) == (25, 50, 30, 12500)
        assert e.managed is True
        assert e.billing_interval == "year"
        assert e.enterprise_flags == {"privatelink": True}
        assert e.current_period_end == period_end
        assert e.grace_until is None

    def test_legacy_row_has_zero_allowances(self) -> None:
        e = entitlement_from_row("o", {"plan_tier": "pro", "status": "active", "current_period_end": None})
        assert e.tier == "team"
        assert e.is_billable
        assert (e.included_seats, e.included_credits) == (0, 0)
        assert e.enterprise_flags == {}

    def test_past_due_without_grace_column_derives_grace_from_period_end(self) -> None:
        period_end = datetime(2026, 9, 10, tzinfo=UTC)
        e = entitlement_from_row("o", {"plan_tier": "team", "status": "past_due", "current_period_end": period_end})
        assert e.grace_until == period_end + timedelta(days=14)
        assert e.billable_at(datetime(2026, 9, 23, tzinfo=UTC))
        assert not e.billable_at(datetime(2026, 9, 25, tzinfo=UTC))

    def test_naive_timestamps_are_treated_as_utc(self) -> None:
        e = entitlement_from_row("o", {"plan_tier": "team", "status": "past_due", "grace_until": datetime(2026, 9, 20)})
        assert e.grace_until == datetime(2026, 9, 20, tzinfo=UTC)


class TestGetEntitlement:
    async def test_local_mode_returns_unlimited_without_db(self, local, monkeypatch: pytest.MonkeyPatch) -> None:
        loader = AsyncMock(side_effect=AssertionError("must not hit the database"))
        monkeypatch.setattr(ent, "_load_entitlement", loader)
        e = await get_entitlement("anything")
        assert e.tier == "unlimited" and e.is_billable

    async def test_cloud_mode_reads_and_caches(self, cloud, monkeypatch: pytest.MonkeyPatch) -> None:
        loader = AsyncMock(return_value=OrgEntitlement(org_id="o", tier="team", status="active"))
        monkeypatch.setattr(ent, "_load_entitlement", loader)
        first = await get_entitlement("o")
        second = await get_entitlement("o")
        assert first is second
        assert loader.await_count == 1

    async def test_invalidate_drops_one_org(self, cloud, monkeypatch: pytest.MonkeyPatch) -> None:
        loader = AsyncMock(return_value=OrgEntitlement(org_id="o", tier="team", status="active"))
        monkeypatch.setattr(ent, "_load_entitlement", loader)
        await get_entitlement("o")
        await get_entitlement("p")
        invalidate("o")
        await get_entitlement("o")
        await get_entitlement("p")
        assert loader.await_count == 3

    async def test_cache_expires_after_ttl(self, cloud, monkeypatch: pytest.MonkeyPatch) -> None:
        loader = AsyncMock(return_value=OrgEntitlement(org_id="o", tier="team", status="active"))
        monkeypatch.setattr(ent, "_load_entitlement", loader)
        clock = [1000.0]
        monkeypatch.setattr(ent.time, "monotonic", lambda: clock[0])
        await get_entitlement("o")
        clock[0] += ent.CACHE_TTL_SECONDS - 1
        await get_entitlement("o")
        clock[0] += 2
        await get_entitlement("o")
        assert loader.await_count == 2

    async def test_non_billable_results_expire_after_fifteen_seconds(self, cloud, monkeypatch: pytest.MonkeyPatch) -> None:
        """A free org that just paid must flip within NON_BILLABLE_CACHE_TTL_SECONDS."""
        loader = AsyncMock(side_effect=[free_entitlement("o"), OrgEntitlement(org_id="o", tier="team", status="active")])
        monkeypatch.setattr(ent, "_load_entitlement", loader)
        clock = [1000.0]
        monkeypatch.setattr(ent.time, "monotonic", lambda: clock[0])
        assert not (await get_entitlement("o")).is_billable
        clock[0] += ent.NON_BILLABLE_CACHE_TTL_SECONDS - 1
        assert not (await get_entitlement("o")).is_billable
        clock[0] += 2
        assert (await get_entitlement("o")).is_billable
        assert loader.await_count == 2

    def test_ttl_split(self) -> None:
        assert ent.NON_BILLABLE_CACHE_TTL_SECONDS == 15
        assert ent.CACHE_TTL_SECONDS == 5 * 60
        assert ent.cache_ttl_seconds(free_entitlement("o")) == 15
        assert ent.cache_ttl_seconds(OrgEntitlement(org_id="o", tier="team", status="active")) == 300
        assert ent.cache_ttl_seconds(OrgEntitlement(org_id="o", tier="team", status="canceled")) == 15

    async def test_refresh_bypasses_and_replaces_the_cached_value(self, cloud, monkeypatch: pytest.MonkeyPatch) -> None:
        paid = OrgEntitlement(org_id="o", tier="team", status="active")
        loader = AsyncMock(side_effect=[free_entitlement("o"), paid, AssertionError("cache must serve the third read")])
        monkeypatch.setattr(ent, "_load_entitlement", loader)
        assert not (await get_entitlement("o")).is_billable
        assert not (await get_entitlement("o")).is_billable
        assert (await get_entitlement("o", refresh=True)) is paid
        assert (await get_entitlement("o")) is paid
        assert loader.await_count == 2

    async def test_lookup_failure_is_free_and_not_cached(self, cloud, monkeypatch: pytest.MonkeyPatch) -> None:
        loader = AsyncMock(
            side_effect=[RuntimeError("db down"), OrgEntitlement(org_id="o", tier="team", status="active")]
        )
        monkeypatch.setattr(ent, "_load_entitlement", loader)
        assert not (await get_entitlement("o")).is_billable
        assert (await get_entitlement("o")).is_billable

    async def test_local_org_id_in_cloud_is_free(self, cloud, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ent, "_load_entitlement", AsyncMock(side_effect=AssertionError))
        assert not (await get_entitlement("local")).is_billable
        assert not (await get_entitlement("")).is_billable


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _FakeSession:
    """Async session double: the first SQL fails when ``fail_full`` is set."""

    def __init__(self, row, fail_full: bool):
        self.row = row
        self.fail_full = fail_full
        self.statements: list[str] = []
        self.rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt, params):
        sql = str(stmt)
        self.statements.append(sql)
        if self.fail_full and "included_seats" in sql:
            raise RuntimeError('column "included_seats" does not exist')
        return _FakeResult(self.row)

    async def rollback(self):
        self.rolled_back = True


class TestLoadEntitlement:
    async def test_full_columns_are_selected_explicitly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sess = _FakeSession({"plan_tier": "enterprise", "status": "active", "included_credits": 75000}, fail_full=False)
        monkeypatch.setattr("gateway.db.engine.get_session_factory", lambda: lambda: sess)
        e = await ent._load_entitlement("o")
        assert e.tier == "enterprise" and e.included_credits == 75000
        assert len(sess.statements) == 1
        for column in (
            "included_seats",
            "included_models",
            "included_eval_runs",
            "managed",
            "billing_interval",
            "enterprise_flags",
            "grace_until",
        ):
            assert column in sess.statements[0]

    async def test_missing_columns_fall_back_to_plan_tier_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sess = _FakeSession({"plan_tier": "team", "status": "active", "current_period_end": None}, fail_full=True)
        monkeypatch.setattr("gateway.db.engine.get_session_factory", lambda: lambda: sess)
        e = await ent._load_entitlement("o")
        assert sess.rolled_back
        assert len(sess.statements) == 2
        assert e.tier == "team" and e.is_billable and e.included_credits == 0

    async def test_no_row_is_free(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sess = _FakeSession(None, fail_full=False)
        monkeypatch.setattr("gateway.db.engine.get_session_factory", lambda: lambda: sess)
        e = await ent._load_entitlement("o")
        assert e.tier == "free" and e.status == "none" and not e.is_billable
