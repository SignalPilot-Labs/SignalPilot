"""
gen_raw_zendesk — Zendesk Support tickets.

Tables: users (PII), tickets (fact), ticket_comments, satisfaction_ratings.
End-user Zendesk users map to NALA customers via email (dirty) + external_id
(customer code). Some tickets reference a transfer_id (det_uuid).
"""
from __future__ import annotations

import json
from pathlib import Path

from common import (
    connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    customer_master, rng, faker_for, rand_datetime, maybe_null,
    dirty_email, dirty_phone, det_uuid, EPOCH_END, N,
)

DDL = Path(__file__).resolve().parent.parent / "sql" / "ddl" / "raw_zendesk.sql"

import datetime as dt

STATUSES = ["new", "open", "pending", "hold", "solved", "closed"]
PRIORITIES = ["low", "normal", "high", "urgent"]
TYPES = ["question", "incident", "problem", "task"]
CHANNELS = ["email", "chat", "api", "web", "mobile"]
GROUPS = ["Tier 1 Support", "Tier 2 Support", "Payments Ops", "Compliance",
          "Fraud", "VIP"]
SUBJECTS = [
    "Transfer not received", "How long does a transfer take?",
    "Wrong recipient details", "Refund request", "KYC document rejected",
    "Cannot log in", "FX rate question", "Fee dispute",
    "Update phone number", "Transfer stuck pending", "Card declined",
    "Account locked", "Recipient bank rejected payment",
]

# Number of agents (Zendesk users with role=agent)
N_AGENTS = 25


def gen_users(n_endusers):
    """First N_AGENTS rows are agents, then end-users mapped to customers."""
    cm = customer_master()
    rows = []
    uid = 500000
    # agents
    for a in range(N_AGENTS):
        r = rng("zd_agent", a)
        f = faker_for(("zd_agent", a))
        name = f.name()
        email = f"{name.split()[0].lower()}.support{a}@nala.com"
        rows.append((
            uid, name, email, None, "agent", None, None,
            r.choice(["en-GB", "en-US", "sw"]), "Europe/London",
            True, False, json.dumps(["agent"]),
            rand_datetime(r), rand_datetime(r),
        ))
        uid += 1
    agent_ids = [500000 + a for a in range(N_AGENTS)]
    # end-users (sampled from customer_master)
    enduser_ids = []
    seen = set()
    n = min(n_endusers, len(cm))
    for k in range(n):
        r = rng("zd_user", k)
        idx = r.randrange(len(cm))
        while idx in seen and len(seen) < len(cm):
            idx = r.randrange(len(cm))
        seen.add(idx)
        cust = cm[idx]
        rows.append((
            uid,
            f"{cust.first} {cust.last}",
            maybe_null(dirty_email(cust.email, r), 0.06, r),     # ~6% null email PII
            maybe_null(dirty_phone(cust.phone, r), 0.5, r),
            "end-user",
            cust.code,
            None,
            r.choice(["en-GB", "en-US", "fr", "sw"]),
            "Europe/London",
            r.random() < 0.8,
            False,
            json.dumps([]),
            rand_datetime(r),
            rand_datetime(r),
        ))
        enduser_ids.append((uid, idx))
        uid += 1
    return rows, agent_ids, enduser_ids


def gen_tickets(n_tickets, agent_ids, enduser_ids):
    cm = customer_master()
    rows = []
    for i in range(n_tickets):
        r = rng("zd_ticket", i)
        eu_id, cust_idx = enduser_ids[r.randrange(len(enduser_ids))]
        cust = cm[cust_idx]
        created = rand_datetime(r)
        status = r.choices(STATUSES, weights=[8, 15, 12, 5, 30, 30], k=1)[0]
        solved = status in ("solved", "closed")
        solved_dt = created + dt.timedelta(hours=r.randint(1, 240)) if solved else None
        if solved_dt and solved_dt > dt.datetime(EPOCH_END.year, EPOCH_END.month, EPOCH_END.day):
            solved_dt = None
            status = "open"
            solved = False
        has_agent = status != "new" and r.random() < 0.9
        rows.append((
            900000 + i,
            eu_id,
            r.choice(agent_ids) if has_agent else None,
            r.choice(SUBJECTS),
            status,
            maybe_null(r.choice(PRIORITIES), 0.3, r),
            maybe_null(r.choice(TYPES), 0.4, r),
            r.choice(CHANNELS),
            json.dumps(r.sample(["billing", "transfer", "kyc", "login", "vip",
                                "corridor-ke", "corridor-ng"], k=r.randint(0, 3))),
            r.choice(GROUPS),
            maybe_null(dirty_email(cust.email, r), 0.06, r),     # denorm PII snapshot
            det_uuid(("transfer", r.randrange(N["transfers"]))) if r.random() < 0.4 else None,
            r.choice(["offered", "good", "bad", "unoffered", "unoffered"]) if solved else "unoffered",
            r.random() < 0.95,
            created,
            created + dt.timedelta(hours=r.randint(0, 250)),
            solved_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z") if solved_dt else None,
            json.dumps({"via": r.choice(CHANNELS)}) if r.random() < 0.3 else None,
        ))
    return rows


def gen_comments(ticket_rows, agent_ids):
    cid = 0
    bodies_user = ["Hi, my transfer hasn't arrived yet.", "Any update?",
                   "Thanks for the help!", "This is urgent please.",
                   "I attached my ID document.", "Still not resolved."]
    bodies_agent = ["Thanks for reaching out, let me check.",
                    "I've escalated this to payments ops.",
                    "Your transfer has been released.",
                    "Could you confirm the recipient details?",
                    "Apologies for the delay — resolving now."]
    for t in ticket_rows:
        tid, requester_id, assignee_id = t[0], t[1], t[2]
        r = rng("zd_comment", tid)
        n = r.randint(1, 5)
        base = t[15]  # created_at
        for j in range(n):
            is_agent = j % 2 == 1 and assignee_id is not None
            author = assignee_id if is_agent else requester_id
            yield (
                cid,
                tid,
                author,
                r.choice(bodies_agent if is_agent else bodies_user),
                True,
                is_agent,
                base + dt.timedelta(hours=j * r.randint(1, 12)),
            )
            cid += 1


def gen_ratings(ticket_rows):
    rid = 0
    comments = ["Fast and helpful!", "Took too long.", "Great agent.",
                "Issue not fully resolved.", None, None, None]
    for t in ticket_rows:
        sat = t[12]
        if sat in ("good", "bad"):
            r = rng("zd_rating", t[0])
            yield (
                rid, t[0], t[2], t[1], sat,
                maybe_null(r.choice(comments), 0.5, r),
                t[16], t[16],     # updated_at as created/updated
            )
            rid += 1


def main(conn):
    ensure_schema(conn, "raw_zendesk")
    apply_ddl_file(conn, DDL)
    truncate(conn,
             "raw_zendesk.satisfaction_ratings", "raw_zendesk.ticket_comments",
             "raw_zendesk.tickets", "raw_zendesk.users")

    n_endusers = max(50, N["customers"] // 3)
    n_tickets = n_endusers * 2

    user_rows, agent_ids, enduser_ids = gen_users(n_endusers)
    ticket_rows = gen_tickets(n_tickets, agent_ids, enduser_ids)

    c1 = bulk_copy(conn, "raw_zendesk.users",
                   ["id", "name", "email", "phone", "role", "external_id",
                    "organization_id", "locale", "time_zone", "verified",
                    "suspended", "tags", "created_at", "updated_at"], user_rows)
    c2 = bulk_copy(conn, "raw_zendesk.tickets",
                   ["id", "requester_id", "assignee_id", "subject", "status",
                    "priority", "type", "channel", "tags", "group_name",
                    "requester_email", "transfer_id", "satisfaction",
                    "is_public", "created_at", "updated_at", "solved_at",
                    "metadata"], ticket_rows)
    c3 = bulk_copy(conn, "raw_zendesk.ticket_comments",
                   ["id", "ticket_id", "author_id", "body", "public",
                    "is_agent", "created_at"],
                   gen_comments(ticket_rows, agent_ids))
    c4 = bulk_copy(conn, "raw_zendesk.satisfaction_ratings",
                   ["id", "ticket_id", "assignee_id", "requester_id", "score",
                    "comment", "created_at", "updated_at"],
                   gen_ratings(ticket_rows))

    print(f"raw_zendesk: users={c1} tickets={c2} ticket_comments={c3} "
          f"satisfaction_ratings={c4}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
