"""
gen_raw_appsflyer — AppsFlyer mobile-attribution (MMP) export for NALA.

Loads raw_appsflyer: media_sources (lookup), installs, in_app_events,
attributions. Vendor format drift: install_time / event_time are naive UTC ISO
*strings* (text), while attributions.touch_time is a real timestamptz.

Cross-source join keys:
  * customer_user_id = customer code "CUS_..." (null pre-login)
  * appsflyer_id     = det_uuid(("af", cid)) stable per-customer device key
"""
from __future__ import annotations

import json
import datetime as dt
from pathlib import Path

from common import (
    N, connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    customer_master, rng, rand_datetime, maybe_null, det_uuid, ts_iso,
    APP_VERSIONS,
)

DDL = Path(__file__).resolve().parent.parent / "sql" / "ddl" / "raw_appsflyer.sql"

MEDIA_SOURCES = [
    (1, "Facebook Ads", "Facebook", "paid_social"),
    (2, "googleadwords_int", "Google Ads", "paid_search"),
    (3, "tiktokglobal_int", "TikTok", "paid_social"),
    (4, "Apple Search Ads", "Apple Search Ads", "paid_search"),
    (5, "snapchat_int", "Snapchat", "paid_social"),
    (6, "Organic", "Organic", "organic"),
    (7, "af_referral", "Referral", "referral"),
]
PAID_SOURCES = [m[1] for m in MEDIA_SOURCES if m[3] != "organic"]
CAMPAIGNS = ["uk_diaspora_prospecting", "ke_corridor_retarget",
             "ng_acq_q2", "brand_search", "us_send_money", "tiktok_creators_2026",
             "ramadan_send_home"]
IOS_DEVICES = ["iPhone15,3", "iPhone14,5", "iPhone13,2", "iPhone16,1"]
ANDROID_DEVICES = ["Pixel 8", "SM-G991B", "SM-A546B", "Redmi Note 12"]
IN_APP = [
    ("af_complete_registration", 0.0),
    ("af_first_transfer", None),
    ("af_purchase", None),
    ("af_add_payment_info", 0.0),
    ("af_login", 0.0),
]
COUNTRIES = ["GB", "US", "IE", "FR", "DE", "ES", "KE", "NG"]
LANGS = ["en-GB", "en-US", "fr-FR", "en", "sw"]


def _af_id(cid: int) -> str:
    # AppsFlyer device id format: <epoch>-<random>; we make it stable per customer
    return f"1{cid:010d}-{det_uuid(('af', cid))[:13]}"


def _fake_ip(r) -> str:
    return f"{r.randint(2,223)}.{r.randint(0,255)}.{r.randint(0,255)}.{r.randint(1,254)}"


def gen_media_sources():
    for mid, ms, pretty, ch in MEDIA_SOURCES:
        yield (mid, ms, pretty, ch, True)


def gen_installs(n):
    # One install per customer (appsflyer_id is the PK and is keyed off cid).
    cm = customer_master()
    n = min(n, len(cm))
    for cid in range(n):
        r = rng("af_install", cid)
        cust = cm[cid]
        plat = "ios" if cust.platform == "ios" else "android"  # web users -> android
        if cust.platform == "web":
            plat = r.choice(["ios", "android"])
        is_organic = r.random() < 0.45
        ms = "Organic" if is_organic else r.choice(PAID_SOURCES)
        install_at = cust.signup_at - dt.timedelta(minutes=r.randint(0, 4320))
        touch_at = None if is_organic else install_at - dt.timedelta(hours=r.randint(0, 72))
        dev = r.choice(IOS_DEVICES if plat == "ios" else ANDROID_DEVICES)
        idfa = idfv = adid = None
        if plat == "ios":
            idfv = det_uuid(("idfv", cust.cid)).upper()
            idfa = maybe_null(det_uuid(("idfa", cust.cid)).upper(), 0.4, r)  # ATT denial
        else:
            adid = maybe_null(det_uuid(("gaid", cust.cid)), 0.12, r)
        campaign = None if is_organic else r.choice(CAMPAIGNS)
        yield (
            _af_id(cust.cid),
            maybe_null(cust.code, 0.18, r),            # null pre-login
            ts_iso(install_at),                        # install_time (naive string)
            ts_iso(touch_at) if touch_at else None,    # attributed_touch_time
            None if is_organic else r.choice(["click", "impression"]),
            ms,
            campaign,
            None if is_organic else f"cmp_{r.randint(10000,99999)}",
            None if is_organic else f"adset_{r.randint(100,999)}",
            None if is_organic else f"ad_{r.randint(100,999)}",
            None if is_organic else r.choice(["Social", "Search", "Video"]),
            plat,
            "id1565123456" if plat == "ios" else "com.nala.app",
            r.choice(APP_VERSIONS),
            dev,
            f"{r.randint(14,18)}.{r.randint(0,6)}",
            r.choice(COUNTRIES),
            r.choice(LANGS),
            idfa, idfv, adid,
            maybe_null(_fake_ip(r), 0.05, r),
            is_organic,
            r.random() < 0.08,                         # is_retargeting
            True,
        )


def gen_in_app_events(n):
    cm = customer_master()
    ncust = len(cm)
    for i in range(n):
        r = rng("af_iae", i)
        cust = cm[r.randrange(ncust)]
        plat = "ios" if cust.platform == "ios" else "android"
        if cust.platform == "web":
            plat = r.choice(["ios", "android"])
        name, fixed_rev = IN_APP[r.randrange(len(IN_APP))]
        et = rand_datetime(r, start=cust.signup_at.date())
        is_organic = r.random() < 0.45
        ms = "Organic" if is_organic else r.choice(PAID_SOURCES)
        rev = None
        ev_val = {}
        if name in ("af_first_transfer", "af_purchase"):
            rev = round(r.uniform(0.99, 9.99), 2)
            ev_val = {"af_revenue": rev, "af_currency": cust.currency,
                      "af_content_type": "transfer"}
        elif fixed_rev is not None:
            ev_val = {"af_registration_method": "email"}
        yield (
            det_uuid(("af_iae", i)),
            _af_id(cust.cid),
            maybe_null(cust.code, 0.3, r),
            name,
            ts_iso(et),                                # event_time (naive string)
            json.dumps(ev_val),
            rev,
            cust.currency if rev is not None else None,
            ms,
            None if is_organic else r.choice(CAMPAIGNS),
            plat,
            r.choice(APP_VERSIONS),
            r.choice(COUNTRIES),
            maybe_null(_fake_ip(r), 0.05, r),
        )


def gen_attributions(n):
    cm = customer_master()
    ncust = len(cm)
    for i in range(n):
        r = rng("af_attr", i)
        cust = cm[r.randrange(ncust)]
        is_organic = r.random() < 0.4
        ms = "Organic" if is_organic else r.choice(PAID_SOURCES)
        attr_at = rand_datetime(r, start=cust.signup_at.date())
        touch = attr_at - dt.timedelta(hours=r.randint(0, 48))
        yield (
            det_uuid(("af_attr", i)),
            _af_id(cust.cid),
            maybe_null(cust.code, 0.2, r),
            ms,
            None if is_organic else r.choice(CAMPAIGNS),
            None if is_organic else f"cmp_{r.randint(10000,99999)}",
            r.choice(["install", "reattribution", "reengagement"]),
            None if is_organic else r.choice(["click", "impression"]),
            touch,                                     # touch_time (tz timestamp!)
            attr_at,
            maybe_null(r.choice(PAID_SOURCES), 0.7, r),  # contributor_1 (sparse)
            is_organic,
        )


MEDIA_COLS = ["media_source_id", "media_source", "pretty_name", "channel_type",
              "is_active"]
INSTALLS_COLS = [
    "appsflyer_id", "customer_user_id", "install_time", "attributed_touch_time",
    "attributed_touch_type", "media_source", "campaign", "campaign_id",
    "af_adset", "af_ad", "af_channel", "platform", "app_id", "app_version",
    "device_model", "os_version", "country_code", "language", "idfa", "idfv",
    "advertising_id", "ip", "is_organic", "is_retargeting", "is_primary_attribution",
]
IAE_COLS = [
    "event_uuid", "appsflyer_id", "customer_user_id", "event_name", "event_time",
    "event_value", "event_revenue", "event_revenue_currency", "media_source",
    "campaign", "platform", "app_version", "country_code", "ip",
]
ATTR_COLS = [
    "attribution_id", "appsflyer_id", "customer_user_id", "media_source",
    "campaign", "campaign_id", "attribution_type", "touch_type", "touch_time",
    "attributed_at", "contributor_1_media_source", "is_organic",
]


def main(conn):
    ensure_schema(conn, "raw_appsflyer")
    apply_ddl_file(conn, DDL)
    truncate(conn, "raw_appsflyer.in_app_events", "raw_appsflyer.attributions",
             "raw_appsflyer.installs", "raw_appsflyer.media_sources")

    n_installs = max(1, N["customers"])
    n_iae = max(1, N["events"] // 6)
    n_attr = max(1, N["customers"] * 2)

    m = bulk_copy(conn, "raw_appsflyer.media_sources", MEDIA_COLS, gen_media_sources())
    ins = bulk_copy(conn, "raw_appsflyer.installs", INSTALLS_COLS, gen_installs(n_installs))
    iae = bulk_copy(conn, "raw_appsflyer.in_app_events", IAE_COLS, gen_in_app_events(n_iae))
    at = bulk_copy(conn, "raw_appsflyer.attributions", ATTR_COLS, gen_attributions(n_attr))
    print(f"raw_appsflyer: media_sources={m} installs={ins} in_app_events={iae} attributions={at}")


if __name__ == "__main__":
    conn = connect()
    main(conn)
    conn.close()
