"""
gen_raw_intercom — Intercom in-app conversational support.

Tables: conversations (fact), conversation_parts.
Contacts map to NALA customers via contact_external_id (customer code) +
contact_email (dirty). Timestamps are UNIX epoch seconds (epoch ms for
waiting_since) — drift vs Zendesk ISO strings.
"""
from __future__ import annotations

import json
from pathlib import Path

from common import (
    connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    customer_master, rng, rand_datetime, maybe_null, dirty_email,
    ts_epoch_s, ts_epoch_ms, N,
)

DDL = Path(__file__).resolve().parent.parent / "sql" / "ddl" / "raw_intercom.sql"

import datetime as dt

STATES = ["closed", "closed", "open", "snoozed"]
SOURCE_TYPES = ["conversation", "email", "push", "chat"]
SUBJECTS = ["Question about my transfer", "FX rate help", "App not loading",
            "Refund please", "Recipient issue", "KYC help", "Fee question",
            "How to add a recipient", "Transfer pending too long"]
N_ADMINS = 18


def gen_conversations(n_convos):
    cm = customer_master()
    convo_ids = []
    for i in range(n_convos):
        r = rng("ic_convo", i)
        cust = cm[r.randrange(len(cm))]
        created = rand_datetime(r)
        state = r.choice(STATES)
        closed = state == "closed"
        updated = created + dt.timedelta(hours=r.randint(0, 120))
        assigned = r.random() < 0.85
        rated = closed and r.random() < 0.4
        cid = str(20000000 + i)
        first_resp = r.randint(60, 7200)
        stats = {
            "first_contact_reply_at": ts_epoch_s(created + dt.timedelta(seconds=first_resp)),
            "first_response_time": first_resp,
            "time_to_close": r.randint(300, 200000) if closed else None,
            "count_reopens": r.randint(0, 2),
        }
        convo_ids.append((cid, created, assigned))
        yield (
            cid,
            cust.code,
            maybe_null(dirty_email(cust.email, r), 0.07, r),    # ~7% null email PII
            state,
            not closed,
            r.random() < 0.8,
            r.choice(["priority", "not_priority", "not_priority"]),
            r.choice(SOURCE_TYPES),
            r.choice(SUBJECTS),
            f"admin_{r.randrange(N_ADMINS)}" if assigned else None,
            str(r.randrange(5)) if assigned and r.random() < 0.5 else None,
            ts_epoch_ms(updated) if state == "open" else None,   # waiting_since epoch MS
            ts_epoch_s(updated + dt.timedelta(hours=2)) if state == "snoozed" else None,
            r.random() < 0.1,
            r.randint(1, 5) if rated else None,
            json.dumps(r.sample(["billing", "transfer", "kyc", "bug"], k=r.randint(0, 2))),
            json.dumps(stats),
            ts_epoch_s(created),
            ts_epoch_s(updated),
        )
    # stash for parts gen via attribute
    gen_conversations.last_ids = convo_ids


def gen_parts(convo_ids):
    pid = 0
    user_bodies = ["<p>Hi, I need help with my transfer.</p>",
                   "<p>Any update?</p>", "<p>Thank you!</p>",
                   "<p>It's still not working.</p>"]
    admin_bodies = ["<p>Hi! Happy to help — checking now.</p>",
                    "<p>Your transfer is on the way.</p>",
                    "<p>Can you confirm the amount?</p>"]
    for cid, created, assigned in convo_ids:
        r = rng("ic_part", cid)
        n = r.randint(1, 6)
        for j in range(n):
            is_admin = j % 2 == 1 and assigned
            if j == n - 1 and r.random() < 0.3:
                ptype = r.choice(["close", "assignment", "note"])
                body = None if ptype != "note" else "<p>Internal note.</p>"
                author_type = "admin"
            else:
                ptype = "comment"
                body = r.choice(admin_bodies if is_admin else user_bodies)
                author_type = "admin" if is_admin else "user"
            ts = created + dt.timedelta(minutes=j * r.randint(2, 90))
            yield (
                str(70000000 + pid),
                cid,
                ptype,
                body,
                author_type,
                f"admin_{r.randrange(N_ADMINS)}" if author_type == "admin" else f"user_{cid}",
                maybe_null(ts_epoch_s(ts), 0.6, r),
                ts_epoch_s(ts),
            )
            pid += 1


def main(conn):
    ensure_schema(conn, "raw_intercom")
    apply_ddl_file(conn, DDL)
    truncate(conn,
             "raw_intercom.conversation_parts", "raw_intercom.conversations")

    n_convos = max(50, N["customers"] // 2)

    convo_gen = gen_conversations(n_convos)
    c1 = bulk_copy(conn, "raw_intercom.conversations",
                   ["id", "contact_external_id", "contact_email", "state",
                    "open", "read", "priority", "source_type", "source_subject",
                    "assignee_admin_id", "team_assignee_id", "waiting_since",
                    "snoozed_until", "sla_breached", "rating", "tags",
                    "statistics", "created_at", "updated_at"], convo_gen)
    c2 = bulk_copy(conn, "raw_intercom.conversation_parts",
                   ["id", "conversation_id", "part_type", "body", "author_type",
                    "author_id", "notified_at", "created_at"],
                   gen_parts(gen_conversations.last_ids))

    print(f"raw_intercom: conversations={c1} conversation_parts={c2}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
