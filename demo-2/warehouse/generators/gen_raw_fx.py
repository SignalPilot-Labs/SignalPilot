"""
NALA warehouse generator — Domain 4 / raw_fx.

Internal FX engine + pricing/treasury slice:
  rate_providers (lookup), fx_rates (FACT hourly time series, capped),
  fx_rate_snapshots, pricing_margins, corridor_pricing, fx_pnl, fx_hedges.

Rates are anchored on common.USD_FX with realistic daily + hourly drift.
fx_rates is the only big table and is STREAMED row-by-row. Its volume is
explicitly capped (see MAX_FX_ROWS) so the demo stays under ~5M rows; the
cadence between ticks is widened automatically to honour the cap.
"""
from __future__ import annotations

import datetime as dt
import json
import math

from common import (
    connect, ensure_schema, apply_ddl_file, truncate, bulk_copy, rng,
    EPOCH_START, EPOCH_END, SEND_CURRENCIES, RECEIVE_MARKETS, STABLECOINS,
    USD_FX, ts_isoz, ts_epoch_ms, maybe_null, SCALE,
)

DDL = "sql/ddl/raw_fx.sql"

# Distinct receive currencies across all markets, de-duplicated, stable order.
_RECV_CCYS = []
for _c, (_ccy, _rails) in RECEIVE_MARKETS.items():
    if _ccy not in _RECV_CCYS:
        _RECV_CCYS.append(_ccy)

# Curated currency-pair universe the engine actually quotes:
#   * every SEND currency -> every receive currency (the corridors NALA prices)
#   * USD -> every receive currency (the treasury / base board)
#   * SEND<->SEND majors (GBP/USD, EUR/USD, GBP/EUR)
#   * USD -> each stablecoin (peg monitoring)
def _build_pairs() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(b: str, q: str):
        if b != q and (b, q) not in seen:
            seen.add((b, q))
            pairs.append((b, q))

    for base in SEND_CURRENCIES:
        for q in _RECV_CCYS:
            add(base, q)
    for q in _RECV_CCYS:
        add("USD", q)
    for q in SEND_CURRENCIES:
        add("USD", q)
    add("GBP", "USD"); add("EUR", "USD"); add("GBP", "EUR")
    for s in STABLECOINS:
        add("USD", s)
    return pairs

PAIRS = _build_pairs()

# Row cap for fx_rates. Pick the finest cadence (in hours) that keeps
# pairs * ticks <= MAX_FX_ROWS over the full EPOCH window.
MAX_FX_ROWS = 4_500_000

PROVIDERS = [
    (1, "OPENEXCHANGE", "Open Exchange Rates", "primary",   0.6000, True),
    (2, "REUTERS",      "Refinitiv / Reuters", "primary",   0.3000, True),
    (3, "ECB",          "European Central Bank reference", "reference", 0.1000, True),
    (4, "XE",           "XE.com",              "fallback",  0.0000, True),
    (5, "INTERNAL_BLEND", "fx-engine blended", "primary",   1.0000, True),
    (6, "BLOOMBERG",    "Bloomberg BGN",       "fallback",  0.0000, False),  # decommissioned
]


def _base_rate(base: str, quote: str) -> float:
    """Mid rate = units of quote per 1 base, from USD anchors."""
    return USD_FX[quote] / USD_FX[base]


def _drift(r, day_index: int, hour: int, base: str, quote: str) -> float:
    """Deterministic daily + hourly multiplicative drift around 1.0."""
    # Slow daily trend (random walk-ish via sin blend) + small hourly noise.
    daily = 1.0 + 0.06 * math.sin((day_index + r.randint(0, 30)) / 45.0)
    intraday = 1.0 + (r.random() - 0.5) * 0.004  # +/-0.2% hourly noise
    # Stablecoins barely move.
    if quote in STABLECOINS or base in STABLECOINS:
        daily = 1.0 + (daily - 1.0) * 0.02
        intraday = 1.0 + (intraday - 1.0) * 0.02
    return daily * intraday


# ---------------------------------------------------------------------------
def _stream_fx_rates(cadence_hours: int):
    """Yield fx_rates rows, streamed. rate_id is a dense bigint counter."""
    total_days = (EPOCH_END - EPOCH_START).days
    rate_id = 0
    for day_index in range(total_days):
        day = EPOCH_START + dt.timedelta(days=day_index)
        for hour in range(0, 24, cadence_hours):
            ts = dt.datetime.combine(day, dt.time(hour=hour))
            for base, quote in PAIRS:
                r = rng("fx_rate", base, quote, day_index, hour)
                mid = _base_rate(base, quote) * _drift(r, day_index, hour, base, quote)
                # Spread wider for exotic/illiquid quotes, tight for majors/stables.
                if quote in STABLECOINS or base in STABLECOINS:
                    half_bps = r.uniform(1, 6)
                elif quote in ("USD", "GBP", "EUR") and base in ("USD", "GBP", "EUR"):
                    half_bps = r.uniform(2, 12)
                else:
                    half_bps = r.uniform(15, 70)
                half = mid * (half_bps / 10_000.0)
                bid = mid - half
                ask = mid + half
                spread_bps = round((ask - bid) / mid * 10_000.0, 4)
                provider_id = r.choice([1, 2, 5, 5, 5])  # blend dominates
                is_stale = r.random() < 0.015
                rate_id += 1
                yield (
                    rate_id,
                    base,
                    quote,
                    f"{base}/{quote}",
                    round(mid, 8),
                    round(bid, 8),
                    round(ask, 8),
                    spread_bps,
                    provider_id,
                    ts_isoz(ts),
                    ts_epoch_ms(ts),
                    ts_isoz(ts).replace("T", " ").replace(".000Z", "+00"),
                    is_stale,
                )


def _gen_snapshots(cadence_hours: int):
    """Hourly-ish board snapshots: jsonb map of USD-base rates. Small table."""
    total_days = (EPOCH_END - EPOCH_START).days
    snap_id = 0
    # Coarser cadence for the cached board (every 6h) to keep this table small.
    snap_cadence = max(6, cadence_hours)
    rows = []
    for day_index in range(total_days):
        day = EPOCH_START + dt.timedelta(days=day_index)
        for hour in range(0, 24, snap_cadence):
            ts = dt.datetime.combine(day, dt.time(hour=hour))
            r = rng("fx_snap", day_index, hour)
            board = {}
            for quote in _RECV_CCYS + SEND_CURRENCIES + STABLECOINS:
                if quote == "USD":
                    continue
                mid = _base_rate("USD", quote) * _drift(r, day_index, hour, "USD", quote)
                board[quote] = round(mid, 6)
            snap_id += 1
            source_label = r.choice(
                ["fx-engine.v2", "fx-engine.v2", "fx-engine.v2", "legacy_cron", "PRICING_CACHE_OLD"]
            )
            rows.append((
                snap_id,
                ts,
                "USD",
                json.dumps(board),
                r.choice([1, 2, 5]),
                len(board),
                source_label,
            ))
    return rows


def _gen_pricing_margins():
    rows = []
    mid = 0
    segments = ["consumer", "consumer", "rafiki", "vip"]
    for send in SEND_CURRENCIES:
        for recv in _RECV_CCYS:
            for seg in set(segments):
                mid += 1
                r = rng("margin", send, recv, seg)
                base_bps = {"consumer": 90, "rafiki": 60, "vip": 45}[seg]
                margin_bps = round(base_bps + r.uniform(-15, 35), 4)
                # Some corridors have a superseded historical row + a current row.
                has_history = r.random() < 0.30
                eff_from = EPOCH_START + dt.timedelta(days=r.randint(0, 800))
                if has_history:
                    eff_to = eff_from + dt.timedelta(days=r.randint(120, 600))
                else:
                    eff_to = None
                is_deleted = r.random() < 0.05
                rows.append((
                    mid, send, recv, seg,
                    margin_bps,
                    round(margin_bps * 0.5, 4),
                    round(margin_bps * 1.8, 4),
                    eff_from.isoformat(),
                    eff_to.isoformat() if eff_to else None,
                    is_deleted,
                    (eff_from + dt.timedelta(days=30)).isoformat() + " 00:00:00+00" if is_deleted else None,
                    (eff_from + dt.timedelta(days=r.randint(1, 60))).isoformat() + " 12:00:00+00",
                ))
    return rows


def _gen_corridor_pricing():
    rows = []
    cid = 0
    fee_ccy_for = {"GBP": "GBP", "USD": "USD", "EUR": "EUR"}
    for send in SEND_CURRENCIES:
        for rc, (recv_ccy, rails) in RECEIVE_MARKETS.items():
            for method in rails:
                cid += 1
                r = rng("corridor_pricing", send, rc, method)
                is_mm = method not in ("Bank",)
                # mobile money usually fee-free; bank ~0.99
                fee = 0.00 if is_mm else round(r.choice([0.99, 0.99, 1.99]), 2)
                if r.random() < 0.10:  # some corridors carry a nominal charge
                    fee = round(r.choice([1.99, 2.99, 3.99]), 2)
                margin_bps = round(r.uniform(50, 150), 4)
                rows.append((
                    cid, send, None, recv_ccy, rc, method,
                    fee, fee_ccy_for[send], margin_bps,
                    r.random() < 0.18,                       # promo_active
                    round(r.choice([1.0, 2.0, 5.0]), 2),     # min_send
                    round(r.choice([5000.0, 5000.0, 3000.0]), 2),  # max_send
                    r.random() > 0.04,                       # isActive (legacy)
                    (EPOCH_START + dt.timedelta(days=r.randint(0, 1500))).isoformat(),
                    (EPOCH_END - dt.timedelta(days=r.randint(0, 400))).isoformat() + " 09:00:00+00",
                ))
    # fill send_country (denormalized, sometimes left null = messy)
    fixed = []
    for row in rows:
        row = list(row)
        rr = rng("corridor_country", row[0])
        row[2] = maybe_null({"GBP": "GB", "USD": "US", "EUR": "FR"}[row[1]], 0.25, rr)
        fixed.append(tuple(row))
    return fixed


def _gen_fx_pnl():
    """Daily P&L per pair, sampled to a tractable set of treasury pairs."""
    treasury_pairs = [("USD", q) for q in _RECV_CCYS] + \
                     [("GBP", "USD"), ("EUR", "USD")]
    rows = []
    pid = 0
    total_days = (EPOCH_END - EPOCH_START).days
    # Weekly P&L marks (Mondays) keep this table demo-sized.
    for day_index in range(0, total_days, 7):
        day = EPOCH_START + dt.timedelta(days=day_index)
        # business grew: scale volume by how far through the epoch we are
        growth = (day_index / total_days) ** 1.5
        for base, quote in treasury_pairs:
            r = rng("fx_pnl", base, quote, day_index)
            vol = round(r.uniform(5_000, 200_000) * (0.1 + growth), 2)
            realized = round(vol * r.uniform(0.002, 0.012), 2)
            unreal = round(vol * r.uniform(-0.004, 0.004), 2)
            mid = _base_rate(base, quote)
            pid += 1
            rows.append((
                pid, day.isoformat(), base, quote,
                vol, realized, unreal,
                round(r.uniform(45, 130), 4),
                round(vol * mid, 2), quote,
                day.isoformat() + " 23:00:00+00",
            ))
    return rows


def _gen_fx_hedges():
    from common import det_uuid
    rows = []
    total_days = (EPOCH_END - EPOCH_START).days
    counterparties = ["MUFG", "Citi", "StoneX", "Goldman Sachs", "JPMorgan", "Standard Chartered"]
    n_hedges = 60 if SCALE == "test" else 1500
    for i in range(n_hedges):
        r = rng("fx_hedge", i)
        base = "USD"
        quote = r.choice(_RECV_CCYS + ["GBP", "EUR"])
        instrument = r.choice(["spot", "forward", "forward", "swap"])
        trade_day = EPOCH_START + dt.timedelta(days=r.randint(0, total_days - 1))
        if instrument == "spot":
            value_day = trade_day + dt.timedelta(days=2)
        else:
            value_day = trade_day + dt.timedelta(days=r.choice([30, 60, 90, 180]))
        settled = value_day < EPOCH_END
        status = "settled" if settled else "open"
        if r.random() < 0.04:
            status = "cancelled"
        notional = round(r.uniform(50_000, 5_000_000), 2)
        strike = round(_base_rate(base, quote) * (1 + (r.random() - 0.5) * 0.03), 8)
        mtm = round(notional * (r.random() - 0.5) * 0.02, 2)
        rows.append((
            det_uuid(("fx_hedge", i)),
            instrument, base, quote, notional, base, strike,
            r.choice(counterparties),
            trade_day.isoformat(),
            value_day.isoformat(),
            status, mtm,
            trade_day.isoformat() + " 10:30:00+00",
            value_day.isoformat() + " 17:00:00+00",
        ))
    return rows


# ---------------------------------------------------------------------------
def main(conn):
    ensure_schema(conn, "raw_fx")
    apply_ddl_file(conn, DDL)
    truncate(
        conn,
        "raw_fx.fx_rates", "raw_fx.fx_rate_snapshots", "raw_fx.pricing_margins",
        "raw_fx.corridor_pricing", "raw_fx.rate_providers", "raw_fx.fx_pnl",
        "raw_fx.fx_hedges",
    )

    # rate_providers (lookup)
    _prov_created = (EPOCH_START + dt.timedelta(days=1)).isoformat() + " 00:00:00+00"
    bulk_copy(conn, "raw_fx.rate_providers",
              ["provider_id", "provider_code", "provider_name", "tier", "weight",
               "is_active", "created_at"],
              [(p[0], p[1], p[2], p[3], p[4], p[5], _prov_created) for p in PROVIDERS])

    # Compute cadence to honour the row cap for fx_rates.
    total_days = (EPOCH_END - EPOCH_START).days
    cadence_hours = 1
    while len(PAIRS) * total_days * (24 // cadence_hours) > MAX_FX_ROWS and cadence_hours < 24:
        cadence_hours += 1
    # At test scale shrink hard so the self-test is fast.
    if SCALE == "test":
        cadence_hours = 24  # one tick/day

    n_rates = bulk_copy(
        conn, "raw_fx.fx_rates",
        ["rate_id", "base_currency", "quote_currency", "pair", "mid_rate",
         "bid_rate", "ask_rate", "spread_bps", "provider_id", "ts_iso",
         "ts_epoch_ms", "ingested_at", "is_stale"],
        _stream_fx_rates(cadence_hours),
    )

    n_snap = bulk_copy(
        conn, "raw_fx.fx_rate_snapshots",
        ["snapshot_id", "snapshot_at", "base_currency", "rates", "provider_id",
         "rate_count", "source_label"],
        _gen_snapshots(cadence_hours),
    )

    n_margin = bulk_copy(
        conn, "raw_fx.pricing_margins",
        ["margin_id", "send_currency", "receive_currency", "customer_segment",
         "margin_bps", "min_margin_bps", "max_margin_bps", "effective_from",
         "effective_to", "is_deleted", "deleted_at", "updated_at"],
        _gen_pricing_margins(),
    )

    n_corr = bulk_copy(
        conn, "raw_fx.corridor_pricing",
        ["corridor_pricing_id", "send_currency", "send_country", "receive_currency",
         "receive_country", "payout_method", "fixed_fee_amount", "fixed_fee_ccy",
         "fx_margin_bps", "promo_active", "min_send_amount", "max_send_amount",
         "isActive", "effective_from", "updated_at"],
        _gen_corridor_pricing(),
    )

    n_pnl = bulk_copy(
        conn, "raw_fx.fx_pnl",
        ["pnl_id", "pnl_date", "base_currency", "quote_currency", "volume_usd",
         "realized_pnl_usd", "unrealized_pnl_usd", "avg_margin_bps",
         "notional_local", "notional_ccy", "created_at"],
        _gen_fx_pnl(),
    )

    n_hedge = bulk_copy(
        conn, "raw_fx.fx_hedges",
        ["hedge_id", "instrument", "base_currency", "quote_currency", "notional",
         "notional_ccy", "strike_rate", "counterparty", "trade_date", "value_date",
         "status", "mark_to_market_usd", "created_at", "updated_at"],
        _gen_fx_hedges(),
    )

    print(f"[raw_fx] scale={SCALE} pairs={len(PAIRS)} cadence_hours={cadence_hours}")
    print(f"[raw_fx] providers={len(PROVIDERS)} fx_rates={n_rates} snapshots={n_snap} "
          f"margins={n_margin} corridor_pricing={n_corr} fx_pnl={n_pnl} hedges={n_hedge}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
