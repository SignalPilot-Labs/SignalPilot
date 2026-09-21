"""The rate card read from billing_rate_card (the backend's Stripe snapshot)."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from gateway.billing import rate_card

SNAPSHOT = {
    "loaded_at": 1_790_000_000.0,
    "rates": {
        "credit_cents": 1, "thread_credits": 50, "query_credits": 1, "model_month_credits": 600,
        "eval_run_credits": 50, "token_credits_per_dollar": 100, "overage_cents_per_credit": 1, "version": "2",
    },
    "plans": {
        "team": {"included_seats": 5, "seat_month_credits": 1500, "custom": False, "rank": 1},
        "scale": {"included_seats": 15, "seat_month_credits": 1500, "custom": False, "rank": 2},
        "enterprise": {"included_seats": 100, "seat_month_credits": None, "custom": True, "rank": 3},
    },
}


@pytest.fixture(autouse=True)
def _clear():
    rate_card.install(None)
    yield
    rate_card.install(None)


class _Row(dict):
    pass


def _factory_returning(row):
    class _Result:
        def mappings(self):
            return self

        def first(self):
            return row

    class _Session:
        async def execute(self, stmt):
            return _Result()

    @asynccontextmanager
    async def _session():
        yield _Session()

    return lambda: _session


def test_from_snapshot_reads_rates_and_seat_prices() -> None:
    card = rate_card.from_snapshot(SNAPSHOT, "2")
    assert (card.thread_credits, card.query_credits, card.eval_run_credits) == (50, 1, 50)
    assert (card.model_month_credits, card.token_credits_per_usd, card.version) == (600, 100, "2")
    assert card.seat_rate("team") == 1500 and card.seat_rate("enterprise") is None
    assert card.seat_rate("free") is None


def test_from_snapshot_rejects_incomplete_rates() -> None:
    with pytest.raises(ValueError):
        rate_card.from_snapshot({"rates": {"thread_credits": 50}, "plans": {}})


def test_current_raises_until_loaded() -> None:
    with pytest.raises(rate_card.RateCardUnavailable):
        rate_card.current()
    rate_card.install(rate_card.from_snapshot(SNAPSHOT))
    assert rate_card.current().thread_credits == 50
    assert rate_card.seat_month_credits("scale") == 1500


@pytest.mark.asyncio
async def test_refresh_reads_the_shared_row(monkeypatch) -> None:
    monkeypatch.setattr("gateway.db.engine.get_session_factory", _factory_returning(_Row(snapshot=SNAPSHOT, rates_version="2")), raising=False)
    card = await rate_card.refresh()
    assert card is not None and card.version == "2" and not rate_card.is_stale()
    assert await rate_card.require() is card  # fresh: no second read


@pytest.mark.asyncio
async def test_refresh_keeps_last_good_card_on_failure(monkeypatch) -> None:
    good = rate_card.from_snapshot(SNAPSHOT)
    rate_card.install(good, ttl_seconds=0)  # stale straight away

    def boom():
        raise ConnectionError("db down")

    monkeypatch.setattr("gateway.db.engine.get_session_factory", boom, raising=False)
    assert await rate_card.require() is good

    monkeypatch.setattr("gateway.db.engine.get_session_factory", _factory_returning(None), raising=False)
    assert await rate_card.require() is good  # empty table: still the last good card


@pytest.mark.asyncio
async def test_require_returns_none_when_nothing_was_ever_loaded(monkeypatch) -> None:
    monkeypatch.setattr("gateway.db.engine.get_session_factory", _factory_returning(None), raising=False)
    assert await rate_card.require() is None
