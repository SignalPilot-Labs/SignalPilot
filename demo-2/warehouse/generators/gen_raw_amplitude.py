"""
gen_raw_amplitude — Amplitude product-analytics export for NALA.

Loads raw_amplitude: events (FACT, streamed; event_time stored as EPOCH MS),
user_properties (one row per amplitude_id), cohorts (lookup-ish).

NALA dual-instruments through Segment + Amplitude, so events overlap raw_segment.
Cross-source join keys:
  * user_id    = customer code "CUS_..." (null for anonymous)
  * device_id  = det_uuid(("device", cid)) == raw_segment anonymous_id
  * amplitude_id = stable per-customer integer surrogate
"""
from __future__ import annotations

import json
import datetime as dt
from pathlib import Path

from common import (
    N, connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    customer_master, rng, rand_datetime, maybe_null, det_uuid,
    ts_epoch_ms, APP_VERSIONS, RECEIVE_MARKETS,
)

DDL = Path(__file__).resolve().parent.parent / "sql" / "ddl" / "raw_amplitude.sql"

EVENT_TYPES = [
    "Session Start", "App Opened", "Signup Completed", "KYC Submitted",
    "Recipient Added", "Quote Viewed", "Transfer Started", "Transfer Completed",
    "Transfer Failed", "Notification Opened", "Promo Applied",
]
EVENT_WEIGHTS = [22, 30, 5, 5, 6, 9, 8, 6, 2, 4, 3]
PLATFORM_MAP = {"ios": "iOS", "android": "Android", "web": "Web"}
COUNTRIES_MM = {
    "GB": ("United Kingdom", "London"), "US": ("United States", "New York"),
    "IE": ("Ireland", "Dublin"), "FR": ("France", "Paris"),
    "DE": ("Germany", "Berlin"), "ES": ("Spain", "Madrid"),
}


def _amp_id(cid: int) -> int:
    return 100_000_000 + cid


def _device_id(cid: int) -> str:
    return det_uuid(("device", cid))


def _fake_ip(r) -> str:
    return f"{r.randint(2,223)}.{r.randint(0,255)}.{r.randint(0,255)}.{r.randint(1,254)}"


def _event_props(event, r, cust):
    p = {}
    if event in ("Transfer Started", "Transfer Completed", "Quote Viewed",
                 "Transfer Failed"):
        rc = r.choice(list(RECEIVE_MARKETS.keys()))
        p["receive_country"] = rc
        p["receive_currency"] = RECEIVE_MARKETS[rc][0]
        p["send_amount"] = round(r.uniform(10, 2000), 2)
        if event == "Transfer Completed":
            p["revenue"] = round(r.uniform(0, 12), 2)
    elif event == "KYC Submitted":
        p["provider"] = r.choice(["Onfido", "Jumio"])
    return json.dumps(p)


def _user_props(cust, r, paying):
    return json.dumps({
        "plan": "consumer", "country": cust.country, "currency": cust.currency,
        "kyc_status": r.choice(["approved", "pending", "approved", "approved"]),
        "lifetime_transfers": r.randint(0, 60), "paying": paying,
    })


def gen_events(n):
    cm = customer_master()
    ncust = len(cm)
    for i in range(n):
        r = rng("amp_evt", i)
        cust = cm[r.randrange(ncust)]
        event = r.choices(EVENT_TYPES, weights=EVENT_WEIGHTS, k=1)[0]
        ts = rand_datetime(r, start=cust.signup_at.date())
        client = ts + dt.timedelta(milliseconds=r.randint(0, 800))
        upload = ts + dt.timedelta(seconds=r.randint(1, 300))
        plat = cust.platform
        is_anon = r.random() < 0.25
        country, city = COUNTRIES_MM.get(cust.country, (cust.country, None))
        session = ts_epoch_ms(ts - dt.timedelta(minutes=r.randint(0, 25)))
        idfa = None
        adid = None
        if plat == "ios":
            idfa = maybe_null(det_uuid(("idfa", cust.cid)).upper(), 0.4, r)  # ATT denial
        elif plat == "android":
            adid = maybe_null(det_uuid(("gaid", cust.cid)), 0.15, r)
        yield (
            det_uuid(("amp_uuid", i)),
            r.randint(1, 5000),                       # event_id (per-user monotonic-ish)
            _amp_id(cust.cid),
            None if is_anon else cust.code,
            maybe_null(_device_id(cust.cid), 0.05, r),
            session,
            event,
            ts_epoch_ms(ts),                          # event_time EPOCH MS
            ts_epoch_ms(client),
            ts_epoch_ms(upload),
            _event_props(event, r, cust),
            _user_props(cust, r, r.random() < 0.4),
            r.choice(APP_VERSIONS),
            PLATFORM_MAP[plat],
            "iOS" if plat == "ios" else ("Android" if plat == "android" else None),
            country, city, city,                      # country, region(~city), city
            maybe_null(_fake_ip(r), 0.06, r),
            idfa, adid,
            event == "Transfer Completed",            # is_attribution_event
        )


def gen_user_properties(n):
    cm = customer_master()
    ncust = min(n, len(cm))
    for cid in range(ncust):
        r = rng("amp_up", cid)
        cust = cm[cid]
        paying = r.random() < 0.45
        first = cust.signup_at
        last = rand_datetime(r, start=cust.signup_at.date())
        if last < first:
            last = first + dt.timedelta(days=1)
        country, city = COUNTRIES_MM.get(cust.country, (cust.country, None))
        yield (
            _amp_id(cid),
            maybe_null(cust.code, 0.08, r),           # some anon-only users
            _device_id(cid),
            first, last,
            _user_props(cust, r, paying),
            country, city,
            PLATFORM_MAP[cust.platform],
            paying,
            maybe_null(r.choice(["activated", "power_user", "dormant"]), 0.5, r),
        )


COHORT_DEFS = [
    ("Activated Senders", "Completed >=1 transfer in first 7 days", "dynamic"),
    ("Churn Risk - KE", "No activity 30d, KE corridor", "dynamic"),
    ("High Value", "Lifetime send > $5k", "dynamic"),
    ("KYC Stuck", "Submitted KYC, not approved 48h", "dynamic"),
    ("Referral Champions", ">=3 successful referrals", "dynamic"),
    ("Web Signups No App", "Signed up web, never opened app", "static"),
    ("USDC Wallet Users", "Holds USDC balance", "dynamic"),
    ("Lapsed Q1", "Active 2025 Q1, inactive since", "static"),
]


def gen_cohorts(n):
    for i in range(min(n, len(COHORT_DEFS))):
        r = rng("amp_cohort", i)
        name, desc, ctype = COHORT_DEFS[i]
        created = rand_datetime(r)
        yield (
            det_uuid(("amp_cohort", i))[:12],
            name, desc, ctype,
            r.randint(50, 40000),
            maybe_null(f"analyst{r.randint(1,5)}@nala.com", 0.2, r),
            created,
            created + dt.timedelta(hours=r.randint(1, 72)),
            r.random() < 0.15,
        )


EVENTS_COLS = [
    "uuid", "event_id", "amplitude_id", "user_id", "device_id", "session_id",
    "event_type", "event_time", "client_event_time", "server_upload_time",
    "event_properties", "user_properties", "app_version", "platform", "os_name",
    "country", "region", "city", "ip_address", "idfa", "adid",
    "is_attribution_event",
]
USERPROPS_COLS = [
    "amplitude_id", "user_id", "device_id", "first_seen_at", "last_seen_at",
    "properties", "country", "city", "platform", "paying", "cohort",
]
COHORTS_COLS = [
    "cohort_id", "name", "description", "cohort_type", "size", "owner",
    "created_at", "last_computed_at", "archived",
]


def main(conn):
    ensure_schema(conn, "raw_amplitude")
    apply_ddl_file(conn, DDL)
    truncate(conn, "raw_amplitude.events", "raw_amplitude.user_properties",
             "raw_amplitude.cohorts")

    n_events = max(1, N["events"] * 7 // 10)   # slightly fewer than Segment tracks
    e = bulk_copy(conn, "raw_amplitude.events", EVENTS_COLS, gen_events(n_events))
    u = bulk_copy(conn, "raw_amplitude.user_properties", USERPROPS_COLS,
                  gen_user_properties(N["customers"]))
    c = bulk_copy(conn, "raw_amplitude.cohorts", COHORTS_COLS, gen_cohorts(len(COHORT_DEFS)))
    print(f"raw_amplitude: events={e} user_properties={u} cohorts={c}")


if __name__ == "__main__":
    conn = connect()
    main(conn)
    conn.close()
