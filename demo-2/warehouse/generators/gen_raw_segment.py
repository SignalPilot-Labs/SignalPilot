"""
gen_raw_segment — Segment Connections event pipeline for NALA.

Loads raw_segment: tracks (FACT, ~N["events"], streamed), identifies, pages,
screens, groups. tracks carries a jsonb `properties` payload, both anonymous_id
and user_id (user_id NULL for anonymous traffic), flattened context_* columns and
the notorious Segment multi-timestamp set with format drift.

Cross-source join keys:
  * user_id        = customer code "CUS_00000123" (joins to common.customer_master)
  * anonymous_id   = stable per-customer device key, reused by Amplitude.device_id
                     and (loosely) AppsFlyer — null user_id where anonymous.
"""
from __future__ import annotations

import json
import datetime as dt
from pathlib import Path

from common import (
    N, connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    customer_master, rng, rand_datetime, maybe_null, dirty_email, dirty_phone,
    det_uuid, ts_isoz, DEVICE_PLATFORMS, APP_VERSIONS, RECEIVE_MARKETS,
    SEND_CURRENCIES,
)

DDL = Path(__file__).resolve().parent.parent / "sql" / "ddl" / "raw_segment.sql"

# Real NALA-style product event names (track calls).
TRACK_EVENTS = [
    "App Opened", "Signup Started", "Signup Completed", "KYC Started",
    "KYC Submitted", "KYC Approved", "Recipient Added", "Quote Viewed",
    "Transfer Started", "Transfer Confirmed", "Transfer Completed",
    "Transfer Failed", "Payment Method Added", "Referral Shared",
    "Promo Applied", "Card Linked", "Notification Opened",
]
# Weights — top-of-funnel events fire far more often than completions.
EVENT_WEIGHTS = [40, 14, 8, 7, 6, 4, 6, 9, 8, 6, 5, 2, 3, 2, 2, 2, 5]

PAGE_NAMES = ["Home", "Pricing", "Send Money", "How It Works", "Login",
              "Signup", "Rafiki", "Help Center", "Country Landing"]
SCREEN_NAMES = ["Home", "SendMoney", "QuoteReview", "KYC", "Recipients",
                "AddRecipient", "TransferStatus", "Wallet", "Profile", "Referrals"]
LIB_BY_PLATFORM = {
    "ios": ("analytics-ios", "4.1.6", "iOS"),
    "android": ("analytics-android", "4.10.4", "Android"),
    "web": ("analytics.js", "4.15.3", None),
}
LOCALES = ["en-GB", "en-US", "fr-FR", "en-KE", "sw-KE", "en-NG", "fr-SN"]
TZS = ["Europe/London", "America/New_York", "Africa/Nairobi", "Africa/Lagos",
       "Europe/Paris", "Africa/Dakar"]


def _anon_id(cust) -> str:
    """Stable anonymous/device id for a customer — shared with Amplitude.device_id."""
    return det_uuid(("device", cust.cid))


def _ctx_for(r, plat):
    lib, libver, osname = LIB_BY_PLATFORM[plat]
    return lib, libver, osname


def _props_for(event, r, cust):
    """Build a realistic jsonb properties payload for an event."""
    p = {}
    if event in ("Transfer Started", "Transfer Confirmed", "Transfer Completed",
                 "Quote Viewed", "Transfer Failed"):
        rc = r.choice(list(RECEIVE_MARKETS.keys()))
        cur, _rails = RECEIVE_MARKETS[rc]
        p["send_currency"] = cust.currency
        p["receive_currency"] = cur
        p["receive_country"] = rc
        p["send_amount"] = round(r.uniform(10, 2000), 2)
        p["corridor"] = f"{cust.country}-{rc}"
        if event == "Transfer Completed":
            p["fee"] = round(r.choice([0, 0, 0.99, 1.99, 2.99]), 2)
        if event == "Transfer Failed":
            p["error_code"] = r.choice(["INSUFFICIENT_FUNDS", "KYC_REQUIRED",
                                        "PAYOUT_REJECTED", "TIMEOUT"])
    elif event in ("KYC Submitted", "KYC Started", "KYC Approved"):
        p["document_type"] = r.choice(["passport", "national_id", "drivers_license"])
        p["provider"] = r.choice(["Onfido", "Jumio"])
    elif event == "Recipient Added":
        rc = r.choice(list(RECEIVE_MARKETS.keys()))
        p["payout_method"] = r.choice(RECEIVE_MARKETS[rc][1])
        p["receive_country"] = rc
    elif event in ("Promo Applied", "Referral Shared"):
        p["promo_code"] = r.choice(["WELCOME10", "SEND5FREE", "FRIEND2026", "RAMADAN"])
    p["platform"] = cust.platform
    p["app_version"] = r.choice(APP_VERSIONS)
    return json.dumps(p)


def _pick_event(r):
    return r.choices(TRACK_EVENTS, weights=EVENT_WEIGHTS, k=1)[0]


def gen_tracks(n):
    cm = customer_master()
    ncust = len(cm)
    for i in range(n):
        r = rng("seg_track", i)
        cust = cm[r.randrange(ncust)]
        event = _pick_event(r)
        plat = cust.platform
        lib, libver, osname = _ctx_for(r, plat)
        ev_ts = rand_datetime(r, start=cust.signup_at.date())
        # Segment timestamp drift: original < sent < received < loaded
        sent = ev_ts + dt.timedelta(seconds=r.randint(0, 30))
        received = sent + dt.timedelta(milliseconds=r.randint(50, 4000))
        loaded = received + dt.timedelta(seconds=r.randint(1, 600))
        anon = _anon_id(cust)
        # ~30% of events are anonymous (no user_id) — realistic pre-identify traffic
        is_anon = r.random() < 0.30
        user_id = None if is_anon else cust.code
        # device id only on mobile; PII, sometimes null
        dev_id = None if plat == "web" else maybe_null(det_uuid(("segdev", cust.cid)), 0.1, r)
        # event_text usually mirrors event, occasionally drifts (legacy label)
        event_text = event if r.random() > 0.05 else event.lower()
        yield (
            det_uuid(("seg_msg", i)),               # id
            event,                                  # event
            event_text,                             # event_text
            anon,                                   # anonymous_id
            user_id,                                # user_id
            _props_for(event, r, cust),             # properties (jsonb)
            maybe_null(_fake_ip(r), 0.05, r),       # context_ip
            lib, libver,                            # context_library_*
            r.choice(APP_VERSIONS),                 # context_app_version
            plat,                                   # context_device_type
            dev_id,                                 # context_device_id
            osname,                                 # context_os_name
            r.choice(LOCALES),                      # context_locale
            r.choice(TZS),                          # context_timezone
            ev_ts,                                  # timestamp (tz)
            ts_isoz(ev_ts),                         # original_timestamp (ISO-Z text)
            sent,                                   # sent_at
            received,                               # received_at
            maybe_null(loaded, 0.08, r),            # loaded_at
        )


def _fake_ip(r) -> str:
    return f"{r.randint(2,223)}.{r.randint(0,255)}.{r.randint(0,255)}.{r.randint(1,254)}"


def gen_identifies(n):
    cm = customer_master()
    ncust = len(cm)
    seen = set()
    out = 0
    i = 0
    # one identify per (most) customers, roughly first time they signed in
    while out < n and i < ncust * 3:
        r = rng("seg_id", i)
        cust = cm[r.randrange(ncust)]
        i += 1
        if cust.cid in seen:
            continue
        seen.add(cust.cid)
        ts = cust.signup_at + dt.timedelta(minutes=r.randint(1, 240))
        received = ts + dt.timedelta(seconds=r.randint(1, 120))
        traits = {
            "email": cust.email, "name": f"{cust.first} {cust.last}",
            "first_name": cust.first, "country": cust.country,
            "currency": cust.currency, "plan": "consumer",
            "created_at": cust.signup_at.isoformat(),
        }
        out += 1
        yield (
            det_uuid(("seg_idmsg", cust.cid)),
            _anon_id(cust),
            cust.code,
            json.dumps(traits),
            maybe_null(dirty_email(cust.email, r), 0.06, r),
            maybe_null(dirty_phone(cust.phone, r), 0.15, r),
            maybe_null(_fake_ip(r), 0.05, r),
            r.choice(APP_VERSIONS),
            cust.platform,
            ts,
            received,
            maybe_null(received + dt.timedelta(seconds=r.randint(1, 300)), 0.08, r),
        )


def gen_pages(n):
    cm = customer_master()
    ncust = len(cm)
    for i in range(n):
        r = rng("seg_page", i)
        cust = cm[r.randrange(ncust)]
        name = r.choice(PAGE_NAMES)
        ts = rand_datetime(r)
        received = ts + dt.timedelta(seconds=r.randint(1, 60))
        path = "/" + name.lower().replace(" ", "-")
        url = f"https://www.nala.com{path}"
        props = {"url": url, "path": path,
                 "referrer": r.choice(["https://google.com", "https://nala.com", ""]),
                 "title": f"NALA — {name}"}
        # web pages: user_id usually null
        user_id = None if r.random() < 0.7 else cust.code
        yield (
            det_uuid(("seg_pagemsg", i)),
            _anon_id(cust),
            user_id,
            name,
            maybe_null("marketing", 0.6, r),
            json.dumps(props),
            maybe_null(_fake_ip(r), 0.05, r),
            url,
            maybe_null(props["referrer"] or None, 0.0, r),
            "Mozilla/5.0",
            ts,
            received,
        )


def gen_screens(n):
    cm = customer_master()
    ncust = len(cm)
    for i in range(n):
        r = rng("seg_screen", i)
        cust = cm[r.randrange(ncust)]
        if cust.platform == "web":
            cust = cm[(cust.cid + 1) % ncust]  # screens are mobile-only
        plat = "ios" if cust.platform == "web" else cust.platform
        _lib, _v, osname = LIB_BY_PLATFORM[plat]
        ts = rand_datetime(r, start=cust.signup_at.date())
        received = ts + dt.timedelta(seconds=r.randint(1, 90))
        name = r.choice(SCREEN_NAMES)
        props = {"name": name, "tab": r.choice(["send", "wallet", "activity"])}
        yield (
            det_uuid(("seg_screenmsg", i)),
            _anon_id(cust),
            None if r.random() < 0.25 else cust.code,
            name,
            json.dumps(props),
            r.choice(APP_VERSIONS),
            plat,
            maybe_null(det_uuid(("segdev", cust.cid)), 0.1, r),
            osname,
            ts,
            received,
        )


def gen_groups(n):
    """Sparse group calls — associate a user with a merchant/org (Rafiki side)."""
    cm = customer_master()
    ncust = len(cm)
    for i in range(n):
        r = rng("seg_group", i)
        cust = cm[r.randrange(ncust)]
        gid = f"org_{r.randint(1, max(2, ncust // 50))}"
        ts = rand_datetime(r, start=cust.signup_at.date())
        received = ts + dt.timedelta(seconds=r.randint(1, 60))
        traits = {"name": f"Merchant {gid}", "plan": r.choice(["growth", "scale"]),
                  "industry": r.choice(["marketplace", "payroll", "remittance"])}
        yield (
            det_uuid(("seg_groupmsg", i)),
            maybe_null(_anon_id(cust), 0.2, r),
            cust.code,
            gid,
            json.dumps(traits),
            ts,
            received,
        )


TRACKS_COLS = [
    "id", "event", "event_text", "anonymous_id", "user_id", "properties",
    "context_ip", "context_library_name", "context_library_version",
    "context_app_version", "context_device_type", "context_device_id",
    "context_os_name", "context_locale", "context_timezone",
    "timestamp", "original_timestamp", "sent_at", "received_at", "loaded_at",
]
IDENT_COLS = [
    "id", "anonymous_id", "user_id", "traits", "email", "phone", "context_ip",
    "context_app_version", "context_device_type", "timestamp", "received_at",
    "loaded_at",
]
PAGES_COLS = [
    "id", "anonymous_id", "user_id", "name", "category", "properties",
    "context_ip", "context_page_url", "context_page_referrer",
    "context_user_agent", "timestamp", "received_at",
]
SCREENS_COLS = [
    "id", "anonymous_id", "user_id", "name", "properties", "context_app_version",
    "context_device_type", "context_device_id", "context_os_name",
    "timestamp", "received_at",
]
GROUPS_COLS = [
    "id", "anonymous_id", "user_id", "group_id", "traits", "timestamp",
    "received_at",
]


def main(conn):
    ensure_schema(conn, "raw_segment")
    apply_ddl_file(conn, DDL)
    truncate(conn, "raw_segment.tracks", "raw_segment.identifies",
             "raw_segment.pages", "raw_segment.screens", "raw_segment.groups")

    n_tracks = N["events"]
    n_pages = max(1, n_tracks // 4)
    n_screens = max(1, n_tracks // 3)
    n_ident = max(1, min(N["customers"], n_tracks // 6))
    n_groups = max(5, N["customers"] // 50)

    t = bulk_copy(conn, "raw_segment.tracks", TRACKS_COLS, gen_tracks(n_tracks))
    i = bulk_copy(conn, "raw_segment.identifies", IDENT_COLS, gen_identifies(n_ident))
    p = bulk_copy(conn, "raw_segment.pages", PAGES_COLS, gen_pages(n_pages))
    s = bulk_copy(conn, "raw_segment.screens", SCREENS_COLS, gen_screens(n_screens))
    g = bulk_copy(conn, "raw_segment.groups", GROUPS_COLS, gen_groups(n_groups))
    print(f"raw_segment: tracks={t} identifies={i} pages={p} screens={s} groups={g}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
