"""
NALA warehouse generator — Domain 4 / raw_openexchange.

Mirror of the Open Exchange Rates API (openexchangerates.org) that the
fx-engine ingests from. Vendor style: USD-base rate maps, epoch-second
timestamps, 'base'/'rates' envelope.

Tables:
  currencies       (lookup of ISO code -> name)
  latest_rates     (one row per fetch x currency; recent fetches only)
  historical_rates (daily close per currency across the full epoch — thin TS)

Rates anchored on common.USD_FX with realistic daily drift.
"""
from __future__ import annotations

import datetime as dt
import math

from common import (
    connect, ensure_schema, apply_ddl_file, truncate, bulk_copy, rng,
    EPOCH_START, EPOCH_END, SEND_CURRENCIES, RECEIVE_MARKETS, STABLECOINS,
    USD_FX, ts_epoch_s, SCALE,
)

DDL = "sql/ddl/raw_openexchange.sql"

# Currency universe the vendor returns (USD base + everything NALA touches).
_QUOTES = []
for _c, (_ccy, _r) in RECEIVE_MARKETS.items():
    if _ccy not in _QUOTES:
        _QUOTES.append(_ccy)
for _c in SEND_CURRENCIES + STABLECOINS:
    if _c not in _QUOTES and _c != "USD":
        _QUOTES.append(_c)

_CCY_NAMES = {
    "USD": "United States Dollar", "GBP": "British Pound Sterling",
    "EUR": "Euro", "KES": "Kenyan Shilling", "TZS": "Tanzanian Shilling",
    "UGX": "Ugandan Shilling", "RWF": "Rwandan Franc", "NGN": "Nigerian Naira",
    "GHS": "Ghanaian Cedi", "XOF": "CFA Franc BCEAO", "XAF": "CFA Franc BEAC",
    "ZAR": "South African Rand", "INR": "Indian Rupee", "PKR": "Pakistani Rupee",
    "BDT": "Bangladeshi Taka", "PHP": "Philippine Peso",
    "USDC": "USD Coin", "USDT": "Tether", "PYUSD": "PayPal USD",
}


def _usd_rate(quote: str, day_index: int) -> float:
    """Units of `quote` per 1 USD on a given day, with slow drift."""
    r = rng("oxr", quote, day_index)
    base = USD_FX[quote]
    if quote in STABLECOINS:
        drift = 1.0 + (r.random() - 0.5) * 0.0008  # near-peg
    else:
        drift = 1.0 + 0.07 * math.sin((day_index + r.randint(0, 40)) / 50.0) \
                + (r.random() - 0.5) * 0.006
    return base * drift


def _gen_currencies():
    rows = [("USD", _CCY_NAMES["USD"], False, 2)]
    for q in _QUOTES:
        is_crypto = q in STABLECOINS
        decimals = 6 if is_crypto else (0 if q in ("UGX", "TZS", "RWF", "XOF", "XAF") else 2)
        rows.append((q, _CCY_NAMES.get(q, q), is_crypto, decimals))
    return rows


def _gen_historical():
    """Daily USD-base close per currency across the full epoch. Streamed."""
    total_days = (EPOCH_END - EPOCH_START).days
    rid = 0
    step = 7 if SCALE == "test" else 1  # weekly at test scale to stay tiny
    for day_index in range(0, total_days, step):
        day = EPOCH_START + dt.timedelta(days=day_index)
        close = dt.datetime.combine(day, dt.time(hour=23, minute=59, second=59))
        epoch = ts_epoch_s(close)
        ingest = close + dt.timedelta(hours=2)
        for quote in _QUOTES:
            rid += 1
            yield (
                rid, day.isoformat(), "USD", quote,
                round(_usd_rate(quote, day_index), 10),
                epoch,
                ingest.isoformat() + "+00",
            )


def _gen_latest():
    """Recent fetches: the engine polls /latest.json periodically. We keep the
    last ~120 days of fetches (every 6h) x currency. Demo-sized."""
    total_days = (EPOCH_END - EPOCH_START).days
    window_days = 120
    start = max(0, total_days - window_days)
    cadence_h = 6
    rid = 0
    for day_index in range(start, total_days):
        day = EPOCH_START + dt.timedelta(days=day_index)
        for hour in range(0, 24, cadence_h):
            ts = dt.datetime.combine(day, dt.time(hour=hour))
            epoch = ts_epoch_s(ts)
            fetched = ts + dt.timedelta(minutes=rng("oxr_fetch", day_index, hour).randint(0, 5))
            for quote in _QUOTES:
                r = rng("oxr_latest", quote, day_index, hour)
                base = _usd_rate(quote, day_index)
                intraday = base * (1 + (r.random() - 0.5) * 0.003)
                rid += 1
                # disclaimer mostly null (vendor only sets it occasionally)
                disclaimer = None if r.random() > 0.05 else \
                    "Usage subject to terms: https://openexchangerates.org/terms"
                yield (
                    rid, "USD", quote, round(intraday, 10),
                    epoch, fetched.isoformat() + "+00", disclaimer,
                )


def main(conn):
    ensure_schema(conn, "raw_openexchange")
    apply_ddl_file(conn, DDL)
    truncate(
        conn,
        "raw_openexchange.latest_rates", "raw_openexchange.historical_rates",
        "raw_openexchange.currencies",
    )

    n_ccy = bulk_copy(
        conn, "raw_openexchange.currencies",
        ["code", "name", "is_crypto", "decimals"],
        _gen_currencies(),
    )
    n_hist = bulk_copy(
        conn, "raw_openexchange.historical_rates",
        ["id", "rate_date", "base", "currency", "rate", "timestamp", "ingested_at"],
        _gen_historical(),
    )
    n_latest = bulk_copy(
        conn, "raw_openexchange.latest_rates",
        ["id", "base", "currency", "rate", "timestamp", "fetched_at", "disclaimer"],
        _gen_latest(),
    )

    print(f"[raw_openexchange] scale={SCALE} quotes={len(_QUOTES)}")
    print(f"[raw_openexchange] currencies={n_ccy} historical_rates={n_hist} "
          f"latest_rates={n_latest}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
