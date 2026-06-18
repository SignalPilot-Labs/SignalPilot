"""
gen_raw_meta_ads — Meta (Facebook/Instagram) acquisition spend.

Tables: campaigns, ad_sets, ad_insights_daily (fact, aggregate daily).
No customer PII. Money: budgets are DECIMAL strings in MINOR units (cents),
spend in ad_insights is major-unit numeric. Timestamps ISO with tz offset.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from common import (
    connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    rng, rand_datetime, maybe_null, EPOCH_END, SEND_CURRENCIES, N,
)

DDL = Path(__file__).resolve().parent.parent / "sql" / "ddl" / "raw_meta_ads.sql"

OBJECTIVES = ["OUTCOME_APP_PROMOTION", "OUTCOME_TRAFFIC", "OUTCOME_LEADS",
              "OUTCOME_AWARENESS", "OUTCOME_APP_PROMOTION"]
OPT_GOALS = ["APP_INSTALLS", "OFFSITE_CONVERSIONS", "LINK_CLICKS",
             "LANDING_PAGE_VIEWS"]
PLATFORMS = ["facebook", "facebook", "instagram", "instagram", "audience_network"]
THEMES = ["Diaspora App Install", "UK Awareness", "US Awareness", "EU Remittance",
          "Kenya Send Home", "Nigeria Send Home", "Retargeting", "Lookalike Senders"]

ACCOUNTS = {"GBP": "act_5510001", "USD": "act_5510002", "EUR": "act_5510003"}


def _meta_ts(d):
    return d.strftime("%Y-%m-%dT%H:%M:%S+0000")


def gen_campaigns(n):
    rows = []
    for i in range(n):
        r = rng("meta_campaign", i)
        ccy = SEND_CURRENCIES[i % len(SEND_CURRENCIES)]
        status = r.choice(["ACTIVE", "ACTIVE", "PAUSED", "ARCHIVED", "DELETED"])
        eff = status if r.random() < 0.85 else r.choice(["ACTIVE", "PAUSED",
                                                         "WITH_ISSUES"])
        created = rand_datetime(r)
        rows.append((
            str(23840000000000000 + i),
            ACCOUNTS[ccy],
            f"{ccy} | {r.choice(THEMES)}",
            r.choice(OBJECTIVES),
            status,
            eff,
            str(r.randint(2000, 200000)),       # daily_budget minor units (cents)
            r.choice(["AUCTION", "AUCTION", "RESERVED"]),
            _meta_ts(created),
            _meta_ts(rand_datetime(r)),
            json.dumps({"special_ad_categories": []}),
        ))
    return rows


def gen_ad_sets(campaign_rows):
    rows = []
    asid = 23850000000000000
    for camp in campaign_rows:
        r = rng("meta_adset", camp[0])
        for _ in range(r.randint(1, 4)):
            rows.append((
                str(asid),
                camp[0],
                f"AdSet {r.randint(1,99)} - {r.choice(['Broad','LAL1%','Interest','Retgt'])}",
                r.choice(["ACTIVE", "ACTIVE", "PAUSED"]),
                r.choice(OPT_GOALS),
                r.choice(["IMPRESSIONS", "LINK_CLICKS"]),
                maybe_null(str(r.randint(50, 5000)), 0.5, r),   # bid_amount, sparse
                str(r.randint(1000, 50000)),                    # daily_budget minor units
                json.dumps({"geo_locations": {"countries": [r.choice(["GB", "US", "FR", "KE", "NG"])]},
                            "age_min": 18, "age_max": 65}),
                _meta_ts(rand_datetime(r)),
            ))
            asid += 1
    return rows


def gen_insights(ad_set_rows, campaign_by_id, n_days):
    end = EPOCH_END
    start = end - dt.timedelta(days=n_days)
    acct_ccy = {v: k for k, v in ACCOUNTS.items()}
    iid = 0
    for ads in ad_set_rows:
        as_id, camp_id = ads[0], ads[1]
        camp = campaign_by_id[camp_id]
        acct = camp[1]
        ccy = acct_ccy.get(acct, "USD")
        for d_off in range(n_days):
            day = start + dt.timedelta(days=d_off)
            r = rng("meta_insight", as_id, d_off)
            if r.random() < 0.3:
                continue
            plat = r.choice(PLATFORMS)
            impr = r.randint(100, 20000)
            clicks = int(impr * r.uniform(0.003, 0.04))
            spend = round(impr * r.uniform(0.002, 0.02), 2)
            reach = int(impr * r.uniform(0.6, 0.95))
            installs = max(0, int(clicks * r.uniform(0.0, 0.2)))
            purchases = max(0, int(installs * r.uniform(0.0, 0.4)))
            actions = []
            if installs:
                actions.append({"action_type": "mobile_app_install", "value": str(installs)})
            if purchases:
                actions.append({"action_type": "offsite_conversion.fb_pixel_purchase",
                                "value": str(purchases)})
            if clicks:
                actions.append({"action_type": "link_click", "value": str(clicks)})
            yield (
                iid,
                day,
                day,                                # date_stop == date_start
                acct,
                camp_id,
                as_id,
                plat,
                impr,
                clicks,
                spend,
                reach,
                json.dumps(actions) if actions else None,
                ccy,
                dt.datetime.combine(day, dt.time(4, 0)).strftime("%Y-%m-%d %H:%M:%S"),
            )
            iid += 1


def main(conn):
    ensure_schema(conn, "raw_meta_ads")
    apply_ddl_file(conn, DDL)
    truncate(conn,
             "raw_meta_ads.ad_insights_daily",
             "raw_meta_ads.ad_sets", "raw_meta_ads.campaigns")

    n_campaigns = max(9, N["customers"] // 50)
    n_days = 60 if N["customers"] <= 1000 else 365

    camp_rows = gen_campaigns(n_campaigns)
    as_rows = gen_ad_sets(camp_rows)
    campaign_by_id = {row[0]: row for row in camp_rows}

    c1 = bulk_copy(conn, "raw_meta_ads.campaigns",
                   ["id", "account_id", "name", "objective", "status",
                    "effective_status", "daily_budget", "buying_type",
                    "created_time", "updated_time", "metadata"], camp_rows)
    c2 = bulk_copy(conn, "raw_meta_ads.ad_sets",
                   ["id", "campaign_id", "name", "status", "optimization_goal",
                    "billing_event", "bid_amount", "daily_budget", "targeting",
                    "created_time"], as_rows)
    c3 = bulk_copy(conn, "raw_meta_ads.ad_insights_daily",
                   ["id", "date_start", "date_stop", "account_id", "campaign_id",
                    "adset_id", "publisher_platform", "impressions", "clicks",
                    "spend", "reach", "actions", "account_currency", "loaded_at"],
                   gen_insights(as_rows, campaign_by_id, n_days))

    print(f"raw_meta_ads: campaigns={c1} ad_sets={c2} ad_insights_daily={c3}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
