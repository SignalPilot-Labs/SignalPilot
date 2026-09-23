"""Daily snapshot: covered models, seats, allowance, idempotency, the loop schedule, and the Clerk client."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import httpx
from sqlalchemy import select

from gateway.background.credit_snapshot import MAX_SLEEP_SECONDS, seconds_until_next_snapshot
from gateway.billing import GatewayCreditLedger, OrgEntitlement, daily_credit_share, local_entitlement
from gateway.billing.emitters import clerk_members
from gateway.billing.emitters.daily import (
    candidate_org_ids,
    covered_from_runs,
    run_credit_daily_snapshot,
    snapshot_org,
)
from gateway.db.models import GatewayEvalRun, GatewayProject

from .conftest import ORG

DAY = date(2026, 9, 14)
FREE_ORG = "org_free"


def _coverage(names: list[str], covered: set[str]) -> dict:
    return {"models": [{"name": name, "layer": "marts", "covered": name in covered} for name in names]}


async def _seed_runs(session, org_id: str = ORG) -> None:
    universe = [f"model_{index}" for index in range(40)]
    session.add_all(
        [
            GatewayEvalRun(
                id="run-old",
                org_id=org_id,
                status="completed",
                trigger="manual",
                created_at="2026-09-01T00:00:00+00:00",
                project_repo="https://github.com/acme/dbt",
                coverage=_coverage([*universe, "deleted_model"], {"model_0", "model_1", "deleted_model"}),
            ),
            GatewayEvalRun(
                id="run-new",
                org_id=org_id,
                status="completed",
                trigger="schedule",
                created_at="2026-09-10T00:00:00+00:00",
                project_repo="https://github.com/acme/dbt",
                coverage=_coverage(universe, {f"model_{index}" for index in range(1, 32)}),
            ),
            GatewayEvalRun(
                id="run-failed",
                org_id=org_id,
                status="failed",
                trigger="manual",
                created_at="2026-09-11T00:00:00+00:00",
                project_repo="https://github.com/acme/dbt",
                coverage=_coverage(universe, set(universe)),
            ),
        ]
    )
    await session.commit()


class TestCoveredModels:
    def test_union_of_covered_intersected_with_latest_universe(self) -> None:
        runs = [
            ("2026-09-10", "repo", _coverage(["a", "b", "c"], {"b"})),
            ("2026-09-01", "repo", _coverage(["a", "b", "c", "zombie"], {"a", "zombie"})),
            ("2026-09-05", "other", _coverage(["A", "d"], {"A"})),
            ("2026-09-06", "other", None),
        ]
        covered = covered_from_runs(runs)
        # "zombie" left the latest run of "repo"; "A" from "other" lower-cases onto "a".
        assert covered.names == ("a", "b")
        assert covered.runs_read == 3
        assert covered.projects == ("other", "repo")

    def test_names_are_distinct_across_projects(self) -> None:
        runs = [("1", "repo", _coverage(["x"], {"x"})), ("1", "other", _coverage(["X"], {"X"}))]
        assert covered_from_runs(runs).names == ("x",)


class TestSnapshot:
    async def test_team_org_beyond_allowance(self, session, team) -> None:
        await _seed_runs(session)
        counted: list[str] = []

        async def members(org_id: str) -> int | None:
            counted.append(org_id)
            return 12

        written = await snapshot_org(session, team, DAY, member_counter=members)
        assert counted == [ORG]
        assert written["model_day"] is not None and written["seat_day"] is not None
        rows = list((await session.execute(select(GatewayCreditLedger).order_by(GatewayCreditLedger.id))).scalars())
        model_row, seat_row = rows
        # covered: model_0 (old run) + model_1..model_31 (new run) = 32, deleted_model dropped; 32 - 30 = 2 billable
        assert model_row.unit == "model_day"
        assert model_row.idempotency_key == f"model_day:{ORG}:2026-09-14"
        assert model_row.credits == -daily_credit_share(2 * 600, DAY) == -40
        assert model_row.quantity == 2
        assert model_row.reason == "ok"
        assert model_row.payload["covered_count"] == 32
        assert model_row.payload["billable"] == 2
        assert model_row.payload["allowance_position"] == 32
        assert "deleted_model" not in model_row.payload["covered_models"]
        assert model_row.payload["eval_runs_read"] == 2
        assert model_row.occurred_at.replace(tzinfo=UTC) == datetime(2026, 9, 14, tzinfo=UTC)
        assert seat_row.unit == "seat_day"
        assert seat_row.idempotency_key == f"seat_day:{ORG}:2026-09-14"
        assert seat_row.credits == -daily_credit_share(2 * 1_500, DAY) == -100
        assert seat_row.quantity == 2
        assert seat_row.payload == {
            "members": 12,
            "included": 10,
            "billable": 2,
            "allowance_position": 12,
            "monthly_rate": 1500,
        }

    async def test_full_month_of_seat_rows_sums_to_the_rate(self, session, team) -> None:
        async def members(org_id: str) -> int | None:
            return 11

        total = 0
        for day_index in range(1, 31):
            await snapshot_org(session, team, date(2026, 9, day_index), member_counter=members)
        rows = (
            await session.execute(select(GatewayCreditLedger).where(GatewayCreditLedger.unit == "seat_day"))
        ).scalars()
        total = sum(row.credits for row in rows)
        assert total == -1_500

    async def test_enterprise_seats_are_contracted_not_metered(self, session, enterprise) -> None:
        """Enterprise has no public seat price: the row records the extra
        seat but deducts nothing; the contract prices it."""

        async def members(org_id: str) -> int | None:
            return 101

        await snapshot_org(session, enterprise, DAY, member_counter=members)
        seat_row = (
            await session.execute(select(GatewayCreditLedger).where(GatewayCreditLedger.unit == "seat_day"))
        ).scalar_one()
        assert seat_row.credits == 0 and seat_row.quantity == 1 and seat_row.reason == "included"
        assert seat_row.payload.get("monthly_rate") is None

    async def test_snapshot_skipped_without_a_rate_card(self, session, team, monkeypatch) -> None:
        from gateway.billing import rate_card

        rate_card.install(None)

        async def no_row():
            return None

        monkeypatch.setattr(rate_card, "refresh", no_row)

        async def members(org_id: str) -> int | None:
            return 12

        written = await snapshot_org(session, team, DAY, member_counter=members)
        assert written == {"model_day": None, "seat_day": None}
        assert (await session.execute(select(GatewayCreditLedger))).scalars().all() == []

    async def test_within_allowance_writes_zero_included_rows(self, session, team) -> None:
        async def members(org_id: str) -> int | None:
            return 3

        await snapshot_org(session, team, DAY, member_counter=members)
        rows = list((await session.execute(select(GatewayCreditLedger))).scalars())
        assert [(row.credits, row.reason, row.quantity) for row in rows] == [(0, "included", 0), (0, "included", 0)]

    async def test_missing_member_count_skips_only_the_seat_row(self, session, team) -> None:
        async def members(org_id: str) -> int | None:
            return None

        written = await snapshot_org(session, team, DAY, member_counter=members)
        assert written["model_day"] is not None and written["seat_day"] is None
        rows = list((await session.execute(select(GatewayCreditLedger))).scalars())
        assert [row.unit for row in rows] == ["model_day"]

    async def test_idempotent_per_day(self, session, team) -> None:
        calls = 0

        async def members(org_id: str) -> int | None:
            nonlocal calls
            calls += 1
            return 12

        await snapshot_org(session, team, DAY, member_counter=members)
        again = await snapshot_org(session, team, DAY, member_counter=members)
        assert again == {"model_day": None, "seat_day": None}
        assert calls == 1  # the second pass never even calls Clerk
        assert len(list((await session.execute(select(GatewayCreditLedger))).scalars())) == 2


class TestRunAll:
    async def test_only_metered_billable_orgs_are_snapshotted(
        self, session, session_factory, team, monkeypatch
    ) -> None:
        monkeypatch.delenv("SP_BACKEND_URL", raising=False)
        await _seed_runs(session)
        session.add(GatewayProject(org_id=FREE_ORG, name="p", connection_name="c"))
        session.add(GatewayProject(org_id="org_local", name="p", connection_name="c"))
        await session.commit()
        assert await candidate_org_ids(session) == [ORG, FREE_ORG, "org_local"]

        entitlements = {
            ORG: team,
            FREE_ORG: OrgEntitlement(org_id=FREE_ORG, tier="free", status="none"),
            "org_local": local_entitlement("org_local"),
        }

        async def entitlement_for(org_id: str) -> OrgEntitlement:
            return entitlements[org_id]

        async def members(org_id: str) -> int | None:
            return 12

        rows = await run_credit_daily_snapshot(
            session_factory, day=DAY, member_counter=members, entitlement_for=entitlement_for
        )
        assert rows == 2
        async with session_factory() as check:
            orgs = {row.org_id for row in (await check.execute(select(GatewayCreditLedger))).scalars()}
        assert orgs == {ORG}
        assert (
            await run_credit_daily_snapshot(
                session_factory, day=DAY, member_counter=members, entitlement_for=entitlement_for
            )
            == 0
        )

    async def test_one_org_failure_does_not_stop_the_others(self, session, session_factory, team) -> None:
        session.add(GatewayProject(org_id="org_broken", name="p", connection_name="c"))
        session.add(GatewayProject(org_id=ORG, name="p", connection_name="c"))
        await session.commit()

        async def entitlement_for(org_id: str) -> OrgEntitlement:
            if org_id == "org_broken":
                raise RuntimeError("subscriptions down")
            return team

        async def members(org_id: str) -> int | None:
            return 1

        assert (
            await run_credit_daily_snapshot(
                session_factory, day=DAY, member_counter=members, entitlement_for=entitlement_for
            )
            == 2
        )


class TestLoopSchedule:
    def test_next_snapshot_is_00_05_utc(self) -> None:
        assert seconds_until_next_snapshot(datetime(2026, 9, 14, 0, 4, tzinfo=UTC)) == 60.0
        assert seconds_until_next_snapshot(datetime(2026, 9, 14, 0, 5, tzinfo=UTC)) == MAX_SLEEP_SECONDS
        assert seconds_until_next_snapshot(datetime(2026, 9, 14, 22, 0, tzinfo=UTC)) == 2 * 3600 + 300


class TestClerkMembers:
    async def test_no_secret_key_returns_none(self, monkeypatch) -> None:
        monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)
        assert await clerk_members.org_member_count("org_1") is None

    async def test_total_count_from_memberships(self, monkeypatch) -> None:
        monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_x")
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["auth"] = request.headers.get("authorization", "")
            return httpx.Response(200, content=json.dumps({"data": [{"id": "m1"}], "total_count": 12}))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await clerk_members.org_member_count("org_1", client=client) == 12
        assert seen["url"] == "https://api.clerk.com/v1/organizations/org_1/memberships?limit=1"
        assert seen["auth"] == "Bearer sk_test_x"

    async def test_http_error_returns_none(self, monkeypatch) -> None:
        monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_x")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, content="{}")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await clerk_members.org_member_count("org_1", client=client) is None
