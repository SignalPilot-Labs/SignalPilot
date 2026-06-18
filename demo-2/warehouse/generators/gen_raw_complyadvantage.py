"""
Generator: raw_complyadvantage — ComplyAdvantage AML / sanctions / PEP screening.

Most NALA customers get one onboarding search. A subset are placed under ongoing
monitoring; monitors occasionally raise alerts. Search hits are sparse (most
searches are clean) but a small tail of customers match watchlist entities.
"""
from __future__ import annotations

import datetime as dt
import json

from common import (
    connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    customer_master, rng, rand_datetime, dirty_email, maybe_null,
    ts_iso, ts_epoch_ms, N,
)

SCHEMA = "raw_complyadvantage"
DDL = "sql/ddl/raw_complyadvantage.sql"

WATCHLISTS = ["OFAC SDN", "OFAC Non-SDN", "UN Consolidated", "UK HMT",
              "EU Consolidated", "World-Check", "DFAT Australia"]
HIT_TYPES = ["sanction", "pep-class-1", "pep-class-2", "adverse-media-financial-crime",
             "adverse-media-fraud", "warning"]
MATCH_TYPES = ["name_exact", "name_fuzzy", "aka_exact", "aka_fuzzy", "phonetic_name"]


def main(conn):
    ensure_schema(conn, SCHEMA)
    apply_ddl_file(conn, DDL)
    truncate(conn,
             f"{SCHEMA}.searches", f"{SCHEMA}.search_hits",
             f"{SCHEMA}.monitors", f"{SCHEMA}.monitor_alerts")

    customers = customer_master()

    searches, hits, monitors, alerts = [], [], [], []
    search_seq = 700_000_000          # ComplyAdvantage-style large numeric ids
    monitor_seq = 50_000_000
    alert_seq = 90_000_000
    hit_seq = 0

    for cust in customers:
        r = rng("comply", cust.cid)
        # ~95% of customers were screened (rest are pre-vendor legacy).
        if r.random() < 0.05:
            continue

        search_id = search_seq
        search_seq += 1
        created = rand_datetime(r, start=dt.date(2019, 6, 1))

        # how many hits this search returned
        roll = r.random()
        if roll < 0.90:
            n_hits, match_status, risk = 0, "no_match", "low"
        elif roll < 0.975:
            n_hits, match_status, risk = r.randint(1, 3), "false_positive", "medium"
        else:
            n_hits, match_status, risk = r.randint(1, 5), \
                r.choice(["potential_match", "true_positive"]), \
                r.choice(["high", "medium"])

        ref = maybe_null(cust.code, 0.06, r)     # client ref usually = customer code
        searches.append((
            search_id, ref,
            dirty_email(maybe_null(cust.email, 0.4, r), r),
            f"{cust.first} {cust.last}",
            ref,                                    # client_ref legacy duplicate
            f"svc_screening_{r.randint(1,4)}",
            maybe_null(f"analyst_{r.randint(1,12)}", 0.7, r),
            json.dumps({"types": r.sample(["sanction", "pep", "adverse-media", "warning"],
                                          k=r.randint(1, 4)),
                        "birth_year": int(cust.dob[:4]),
                        "remove_deceased": True}),
            match_status, risk, n_hits, n_hits,
            f"https://app.complyadvantage.com/public/search/{search_id}/{r.getrandbits(48):x}",
            None,                                   # is_monitored filled below
            ts_iso(created),
            ts_iso(created),
            json.dumps([]),
        ))

        for _ in range(n_hits):
            hit_seq += 1
            hits.append((
                hit_seq,
                search_id,
                f"{r.getrandbits(48):x}",
                f"{cust.last.upper()}, {cust.first}",      # matched entity name style
                "person",
                json.dumps(r.sample(MATCH_TYPES, k=r.randint(1, 2))),
                json.dumps([f"{cust.first} {cust.last}",
                            f"{cust.first[0]}. {cust.last}"]),
                json.dumps(r.sample(WATCHLISTS, k=r.randint(1, 3))),
                json.dumps(r.sample(HIT_TYPES, k=r.randint(1, 2))),
                maybe_null(round(r.uniform(50, 100), 2), 0.15, r),
                r.random() < 0.2,
                r.choice(["potential_match", "false_positive", "true_positive"]),
                json.dumps({"dob": [cust.dob[:4]],
                            "nationality": [cust.country],
                            "associates": []}),
                ts_iso(created),
            ))

        # monitoring: high/medium risk almost always monitored, others ~25%.
        monitored = (risk in ("high", "medium")) or (r.random() < 0.25)
        # patch is_monitored on the search row we just appended
        searches[-1] = searches[-1][:13] + (monitored,) + searches[-1][14:]

        if monitored:
            monitor_id = monitor_seq
            monitor_seq += 1
            freq = r.choice(["daily", "weekly", "monthly"])
            if created.year <= 2020 and r.random() < 0.3:
                freq = freq.upper()                 # legacy uppercase
            last_run = rand_datetime(r, start=created.date())
            monitors.append((
                monitor_id, search_id, ref,
                r.random() < 0.9,
                freq,
                maybe_null(ts_iso(last_run), 0.1, r),
                ts_iso(created),
                ts_iso(last_run),
            ))

            # alerts: monitors of matched customers raise alerts.
            n_alerts = (r.randint(1, 3) if n_hits else 0) + (1 if r.random() < 0.05 else 0)
            for _ in range(n_alerts):
                a_created = rand_datetime(r, start=created.date())
                status = r.choices(["open", "acknowledged", "closed", "escalated"],
                                   weights=[25, 25, 40, 10])[0]
                if a_created.year <= 2020 and status == "open" and r.random() < 0.4:
                    status = "OPEN"                  # legacy uppercase
                resolved = (ts_epoch_ms(rand_datetime(r, start=a_created.date()))
                            if status in ("closed", "acknowledged") else None)
                alerts.append((
                    alert_seq, monitor_id, search_id,
                    r.choice(["new_match", "match_removed", "risk_changed", "data_updated"]),
                    r.choice(["low", "medium", "high"]),
                    r.choice(["medium", "high"]),
                    status,
                    maybe_null(f"analyst_{r.randint(1,12)}", 0.3, r),
                    resolved,
                    json.dumps({"summary": "monitored search changed",
                                "search_id": search_id}),
                    ts_iso(a_created),
                ))
                alert_seq += 1

    bulk_copy(conn, f"{SCHEMA}.searches",
              ["id", "ref", "nala_customer_email", "search_term", "client_ref",
               "searcher_id", "assignee_id", "filters", "match_status", "risk_level",
               "total_hits", "total_matches", "share_url", "is_monitored",
               "created_at", "updated_at", "tags"], searches)
    bulk_copy(conn, f"{SCHEMA}.search_hits",
              ["id", "search_id", "doc_id", "entity_name", "entity_type",
               "match_types", "aka", "sources", "types", "match_score",
               "is_whitelisted", "match_status", "fields", "created_at"], hits)
    bulk_copy(conn, f"{SCHEMA}.monitors",
              ["id", "search_id", "ref", "is_active", "monitor_frequency",
               "last_run_at", "created_at", "updated_at"], monitors)
    bulk_copy(conn, f"{SCHEMA}.monitor_alerts",
              ["id", "monitor_id", "search_id", "alert_type", "previous_risk_level",
               "new_risk_level", "status", "assigned_to", "resolved_at_epoch_ms",
               "payload", "created_at"], alerts)

    print(f"[{SCHEMA}] searches={len(searches)} hits={len(hits)} "
          f"monitors={len(monitors)} alerts={len(alerts)}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
