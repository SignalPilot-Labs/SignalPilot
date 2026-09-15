"""Rate constants, plan allowances, period helpers, and the daily share carry."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from gateway.billing import rates
from gateway.billing.identity import is_service_identity, service_identity


class TestRates:
    def test_rate_card(self) -> None:
        assert rates.THREAD_CREDITS == 50
        assert rates.QUERY_CREDITS == 1
        assert rates.MODEL_MONTH_CREDITS == 600
        assert rates.EVAL_RUN_CREDITS == 50
        assert rates.SEAT_MONTH_CREDITS == 1000
        assert rates.ENTERPRISE_SEAT_MONTH_CREDITS == 1500
        assert rates.TOKEN_CREDITS_PER_USD == 100
        assert rates.GRACE_DAYS == 14
        assert rates.RATES["thread"] == 50 and rates.RATES["query"] == 1

    def test_rates_are_read_only(self) -> None:
        with pytest.raises(TypeError):
            rates.RATES["thread"] = 1  # type: ignore[index]

    @pytest.mark.parametrize(
        ("tier", "seats", "models", "eval_runs", "credits"),
        [
            ("team", 10, 30, 30, 5000),
            ("scale", 25, 50, 30, 12500),
            ("enterprise", 100, 100, 30, 75000),
            ("free", 0, 0, 0, 0),
        ],
    )
    def test_plan_allowances(self, tier: str, seats: int, models: int, eval_runs: int, credits: int) -> None:
        allowance = rates.PLAN_ALLOWANCES[tier]
        assert (allowance["seats"], allowance["models"], allowance["eval_runs"], allowance["credits"]) == (
            seats,
            models,
            eval_runs,
            credits,
        )

    def test_seat_rate_by_tier(self) -> None:
        assert rates.seat_month_credits("enterprise") == 1500
        assert rates.seat_month_credits("team") == 1000
        assert rates.seat_month_credits("scale") == 1000

    def test_billable_tiers(self) -> None:
        assert rates.BILLABLE_TIERS == {"team", "scale", "enterprise"}


class TestPeriods:
    def test_period_of_date_and_naive_datetime(self) -> None:
        assert rates.period_of(date(2026, 9, 14)) == date(2026, 9, 1)
        assert rates.period_of(datetime(2026, 2, 28, 23, 59)) == date(2026, 2, 1)

    def test_period_of_uses_utc_month_boundary(self) -> None:
        pacific = timezone(timedelta(hours=-7))
        late_local = datetime(2026, 9, 30, 20, 0, tzinfo=pacific)  # 03:00 UTC on 1 Oct
        assert rates.period_of(late_local) == date(2026, 10, 1)
        early_east = datetime(2026, 10, 1, 1, 0, tzinfo=timezone(timedelta(hours=2)))  # 23:00 UTC on 30 Sep
        assert rates.period_of(early_east) == date(2026, 9, 1)
        assert rates.period_of(datetime(2026, 10, 1, 0, 0, tzinfo=UTC)) == date(2026, 10, 1)

    def test_current_period(self) -> None:
        assert rates.current_period(datetime(2026, 12, 31, 23, 59, tzinfo=UTC)) == date(2026, 12, 1)
        assert rates.current_period() == rates.period_of(datetime.now(UTC))

    @pytest.mark.parametrize(
        ("period", "days"),
        [(date(2026, 2, 1), 28), (date(2028, 2, 1), 29), (date(2026, 9, 1), 30), (date(2026, 12, 1), 31)],
    )
    def test_days_in_period(self, period: date, days: int) -> None:
        assert rates.days_in_period(period) == days

    def test_period_end(self) -> None:
        assert rates.period_end(date(2026, 9, 1)) == date(2026, 10, 1)
        assert rates.period_end(date(2026, 12, 1)) == date(2027, 1, 1)


class TestDailyShare:
    @pytest.mark.parametrize("rate", [600, 1000, 1500, 1, 7])
    @pytest.mark.parametrize("period", [date(2026, 2, 1), date(2028, 2, 1), date(2026, 9, 1), date(2026, 10, 1)])
    def test_daily_rows_sum_exactly_to_the_month_rate(self, rate: int, period: date) -> None:
        days = rates.days_in_period(period)
        shares = [rates.daily_credit_share(rate, period + timedelta(days=i)) for i in range(days)]
        assert sum(shares) == rate
        assert max(shares) - min(shares) <= 1
        assert all(share >= 0 for share in shares)

    def test_600_over_30_days_is_20_per_day(self) -> None:
        assert rates.daily_credit_share(600, date(2026, 9, 3)) == 20

    def test_remainder_is_carried_not_dropped(self) -> None:
        # 1000 / 31 = 32.26...; days alternate 32/33 and the total is exact.
        shares = [rates.daily_credit_share(1000, date(2026, 10, 1) + timedelta(days=i)) for i in range(31)]
        assert set(shares) == {32, 33}
        assert sum(shares) == 1000


class TestServiceIdentity:
    def test_context_manager_marks_work_as_service(self) -> None:
        assert not is_service_identity()
        with service_identity():
            assert is_service_identity()
            assert is_service_identity("user_123")
        assert not is_service_identity()

    @pytest.mark.parametrize(
        "ctx",
        ["system", "gateway", "service:dbt-map", {"user_id": "system"}, {"is_service": True}, {"source": "system"}],
    )
    def test_service_markers(self, ctx) -> None:
        assert is_service_identity(ctx)

    @pytest.mark.parametrize(
        "ctx", [None, "user_123", "eval-runner", "local", {"user_id": "user_1", "source": "chat"}, {}]
    )
    def test_customer_work_is_not_service(self, ctx) -> None:
        assert not is_service_identity(ctx)

    def test_object_attributes(self) -> None:
        class Ctx:
            user_id = "user_1"
            source = "mcp"
            is_service = False

        assert not is_service_identity(Ctx())
        Ctx.user_id = "service:readiness"
        assert is_service_identity(Ctx())
