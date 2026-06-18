"""
gen_raw_google_ads — Google Ads acquisition spend.

Tables: campaigns, ad_groups, ad_performance_daily (fact, aggregate daily).
No customer PII (aggregate ad metrics only). Money in MICROS (1e6 units).
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from common import (
    connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    rng, rand_datetime, maybe_null, ts_iso, EPOCH_START, EPOCH_END,
    SEND_CURRENCIES, N,
)

DDL = Path(__file__).resolve().parent.parent / "sql" / "ddl" / "raw_google_ads.sql"

CHANNEL_TYPES = ["SEARCH", "DISPLAY", "VIDEO", "PERFORMANCE_MAX", "SEARCH"]
BID_STRATEGIES = ["TARGET_CPA", "MAXIMIZE_CONVERSIONS", "TARGET_ROAS",
                  "MAXIMIZE_CLICKS"]
DEVICES = ["MOBILE", "MOBILE", "MOBILE", "DESKTOP", "TABLET"]
GEO_THEMES = ["UK Brand", "UK Generic", "US Brand", "US Generic", "EU Remittance",
              "Kenya Send", "Nigeria Send", "Diaspora App Install",
              "Competitor Conquest", "Retargeting"]

# Three Google Ads accounts (one per send region) — NOT NALA customers.
ACCOUNTS = {"GBP": 7100000001, "USD": 7100000002, "EUR": 7100000003}


def gen_campaigns(n):
    rows = []
    for i in range(n):
        r = rng("gads_campaign", i)
        ccy = SEND_CURRENCIES[i % len(SEND_CURRENCIES)]
        start = rand_datetime(r).date()
        ongoing = r.random() < 0.6
        rows.append((
            8000000000 + i,
            ACCOUNTS[ccy],
            f"{ccy} | {r.choice(GEO_THEMES)} | {start.year}",
            r.choice(["ENABLED", "ENABLED", "PAUSED", "REMOVED"]),
            r.choice(CHANNEL_TYPES),
            r.choice(BID_STRATEGIES),
            r.randint(20, 2000) * 1_000_000,        # daily budget micros
            start,
            None if ongoing else (start + dt.timedelta(days=r.randint(30, 400))),
            json.dumps([ccy.lower(), "acquisition"]),
            ts_iso(rand_datetime(r)),
        ))
    return rows


def gen_ad_groups(campaign_rows):
    rows = []
    ag_id = 9000000000
    for camp in campaign_rows:
        r = rng("gads_adgroup", camp[0])
        for _ in range(r.randint(2, 5)):
            rows.append((
                ag_id,
                camp[0],
                f"AG {r.randint(1,99)} - {r.choice(['Exact','Phrase','Broad','RSA'])}",
                r.choice(["ENABLED", "ENABLED", "PAUSED"]),
                "SEARCH_STANDARD" if camp[4] == "SEARCH" else "DISPLAY_STANDARD",
                r.randint(5, 500) * 100_000,
                ts_iso(rand_datetime(r)),
            ))
            ag_id += 1
    return rows


def gen_performance(ad_group_rows, campaign_by_id, n_days):
    """One row per ad_group per day (recent window), per dominant device."""
    end = EPOCH_END
    start = end - dt.timedelta(days=n_days)
    pid = 0
    acct_ccy = {v: k for k, v in ACCOUNTS.items()}
    for ag in ad_group_rows:
        ag_id, camp_id = ag[0], ag[1]
        camp = campaign_by_id[camp_id]
        ccy = acct_ccy.get(camp[1], "USD")
        # campaign active window
        c_start = camp[7]
        for d_off in range(n_days):
            day = start + dt.timedelta(days=d_off)
            if day < c_start:
                continue
            r = rng("gads_perf", ag_id, d_off)
            if r.random() < 0.25:      # not every group spends every day
                continue
            dev = r.choice(DEVICES)
            impr = r.randint(50, 8000)
            clicks = int(impr * r.uniform(0.005, 0.06))
            cost_micros = clicks * r.randint(150_000, 1_800_000)  # micros
            conv = round(clicks * r.uniform(0.0, 0.12), 2)
            conv_val = round(conv * r.uniform(40, 600), 2)
            ctr = round(clicks / impr, 5) if impr else None
            yield (
                pid,
                day,
                camp_id,
                ag_id,
                dev,
                impr,
                clicks,
                cost_micros,
                conv,
                conv_val,
                ccy,
                maybe_null(ctr, 0.1, r),   # ~10% stale/null precomputed ctr
                ts_iso(dt.datetime.combine(day, dt.time(3, 0))),
            )
            pid += 1


def main(conn):
    ensure_schema(conn, "raw_google_ads")
    apply_ddl_file(conn, DDL)
    truncate(conn,
             "raw_google_ads.ad_performance_daily",
             "raw_google_ads.ad_groups", "raw_google_ads.campaigns")

    n_campaigns = max(9, N["customers"] // 40)
    # window of daily perf rows; scale-aware but bounded
    n_days = 60 if N["customers"] <= 1000 else 365

    camp_rows = gen_campaigns(n_campaigns)
    ag_rows = gen_ad_groups(camp_rows)
    campaign_by_id = {row[0]: row for row in camp_rows}

    c1 = bulk_copy(conn, "raw_google_ads.campaigns",
                   ["campaign_id", "customer_id", "name", "status",
                    "advertising_channel_type", "bidding_strategy_type",
                    "campaign_budget_micros", "start_date", "end_date",
                    "labels", "created_at"], camp_rows)
    c2 = bulk_copy(conn, "raw_google_ads.ad_groups",
                   ["ad_group_id", "campaign_id", "name", "status", "type",
                    "cpc_bid_micros", "created_at"], ag_rows)
    c3 = bulk_copy(conn, "raw_google_ads.ad_performance_daily",
                   ["id", "date", "campaign_id", "ad_group_id", "device",
                    "impressions", "clicks", "cost_micros", "conversions",
                    "conversions_value", "currency_code", "ctr", "loaded_at"],
                   gen_performance(ag_rows, campaign_by_id, n_days))

    print(f"raw_google_ads: campaigns={c1} ad_groups={c2} "
          f"ad_performance_daily={c3}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
