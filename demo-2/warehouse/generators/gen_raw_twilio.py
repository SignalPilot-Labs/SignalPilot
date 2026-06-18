"""
Domain 10 — raw_twilio generator.

Programmable SMS (messages) + Lookup v2 (phone_lookups). Recipients are
canonical customers (phone routed through dirty_phone). Twilio's native
quirks: SID ids, RFC2822-string timestamps, signed string "price", epoch-ms
lookup timestamps, CamelCase-ish status enums, sparse error columns.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from common import (
    N, SCALE, connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    customer_master, rng, rand_datetime, det_uuid, maybe_null, dirty_phone,
    ts_epoch_ms,
)

_DDL = Path(__file__).resolve().parent.parent / "sql" / "ddl" / "raw_twilio.sql"

ACCOUNT_SID = "AC" + det_uuid("twilio-acct").replace("-", "")[:32]
MSG_STATUS = ["delivered", "delivered", "delivered", "sent", "undelivered",
              "failed", "queued"]
MSG_TYPES = ["otp", "otp", "notification", "notification", "notification",
             "marketing"]
SHORTCODES = ["NALA", "+447488800000", "+12025550100", "MM247"]
LINE_TYPES = ["mobile", "mobile", "mobile", "landline", "voip", "nonFixedVoip"]
CARRIERS = {
    "KE": "Safaricom", "TZ": "Vodacom Tanzania", "NG": "MTN Nigeria",
    "GB": "Vodafone UK", "US": "T-Mobile US", "GH": "MTN Ghana",
    "UG": "MTN Uganda", "SN": "Orange Senegal", "IN": "Airtel India",
}
ERR_CODES = [30003, 30005, 30006, 30007, 21610]


def _rfc2822(d: dt.datetime) -> str:
    # Twilio renders dates as RFC2822 e.g. "Tue, 18 Jun 2026 14:03:22 +0000"
    return d.strftime("%a, %d %b %Y %H:%M:%S +0000")


def _msg_body(mtype: str, code: str, r) -> str:
    if mtype == "otp":
        return f"Your NALA verification code is {code}. Do not share it."
    if mtype == "notification":
        return r.choice([
            "Your transfer has been delivered. Thanks for using NALA.",
            "Your money is on the way. Track it in the app.",
            "Funds received! Your recipient has been paid.",
        ])
    return r.choice([
        "Send money home for free this weekend with NALA.",
        "Refer a friend and earn $10. Open the app to share your code.",
    ])


def _gen_messages(cms):
    n = N["transfers"]  # SMS roughly tracks transfer volume + OTP traffic
    for i in range(n):
        r = rng("twilio_msg", i)
        cust = cms[r.randrange(len(cms))]
        mtype = r.choice(MSG_TYPES)
        status = r.choice(MSG_STATUS)
        created = rand_datetime(r)
        sent = created + dt.timedelta(seconds=r.randint(1, 30))
        updated = sent + dt.timedelta(seconds=r.randint(0, 120))
        code = str(r.randint(100000, 999999))
        sid = "SM" + det_uuid(("twilio_msg", i)).replace("-", "")[:32]
        failed = status in ("undelivered", "failed")
        err_code = maybe_null(r.choice(ERR_CODES), 0.0, r) if failed else None
        err_msg = ("Unknown destination handset" if failed else None)
        to_num = dirty_phone(cust.phone, r)
        payload = {
            "sid": sid, "status": status, "direction": "outbound-api",
            "num_segments": str(1 if len(_msg_body(mtype, code, r)) <= 160 else 2),
        }
        yield (
            sid,
            ACCOUNT_SID,
            maybe_null("MG" + det_uuid(("twilio_mg", i % 5)).replace("-", "")[:32], 0.6, r),
            to_num,
            r.choice(SHORTCODES),
            _msg_body(mtype, code, r),
            1 if r.random() < 0.85 else 2,
            0,
            "outbound-api" if r.random() < 0.97 else "inbound",
            mtype,
            status,
            err_code,
            err_msg,
            f"-0.{r.randint(40, 95):02d}00"[:7] if status not in ("queued",) else None,
            "USD",
            maybe_null(cust.cid, 0.10, r),
            _rfc2822(created),
            None if status == "queued" else _rfc2822(sent),
            _rfc2822(updated),
            "2010-04-01",
            json.dumps(payload),
        )


def _gen_lookups(cms):
    n = max(200, N["transfers"] // 4)
    for i in range(n):
        r = rng("twilio_lookup", i)
        cust = cms[r.randrange(len(cms))]
        valid = r.random() < 0.93
        country = cust.country
        carrier = CARRIERS.get(country, "Unknown Carrier")
        lt = r.choice(LINE_TYPES)
        created = rand_datetime(r)
        sid = "LU" + det_uuid(("twilio_lookup", i)).replace("-", "")[:30]
        cc = {"GB": "44", "US": "1"}.get(country, "33")
        yield (
            sid,
            cust.phone,                                 # clean E.164 here
            maybe_null(f"0{cust.phone[-10:]}", 0.2, r),
            country,
            f"+{cc}",
            valid,
            None if valid else "TOO_SHORT",
            lt,
            maybe_null(carrier, 0.08, r),
            maybe_null(str(r.randint(600, 650)), 0.3, r),
            maybe_null(f"{r.randint(1, 99):02d}", 0.3, r),
            maybe_null(r.choice(["low", "low", "medium", "high"]), 0.5, r),
            maybe_null(cust.cid, 0.15, r),
            ts_epoch_ms(created),
            json.dumps({"valid": valid, "line_type_intelligence": {"type": lt}}),
        )


MESSAGE_COLS = [
    "message_sid", "account_sid", "messaging_service_sid", "to_number",
    "from_number", "body", "num_segments", "num_media", "direction",
    "message_type", "status", "error_code", "error_message", "price",
    "price_unit", "customer_id", "date_created", "date_sent", "date_updated",
    "api_version", "raw_payload",
]
LOOKUP_COLS = [
    "lookup_sid", "phone_number", "national_format", "country_code",
    "calling_country_code", "valid", "validation_errors", "line_type",
    "carrier_name", "carrier_mcc", "carrier_mnc", "sim_swap_risk",
    "customer_id", "created_epoch_ms", "raw_response",
]


def main(conn):
    ensure_schema(conn, "raw_twilio")
    apply_ddl_file(conn, _DDL)
    truncate(conn, "raw_twilio.messages", "raw_twilio.phone_lookups")
    cms = customer_master()
    m = bulk_copy(conn, "raw_twilio.messages", MESSAGE_COLS, _gen_messages(cms))
    l = bulk_copy(conn, "raw_twilio.phone_lookups", LOOKUP_COLS, _gen_lookups(cms))
    print(f"[raw_twilio] scale={SCALE} messages={m} phone_lookups={l}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
