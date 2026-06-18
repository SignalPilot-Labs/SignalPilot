"""
Domain 10 — raw_sendgrid generator.

Transactional + marketing email (messages) and the Event Webhook fan-out
(events). Recipients are canonical customers (email via dirty_email).
SendGrid quirks: sg_message_id, ISO-Z send timestamps, epoch-SECOND event
timestamps (native to SendGrid), category strings, sparse engagement fields.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from common import (
    N, SCALE, connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    customer_master, rng, rand_datetime, det_uuid, maybe_null, dirty_email,
    ts_isoz, ts_epoch_s,
)

_DDL = Path(__file__).resolve().parent.parent / "sql" / "ddl" / "raw_sendgrid.sql"

CATEGORIES = ["otp", "receipt", "receipt", "kyc", "notification",
              "marketing", "marketing"]
FROM_BY_CAT = {
    "otp": "security@nala.com", "receipt": "receipts@nala.com",
    "kyc": "verify@nala.com", "notification": "noreply@nala.com",
    "marketing": "hello@nala.com",
}
SUBJECTS = {
    "otp": "Your NALA verification code",
    "receipt": "Your transfer receipt",
    "kyc": "Action needed: verify your identity",
    "notification": "Your money has arrived",
    "marketing": "Send money home for free this weekend",
}
TEMPLATES = {
    "otp": "d-otp0001", "receipt": "d-rcpt0002", "kyc": "d-kyc0003",
    "notification": "d-notif0004", "marketing": "d-mktg0005",
}
MSG_STATUS = ["delivered", "delivered", "delivered", "delivered",
              "processed", "bounce", "dropped"]
IP_POOLS = ["transactional", "transactional", "marketing"]
BOUNCE_REASONS = ["550 5.1.1 user unknown", "552 mailbox full",
                  "421 temporarily deferred"]
USER_AGENTS = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0",
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/123.0 Mobile",
]


def _msg_ctx(i, cms):
    """Deterministically reconstruct a message's context from its index.

    Both the messages pass and the events pass call this with the same index
    and seed, so events line up with their message without holding state."""
    r = rng("sg_msg", i)
    cust = cms[r.randrange(len(cms))]
    cat = r.choice(CATEGORIES)
    status = r.choice(MSG_STATUS)
    sent = rand_datetime(r)
    mid = det_uuid(("sg_msg", i)).replace("-", "")[:22] + ".filterdrecv-x"
    delivered = status == "delivered"
    opens = (r.randint(0, 4) if delivered and r.random() < 0.45 else 0)
    clicks = (r.randint(0, opens) if opens and r.random() < 0.5 else 0)
    return {"r": r, "cust": cust, "mid": mid, "email": cust.email,
            "cid": cust.cid, "cat": cat, "status": status, "sent": sent,
            "opens": opens, "clicks": clicks, "i": i}


def _gen_messages(cms):
    n = N["transfers"]  # emails roughly track transfer + lifecycle volume
    for i in range(n):
        c = _msg_ctx(i, cms)
        r = c["r"]
        marketing = c["cat"] == "marketing"
        yield (
            c["mid"],
            dirty_email(c["email"], r),
            FROM_BY_CAT[c["cat"]],
            SUBJECTS[c["cat"]],
            TEMPLATES[c["cat"]],
            c["cat"],
            maybe_null(r.randint(1000, 9999), 0.6 if marketing else 0.95, r),
            c["status"],
            c["opens"],
            c["clicks"],
            maybe_null(c["cid"], 0.10, r),
            r.choice(IP_POOLS),
            marketing,
            ts_isoz(c["sent"]),
            json.dumps({"message_id": c["mid"], "categories": [c["cat"]],
                        "status": c["status"]}),
        )


def _gen_events(cms):
    n = N["transfers"]
    for i in range(n):
        ctx = _msg_ctx(i, cms)
        er = rng("sg_evt_seq", i)
        for ev in _events_for(ctx, er):
            yield ev


def _events_for(ctx, r):
    """Fan a message out into webhook events (processed -> delivered -> open...)."""
    seq = 0
    mid, sent = ctx["mid"], ctx["sent"]

    def mk(event, t, **extra):
        nonlocal seq
        seq += 1
        eid = det_uuid(("sg_evt", ctx["i"], seq)).replace("-", "")
        return (
            eid, mid, dirty_email(ctx["email"], r), event, ts_epoch_s(t),
            maybe_null(f"<{eid[:16]}@nala.com>", 0.2, r),
            ctx["cat"],
            extra.get("url"), extra.get("ua"), extra.get("ip"),
            extra.get("reason"), extra.get("bounce_type"), extra.get("response"),
            maybe_null(ctx["cid"], 0.12, r),
        )

    t = sent
    yield mk("processed", t)
    if ctx["status"] == "dropped":
        yield mk("dropped", t + dt.timedelta(seconds=1),
                 reason="Bounced Address", response="550 dropped")
        return
    if ctx["status"] == "bounce":
        yield mk("bounce", t + dt.timedelta(seconds=2),
                 reason=r.choice(BOUNCE_REASONS), bounce_type="bounce",
                 response=r.choice(BOUNCE_REASONS))
        return
    t = t + dt.timedelta(seconds=r.randint(1, 8))
    yield mk("delivered", t, response="250 OK")
    for _ in range(ctx["opens"]):
        t = t + dt.timedelta(minutes=r.randint(1, 600))
        yield mk("open", t, ua=r.choice(USER_AGENTS),
                 ip=f"{r.randint(1,223)}.{r.randint(0,255)}.{r.randint(0,255)}.{r.randint(1,254)}")
    for _ in range(ctx["clicks"]):
        t = t + dt.timedelta(minutes=r.randint(1, 60))
        yield mk("click", t, ua=r.choice(USER_AGENTS),
                 url="https://nala.com/app?utm_source=sendgrid",
                 ip=f"{r.randint(1,223)}.{r.randint(0,255)}.{r.randint(0,255)}.{r.randint(1,254)}")
    if r.random() < 0.02:
        yield mk("spamreport", t + dt.timedelta(hours=1))


MESSAGE_COLS = [
    "sg_message_id", "to_email", "from_email", "subject", "template_id",
    "category", "asm_group_id", "msg_status", "opens_count", "clicks_count",
    "customer_id", "ip_pool", "is_marketing", "sent_at", "raw_payload",
]
EVENT_COLS = [
    "event_id", "sg_message_id", "email", "event", "timestamp", "smtp_id",
    "category", "url", "useragent", "ip", "reason", "bounce_type", "response",
    "customer_id",
]


def main(conn):
    ensure_schema(conn, "raw_sendgrid")
    apply_ddl_file(conn, _DDL)
    truncate(conn, "raw_sendgrid.messages", "raw_sendgrid.events")
    cms = customer_master()
    # Two independent streaming passes keyed by message index keep memory
    # bounded; events are reconstructed deterministically from the same seed.
    m = bulk_copy(conn, "raw_sendgrid.messages", MESSAGE_COLS, _gen_messages(cms))
    e = bulk_copy(conn, "raw_sendgrid.events", EVENT_COLS, _gen_events(cms))
    print(f"[raw_sendgrid] scale={SCALE} messages={m} events={e}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
