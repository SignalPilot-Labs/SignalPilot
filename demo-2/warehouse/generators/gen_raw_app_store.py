"""
gen_raw_app_store — Apple App Store Connect + Google Play Console exports for NALA.

Loads raw_app_store: apple_downloads (daily aggregate), apple_reviews,
google_play_installs (daily aggregate), google_play_reviews. Downloads/installs
are aggregated daily metrics (no user id). Reviews carry reviewer text/nickname
(PII-ish) and a 1..5 star rating — NALA's ~4.8 average shows up here.

No cross-source customer join key (store aggregates are anonymous); the join is
temporal/geographic (report_date, country) into marketing/install funnels.
"""
from __future__ import annotations

import json
import datetime as dt
from pathlib import Path

from common import (
    N, connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    rng, rand_datetime, maybe_null, det_uuid, EPOCH_START, EPOCH_END,
    APP_VERSIONS,
)

DDL = Path(__file__).resolve().parent.parent / "sql" / "ddl" / "raw_app_store.sql"

PACKAGE = "com.nala.app"
APPLE_COUNTRIES = ["GB", "US", "IE", "FR", "DE", "ES", "KE", "NG", "TZ"]
GOOGLE_COUNTRIES = ["GB", "US", "KE", "NG", "TZ", "UG", "GH", "FR"]
APPLE_SOURCES = ["App Store Search", "App Referrer", "Web Referrer",
                 "App Store Browse", "Unavailable"]
APPLE_DEVICES = ["iPhone", "iPad"]
GOOGLE_DEVICES = ["Pixel 8", "SM-G991B", "Redmi Note 12", "SM-A546B", "Infinix X670"]

REVIEW_POOL_POS = [
    ("Fast and cheap", "Sent money to Kenya in under 2 minutes. Best rates I've found.", 5),
    ("Lifesaver", "Use it every month to send to my family in Nigeria. Never had an issue.", 5),
    ("Great app", "Transparent fees and the FX rate is much better than my bank.", 5),
    ("Love NALA", "M-PESA delivery is instant. Highly recommend.", 5),
    ("Reliable", "Been using for a year, transfers always arrive.", 4),
]
REVIEW_POOL_NEG = [
    ("Stuck transfer", "My transfer has been pending for 3 days, support not responding.", 2),
    ("KYC issues", "Couldn't verify my ID, app kept rejecting my passport photo.", 2),
    ("Annoying", "Keeps logging me out and asking to re-verify.", 3),
    ("Fees crept up", "Used to be free, now charging me on bank payouts.", 3),
    ("App crashes", "Crashes on the quote screen on my Android.", 1),
]


def _daily_dates(r, max_days):
    """Iterate dates from EPOCH_START..EPOCH_END but cap row count via max_days."""
    span = (EPOCH_END - EPOCH_START).days
    step = max(1, span // max_days)
    d = EPOCH_START
    while d < EPOCH_END:
        yield d
        d = d + dt.timedelta(days=step)


def gen_apple_downloads(max_rows):
    rid = 0
    # rows per day = a few country/source combos; cap total at max_rows
    days = max(1, max_rows // 8)
    for d in _daily_dates(rng("apple_dl_dates"), days):
        for _ in range(8):
            if rid >= max_rows:
                return
            r = rng("apple_dl", rid)
            src = r.choice(APPLE_SOURCES)
            units = r.randint(0, 400)
            yield (
                rid,
                d,
                r.choice(APP_VERSIONS),
                r.choice(APPLE_COUNTRIES),
                src,
                r.choice(APPLE_DEVICES),
                units,
                r.randint(0, units // 2 + 1),         # redownloads
                r.randint(0, units * 2 + 1),          # updates
                r.randint(units, units * 30 + 10),    # impressions
                r.randint(units, units * 8 + 5),      # product_page_views
                maybe_null(dt.datetime.combine(d, dt.time()) + dt.timedelta(hours=6), 0.1, r),
            )
            rid += 1


def gen_apple_reviews(n):
    for i in range(n):
        r = rng("apple_rev", i)
        positive = r.random() < 0.82                  # ~4.8 star skew
        title, body, rating = r.choice(REVIEW_POOL_POS if positive else REVIEW_POOL_NEG)
        rd = rand_datetime(r)
        responded = (not positive) and r.random() < 0.6
        yield (
            det_uuid(("apple_rev", i)),
            r.choice(APPLE_COUNTRIES),
            rating,
            title,
            body,
            maybe_null(f"{r.choice(['user','nala_fan','diaspora','sender'])}{r.randint(1,9999)}", 0.05, r),
            r.choice(APP_VERSIONS),
            r.random() < 0.05,
            rd,
            "Thanks for your feedback — please reach out to support@nala.com." if responded else None,
            (rd + dt.timedelta(days=r.randint(1, 5))) if responded else None,
            json.dumps({"rating": rating, "territory": "store"}),
        )


def gen_google_play_installs(max_rows):
    rid = 0
    days = max(1, max_rows // 6)
    for d in _daily_dates(rng("gp_dl_dates"), days):
        for _ in range(6):
            if rid >= max_rows:
                return
            r = rng("gp_install", rid)
            di = r.randint(0, 600)
            yield (
                rid,
                d,
                PACKAGE,
                r.choice([341, 342, 350, 400, 413, 420, 431]),  # version codes
                r.choice(GOOGLE_COUNTRIES),
                di,
                r.randint(0, di // 3 + 1),            # uninstalls
                r.randint(0, di + 1),                 # user installs
                r.randint(di, di * 50 + 10),          # active installs
                r.randint(di, di * 12 + 5),           # store listing visitors
                maybe_null(dt.datetime.combine(d, dt.time()) + dt.timedelta(hours=5), 0.1, r),
            )
            rid += 1


def gen_google_play_reviews(n):
    for i in range(n):
        r = rng("gp_rev", i)
        positive = r.random() < 0.80
        title, body, rating = r.choice(REVIEW_POOL_POS if positive else REVIEW_POOL_NEG)
        sub = rand_datetime(r)
        replied = (not positive) and r.random() < 0.5
        vcode = r.choice([341, 342, 350, 400, 413, 420, 431])
        yield (
            det_uuid(("gp_rev", i)),
            PACKAGE,
            maybe_null(f"{r.choice(['A','J','M','S'])}. {r.choice(['Mwangi','Okafor','Diallo','Smith','Hassan'])}", 0.1, r),
            rating,
            maybe_null(title, 0.3, r),                # Play reviews often have no title
            body,
            r.choice(["en", "fr", "sw", "en-GB"]),
            r.choice(GOOGLE_DEVICES),
            f"{r.randint(10,15)}",
            vcode,
            r.choice(APP_VERSIONS),
            sub,
            maybe_null(sub + dt.timedelta(days=r.randint(0, 30)), 0.7, r),
            "We're sorry to hear that — email support@nala.com and we'll help." if replied else None,
            (sub + dt.timedelta(days=r.randint(1, 4))) if replied else None,
        )


APPLE_DL_COLS = [
    "row_id", "report_date", "app_version", "country_code", "source_type",
    "device", "units", "redownloads", "updates", "impressions",
    "product_page_views", "loaded_at",
]
APPLE_REV_COLS = [
    "review_id", "territory", "rating", "title", "body", "reviewer_nickname",
    "app_version", "is_edited", "review_date", "developer_response",
    "developer_response_date", "raw_payload",
]
GP_INSTALL_COLS = [
    "row_id", "stat_date", "package_name", "app_version_code", "country",
    "daily_device_installs", "daily_device_uninstalls", "daily_user_installs",
    "active_device_installs", "store_listing_visitors", "loaded_at",
]
GP_REV_COLS = [
    "review_id", "package_name", "author_name", "star_rating", "review_title",
    "review_text", "reviewer_language", "device", "android_os_version",
    "app_version_code", "app_version_name", "submitted_at", "last_modified_at",
    "developer_reply_text", "developer_reply_at",
]


def main(conn):
    ensure_schema(conn, "raw_app_store")
    apply_ddl_file(conn, DDL)
    truncate(conn, "raw_app_store.apple_downloads", "raw_app_store.apple_reviews",
             "raw_app_store.google_play_installs", "raw_app_store.google_play_reviews")

    n_apple_dl = max(8, N["events"] // 30)
    n_gp_dl = max(6, N["events"] // 30)
    n_apple_rev = max(5, N["customers"] // 6)
    n_gp_rev = max(5, N["customers"] // 5)

    ad = bulk_copy(conn, "raw_app_store.apple_downloads", APPLE_DL_COLS,
                   gen_apple_downloads(n_apple_dl))
    ar = bulk_copy(conn, "raw_app_store.apple_reviews", APPLE_REV_COLS,
                   gen_apple_reviews(n_apple_rev))
    gi = bulk_copy(conn, "raw_app_store.google_play_installs", GP_INSTALL_COLS,
                   gen_google_play_installs(n_gp_dl))
    gr = bulk_copy(conn, "raw_app_store.google_play_reviews", GP_REV_COLS,
                   gen_google_play_reviews(n_gp_rev))
    print(f"raw_app_store: apple_downloads={ad} apple_reviews={ar} "
          f"google_play_installs={gi} google_play_reviews={gr}")


if __name__ == "__main__":
    conn = connect()
    main(conn)
    conn.close()
