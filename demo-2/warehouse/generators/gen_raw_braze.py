"""
gen_raw_braze — Braze customer-engagement platform.

Tables: campaigns, canvases, segments, messages_sent (fact), custom_events.
References NALA customers via external_user_id (customer code 'CUS_XXXXXXXX')
and a dirty email. Timestamp drift: ISO-Z strings, epoch s, epoch ms.
"""
from __future__ import annotations

import json
from pathlib import Path

from common import (
    connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    customer_master, rng, rand_datetime, maybe_null, dirty_email,
    ts_isoz, ts_iso, ts_epoch_s, ts_epoch_ms, det_uuid, N,
)

DDL = Path(__file__).resolve().parent.parent / "sql" / "ddl" / "raw_braze.sql"

CHANNELS = ["email", "push", "in_app_message", "sms", "webhook"]
SEND_CHANNELS = ["email", "push", "sms", "in_app_message"]
EVENT_TYPES = ["sent", "delivered", "open", "click", "bounce", "unsubscribe"]
CUSTOM_EVENT_NAMES = [
    "transfer_completed", "transfer_initiated", "kyc_passed", "kyc_failed",
    "first_transfer", "recipient_added", "app_opened", "promo_redeemed",
    "card_linked", "referral_sent",
]
CAMPAIGN_THEMES = [
    "Welcome Series", "First Transfer Bonus", "Refer a Friend", "FX Rate Alert",
    "Reactivation", "KYC Reminder", "Kenya Corridor Promo", "Nigeria Corridor Promo",
    "Bank Payout Upsell", "Holiday Send Home", "Abandoned Transfer", "USDC Wallet",
]


def _hexid(r):
    return "%024x" % r.getrandbits(96)


def gen_campaigns(n):
    rows = []
    for i in range(n):
        r = rng("braze_campaign", i)
        created = rand_datetime(r)
        first = rand_datetime(r) if r.random() < 0.85 else None
        last = rand_datetime(r) if first else None
        theme = r.choice(CAMPAIGN_THEMES)
        ch = r.choice(CHANNELS)
        status = r.choice(["active", "active", "draft", "archived", "STOPPED"])
        rows.append((
            _hexid(r),
            f"{theme} - {ch}",
            ch,
            r.choice(["promotional", "promotional", "transactional"]),
            json.dumps(r.sample(["growth", "lifecycle", "promo", "transactional",
                                 "corridor", "winback"], k=r.randint(1, 3))),
            status,
            status == "archived",
            ts_isoz(first) if first else None,
            ts_isoz(last) if last else None,
            ts_isoz(created),
            ts_iso(rand_datetime(r)),
            json.dumps({"team": r.choice(["growth", "lifecycle", "crm"])}),
        ))
    return rows


def gen_canvases(n):
    rows = []
    for i in range(n):
        r = rng("braze_canvas", i)
        created = rand_datetime(r)
        first = rand_datetime(r) if r.random() < 0.9 else None
        rows.append((
            _hexid(r),
            f"{r.choice(CAMPAIGN_THEMES)} Journey",
            json.dumps(r.sample(["onboarding", "winback", "lifecycle", "promo"],
                                k=r.randint(1, 2))),
            r.randint(2, 8),
            r.choice(["active", "active", "draft", "archived"]),
            r.random() < 0.15,
            r.random() < 0.9,
            ts_isoz(first) if first else None,
            ts_isoz(rand_datetime(r)) if first else None,
            ts_isoz(created),
            ts_isoz(rand_datetime(r)),
        ))
    return rows


def gen_segments(n):
    rows = []
    names = ["All Users", "UK Senders", "US Senders", "EU Senders",
             "Lapsed 30d", "High Value", "Kenya Corridor", "Nigeria Corridor",
             "New This Week", "KYC Incomplete", "Push Enabled", "Email Subscribed"]
    for i in range(n):
        r = rng("braze_segment", i)
        rows.append((
            _hexid(r),
            names[i % len(names)] + (f" v{i//len(names)+1}" if i >= len(names) else ""),
            maybe_null("Auto-built segment from analytics events.", 0.4, r),
            r.random() < 0.7,
            json.dumps(r.sample(["growth", "crm", "lifecycle"], k=r.randint(0, 2))),
            r.randint(500, 80_000),
            ts_isoz(rand_datetime(r)),
            ts_isoz(rand_datetime(r)),
        ))
    return rows


def gen_messages_sent(n_rows, campaign_ids, canvas_ids):
    cm = customer_master()
    for i in range(n_rows):
        r = rng("braze_msg", i)
        cust = cm[r.randrange(len(cm))]
        ch = r.choice(SEND_CHANNELS)
        from_canvas = r.random() < 0.35
        cid = None if from_canvas else r.choice(campaign_ids)
        cvid = r.choice(canvas_ids) if from_canvas else None
        sent_dt = rand_datetime(r)
        # event_type funnel: most sent/delivered, fewer open/click
        et = r.choices(EVENT_TYPES, weights=[40, 35, 15, 6, 3, 1], k=1)[0]
        email = dirty_email(cust.email, r) if ch == "email" else None
        if ch == "email":
            email = maybe_null(email, 0.05, r)  # ~5% null email
        yield (
            i,
            _hexid(r),
            cid,
            cvid,
            cust.code,
            _hexid(r),
            email,
            ch,
            r.choice(["A", "B", "control"]),
            et,
            ts_isoz(sent_dt),
            ts_epoch_s(sent_dt),
            ch == "email" and r.random() < 0.1,
            json.dumps({"variation_name": r.choice(["v1", "v2"])}) if r.random() < 0.3 else None,
        )


def gen_custom_events(n_rows):
    cm = customer_master()
    for i in range(n_rows):
        r = rng("braze_evt", i)
        cust = cm[r.randrange(len(cm))]
        evt_dt = rand_datetime(r)
        name = r.choice(CUSTOM_EVENT_NAMES)
        props = {}
        if name in ("transfer_completed", "transfer_initiated", "first_transfer"):
            props = {"transfer_id": det_uuid(("transfer", r.randrange(N["transfers"]))),
                     "amount_usd": round(r.uniform(10, 2000), 2)}
        elif name == "promo_redeemed":
            props = {"promo_code": r.choice(["SEND10", "FIRST5", "REFER20"])}
        yield (
            i,
            cust.code,
            name,
            json.dumps(props) if props else None,
            r.choice(["nala-ios", "nala-android", "nala-web"]),
            ts_epoch_ms(evt_dt),                # epoch ms (drift)
            ts_iso(evt_dt),                     # ISO no tz
        )


def main(conn):
    ensure_schema(conn, "raw_braze")
    apply_ddl_file(conn, DDL)
    truncate(conn,
             "raw_braze.messages_sent", "raw_braze.custom_events",
             "raw_braze.campaigns", "raw_braze.canvases", "raw_braze.segments")

    n_campaigns = max(8, N["customers"] // 20)
    n_canvases = max(5, N["customers"] // 60)
    n_segments = max(12, N["customers"] // 80)
    n_messages = N["customers"] * 6
    n_events = N["customers"] * 4

    camp_rows = gen_campaigns(n_campaigns)
    canvas_rows = gen_canvases(n_canvases)
    campaign_ids = [row[0] for row in camp_rows]
    canvas_ids = [row[0] for row in canvas_rows]

    c1 = bulk_copy(conn, "raw_braze.campaigns",
                   ["campaign_id", "name", "channel", "messaging_type", "tags",
                    "status", "is_archived", "first_sent", "last_sent",
                    "created_at", "updated_at", "metadata"], camp_rows)
    c2 = bulk_copy(conn, "raw_braze.canvases",
                   ["canvas_id", "name", "tags", "num_steps", "status",
                    "is_archived", "enabled", "first_entry", "last_entry",
                    "created_at", "updated_at"], canvas_rows)
    c3 = bulk_copy(conn, "raw_braze.segments",
                   ["segment_id", "name", "description",
                    "analytics_tracking_enabled", "tags", "estimated_size",
                    "created_at", "updated_at"], gen_segments(n_segments))
    c4 = bulk_copy(conn, "raw_braze.messages_sent",
                   ["id", "dispatch_id", "campaign_id", "canvas_id",
                    "external_user_id", "user_id", "email", "channel",
                    "message_variation", "event_type", "sent_at", "time",
                    "is_amp", "metadata"],
                   gen_messages_sent(n_messages, campaign_ids, canvas_ids))
    c5 = bulk_copy(conn, "raw_braze.custom_events",
                   ["id", "external_user_id", "name", "properties", "app_id",
                    "time", "received_at"], gen_custom_events(n_events))

    print(f"raw_braze: campaigns={c1} canvases={c2} segments={c3} "
          f"messages_sent={c4} custom_events={c5}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
