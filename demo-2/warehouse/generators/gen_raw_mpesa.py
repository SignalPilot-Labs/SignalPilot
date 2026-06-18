"""
Domain 5 — Mobile-Money Rails: raw_mpesa generator.

Safaricom M-PESA Daraja API landing tables. Authentic CamelCase field
naming. These are the collection (STK/C2B) and payout (B2C) legs for NALA
transfers into Kenya / Tanzania (KES / TZS receive markets).

Run:  NALA_SCALE=test ./.venv/Scripts/python.exe generators/gen_raw_mpesa.py
"""
from __future__ import annotations

import json
import datetime as dt
from pathlib import Path

from common import (
    connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    customer_master, random_customer, rng, rand_datetime, det_uuid,
    maybe_null, dirty_phone, ts_iso, ts_epoch_ms,
    RECEIVE_MARKETS, USD_FX, N,
)

DDL = Path(__file__).resolve().parent.parent / "sql" / "ddl" / "raw_mpesa.sql"

SCHEMA = "raw_mpesa"
TABLES = [
    f"{SCHEMA}.stk_push_requests",
    f"{SCHEMA}.c2b_payments",
    f"{SCHEMA}.b2c_requests",
    f"{SCHEMA}.callbacks",
    f"{SCHEMA}.transaction_status_queries",
    f"{SCHEMA}.account_balance_queries",
    f"{SCHEMA}.statements",
]

# Daraja serves only the East-Africa M-PESA markets. NALA uses M-PESA in KE & TZ.
MPESA_MARKETS = ["KE", "TZ"]
SHORTCODES = {"KE": "174379", "TZ": "601426"}   # plausible paybill shortcodes
RECEIPT_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

# Daraja date format yyyyMMddHHmmss (string).
def daraja_ts(d: dt.datetime) -> str:
    return d.strftime("%Y%m%d%H%M%S")

def b2c_ts(d: dt.datetime) -> str:           # "dd.MM.yyyy HH:mm:ss"
    return d.strftime("%d.%m.%Y %H:%M:%S")

def stmt_ts(d: dt.datetime) -> str:          # "yyyy-MM-dd HH:mm:ss"
    return d.strftime("%Y-%m-%d %H:%M:%S")


def mpesa_receipt(r) -> str:
    return "".join(r.choice(RECEIPT_CHARS) for _ in range(10))


def kes_amount(r, usd_lo=10, usd_hi=2500) -> float:
    """A plausible KES receive amount derived from a USD-equivalent send."""
    usd = r.uniform(usd_lo, usd_hi)
    return round(usd * USD_FX["KES"], 2)


def msisdn(country: str, r) -> str:
    """A Safaricom/Vodacom MSISDN in E.164 then dirtied via dirty_phone."""
    cc = "+254" if country == "KE" else "+255"
    num = f"{cc}7{r.randint(10000000, 99999999)}"
    return dirty_phone(num, r)


def masked_public_name(country: str, cust, r) -> str:
    """Daraja masks the receiver: '2547****1234 - JOHN D.'"""
    cc = "254" if country == "KE" else "255"
    tail = r.randint(1000, 9999)
    return f"{cc}7****{tail} - {cust.first.upper()} {cust.last[0].upper()}."


# How many M-PESA legs we mint. A subset of all transfers route to KE/TZ.
def n_mpesa_legs() -> int:
    return max(50, int(N["transfers"] * 0.18))


# ---------------------------------------------------------------------
# Row generators
# ---------------------------------------------------------------------
def gen_b2c_requests():
    """Payout leg — the primary M-PESA fact. Yields rows + side-channels
    used by callbacks/status/statements."""
    n = n_mpesa_legs()
    cmds = ["BusinessPayment", "SalaryPayment", "PromotionPayment"]
    for i in range(n):
        r = rng("mpesa_b2c", i)
        country = r.choice(MPESA_MARKETS)
        cust = random_customer(r)
        ts = rand_datetime(r)
        amount = kes_amount(r)
        # ~88% succeed, ~9% fail, ~3% still pending (no callback yet)
        roll = r.random()
        if roll < 0.88:
            result_code, result_desc, status = 0, "The service request is processed successfully.", "ok"
        elif roll < 0.97:
            result_code = r.choice([1, 2001, 17, 21])
            result_desc = r.choice([
                "The balance is insufficient for the transaction.",
                "The initiator information is invalid.",
                "Less Than Minimum Transaction Value.",
                "Unresolved initiator.",
            ])
            status = "fail"
        else:
            result_code, result_desc, status = None, None, "pending"

        ocid = f"AG_{daraja_ts(ts)}_{det_uuid(('mpesa_b2c', i))[:16]}"
        conv_id = f"AG_{daraja_ts(ts)}_{r.randint(10**11, 10**12):x}"
        receipt = mpesa_receipt(r) if status == "ok" else None
        txn_amount = amount if status == "ok" else None
        working = round(r.uniform(5e5, 5e7), 2)

        nala_tid = str(det_uuid(("transfer", r.randrange(N["transfers"]))))
        payload = {
            "Result": {
                "ResultType": 0, "ResultCode": result_code,
                "ResultDesc": result_desc,
                "OriginatorConversationID": ocid, "ConversationID": conv_id,
                "TransactionID": receipt,
            }
        }
        yield (
            ocid, conv_id, receipt,
            f"nala_api_{country.lower()}",
            r.choice(cmds), amount,
            SHORTCODES[country],                       # PartyA shortcode
            msisdn(country, r),                        # PartyB recipient MSISDN (PII)
            maybe_null(r.choice(["NALA payout", "Remittance", "Transfer", ""]), 0.1, r),
            maybe_null("NALA", 0.3, r),
            "https://api.nala.com/mpesa/b2c/timeout",
            "https://api.nala.com/mpesa/b2c/result",
            "0", "Accept the service request successfully.",
            result_code, result_desc,
            receipt, txn_amount,
            r.choice(["Y", "N"]),
            round(r.uniform(0, 1000), 2),
            masked_public_name(country, cust, r),      # PII masked
            working, working,
            b2c_ts(ts) if status == "ok" else None,    # dd.MM.yyyy HH:mm:ss
            nala_tid, cust.code,
            "KES" if country == "KE" else "TZS",
            ts_iso_dt(ts),                             # created_at timestamptz
            json.dumps(payload),
        )


def ts_iso_dt(d: dt.datetime) -> str:
    # ISO for timestamptz column (psycopg COPY accepts this text form)
    return d.strftime("%Y-%m-%d %H:%M:%S")


def gen_stk_push_requests():
    """Collection leg (Lipa na M-PESA Online). Fewer than payouts."""
    n = max(30, int(n_mpesa_legs() * 0.5))
    for i in range(n):
        r = rng("mpesa_stk", i)
        country = "KE" if r.random() < 0.8 else "TZ"
        cust = random_customer(r)
        ts = rand_datetime(r)
        amount = kes_amount(r, 5, 800)
        roll = r.random()
        if roll < 0.82:
            result_code, result_desc = 0, "The service request is processed successfully."
            receipt = mpesa_receipt(r)
        elif roll < 0.95:
            result_code = r.choice([1, 1032, 1037, 2001])
            result_desc = r.choice([
                "The balance is insufficient for the transaction.",
                "Request cancelled by user.",
                "DS timeout user cannot be reached.",
                "Wrong PIN entered.",
            ])
            receipt = None
        else:
            result_code, result_desc, receipt = None, None, None   # still pending

        # i guarantees PK uniqueness at demo/large volume (pure-random collided).
        merchant_req = f"{r.randint(1000,9999)}-{r.randint(1000,9999)}-{i}"
        checkout_req = f"ws_CO_{daraja_ts(ts)}{r.randint(100000,999999)}"
        phone = msisdn(country, r)
        nala_tid = str(det_uuid(("transfer", r.randrange(N["transfers"]))))
        payload = {"CheckoutRequestID": checkout_req, "ResultCode": result_code}
        yield (
            merchant_req, checkout_req, SHORTCODES[country],
            r.choice(["CustomerPayBillOnline", "CustomerBuyGoodsOnline"]),
            amount,
            phone,                                     # PartyA payer MSISDN
            SHORTCODES[country],                       # PartyB
            phone,                                     # PhoneNumber (PII)
            maybe_null(cust.code, 0.15, r),            # AccountReference
            r.choice(["NALA Top-up", "Wallet funding", "Payment"]),
            "0", "Success. Request accepted for processing.",
            "Success. Request accepted for processing.",
            result_code, result_desc, receipt,
            nala_tid, cust.code,
            daraja_ts(ts),                             # TransactionDate string
            ts_iso_dt(ts),
            json.dumps(payload),
        )


def gen_c2b_payments():
    n = max(30, int(n_mpesa_legs() * 0.4))
    for i in range(n):
        r = rng("mpesa_c2b", i)
        country = "KE" if r.random() < 0.8 else "TZ"
        cust = random_customer(r)
        ts = rand_datetime(r)
        amount = kes_amount(r, 5, 1500)
        org_bal = round(r.uniform(1e5, 5e7), 2)
        yield (
            mpesa_receipt(r),                          # TransID
            r.choice(["Pay Bill", "Buy Goods"]),
            daraja_ts(ts),                             # TransTime string
            amount, SHORTCODES[country],
            maybe_null(cust.code, 0.2, r),             # BillRefNumber
            maybe_null(f"INV{r.randint(10000,99999)}", 0.6, r),
            org_bal,
            maybe_null(f"TP{r.randint(10**6,10**7)}", 0.7, r),
            msisdn(country, r),                        # MSISDN (PII)
            cust.first,                                # FirstName (PII)
            maybe_null(cust.last[:3], 0.5, r),         # MiddleName (PII, sparse)
            maybe_null(cust.last, 0.4, r),             # LastName (PII, often null)
            str(det_uuid(("transfer", r.randrange(N["transfers"])))),
            cust.code,
            "KES" if country == "KE" else "TZS",
            ts_epoch_ms(ts),                           # ingested_at epoch ms
            json.dumps({"TransID": "REDACTED", "TransAmount": amount}),
        )


def gen_callbacks():
    """Async result callbacks for B2C + STK legs. ~2% are duplicates."""
    cb_id = 1
    # B2C callbacks
    nb = n_mpesa_legs()
    for i in range(nb):
        r = rng("mpesa_b2c", i)          # same seed as b2c -> consistent
        country = r.choice(MPESA_MARKETS)
        cust = random_customer(r)
        ts = rand_datetime(r)
        amount = kes_amount(r)
        roll = r.random()
        if roll < 0.88:
            result_code = 0
        elif roll < 0.97:
            result_code = r.choice([1, 2001, 17, 21])
        else:
            continue                     # pending: no callback arrived

        ocid = f"AG_{daraja_ts(ts)}_{det_uuid(('mpesa_b2c', i))[:16]}"
        conv_id = f"AG_{daraja_ts(ts)}_{r.randint(10**11, 10**12):x}"
        receipt = mpesa_receipt(r) if result_code == 0 else None
        rc = rng("mpesa_cb", i)
        recv = ts + dt.timedelta(seconds=rc.randint(1, 90))
        params = {"ResultParameter": [
            {"Key": "TransactionAmount", "Value": amount},
            {"Key": "TransactionReceipt", "Value": receipt},
            {"Key": "ReceiverPartyPublicName", "Value": masked_public_name(country, cust, rc)},
        ]} if result_code == 0 else None
        dup = rc.random() < 0.02

        row = (
            cb_id, "b2c", conv_id, ocid, None, None,
            0, result_code,
            "The service request is processed successfully." if result_code == 0
            else "The balance is insufficient for the transaction.",
            receipt, ts_epoch_ms(recv), dup,
            json.dumps(params) if params else None,
            json.dumps({"Result": {"ResultCode": result_code}}),
        )
        yield row
        cb_id += 1
        if dup:                          # emit the duplicate too
            yield (cb_id,) + row[1:]
            cb_id += 1

    # STK callbacks
    ns = max(30, int(n_mpesa_legs() * 0.5))
    for i in range(ns):
        r = rng("mpesa_stk", i)
        ts = rand_datetime(r)
        roll = r.random()
        if roll < 0.82:
            result_code = 0
        elif roll < 0.95:
            result_code = r.choice([1, 1032, 1037, 2001])
        else:
            continue
        merchant_req = f"{r.randint(1000,9999)}-{r.randint(1000,9999)}-{r.randint(1,9)}"
        checkout_req = f"ws_CO_{daraja_ts(ts)}{r.randint(100000,999999)}"
        receipt = mpesa_receipt(r) if result_code == 0 else None
        rc = rng("mpesa_stkcb", i)
        recv = ts + dt.timedelta(seconds=rc.randint(1, 60))
        params = {"ResultParameter": [
            {"Key": "Amount", "Value": kes_amount(r, 5, 800)},
            {"Key": "MpesaReceiptNumber", "Value": receipt},
        ]} if result_code == 0 else None
        yield (
            cb_id, "stk", None, None, checkout_req, merchant_req,
            None, result_code,
            "The service request is processed successfully." if result_code == 0
            else "Request cancelled by user.",
            receipt, ts_epoch_ms(recv), False,
            json.dumps(params) if params else None,
            json.dumps({"Body": {"stkCallback": {"ResultCode": result_code}}}),
        )
        cb_id += 1


def gen_transaction_status_queries():
    """Reconciliation queries — mostly target the pending/failed B2C legs."""
    qn = max(20, int(n_mpesa_legs() * 0.12))
    for i in range(qn):
        r = rng("mpesa_status", i)
        country = r.choice(MPESA_MARKETS)
        cust = random_customer(r)
        ts = rand_datetime(r)
        completed = r.random() < 0.6
        if completed:
            result_code, status = 0, "Completed"
        else:
            result_code = r.choice([1, 17])
            status = r.choice(["Failed", "PENDING_OLD"])   # legacy enum value kept around
        ocid = f"AG_{daraja_ts(ts)}_{det_uuid(('mpesa_status', i))[:16]}"
        yield (
            ocid,
            f"AG_{daraja_ts(ts)}_{r.randint(10**11,10**12):x}",
            mpesa_receipt(r),
            SHORTCODES[country], "4",
            result_code, "The service request is processed successfully." if completed else "Failed",
            masked_public_name(country, cust, r),
            masked_public_name(country, random_customer(r), r),
            status, r.choice(["Organization settlement", "Disbursement", ""]),
            daraja_ts(ts) if completed else None,
            kes_amount(r),
            ts_iso_dt(ts + dt.timedelta(hours=r.randint(1, 48))),
            json.dumps({"TransactionStatus": status}),
        )


def gen_account_balance_queries():
    """Treasury float polls — a few per day across the date range."""
    rows = []
    rmaster = rng("mpesa_bal_master")
    start = dt.date(2023, 1, 1)
    end = dt.date(2026, 6, 18)
    days = (end - start).days
    qid = 0
    for d in range(0, days, 3):          # every ~3 days
        for country in MPESA_MARKETS:
            r = rng("mpesa_bal", qid)
            day = start + dt.timedelta(days=d)
            ts = dt.datetime.combine(day, dt.time(r.randint(0, 5), r.randint(0, 59)))
            working = round(r.uniform(1e6, 8e7), 2)
            rows.append((
                f"AG_{daraja_ts(ts)}_{det_uuid(('mpesa_bal', qid))[:16]}",
                f"AG_{daraja_ts(ts)}_{r.randint(10**11,10**12):x}",
                SHORTCODES[country], 0,
                "The service request is processed successfully.",
                working,
                round(working * r.uniform(0.05, 0.2), 2),
                round(working * r.uniform(0.0, 0.05), 2),
                "KES" if country == "KE" else "TZS",
                daraja_ts(ts),
                ts_iso_dt(ts),
                json.dumps({"ResultCode": 0}),
            ))
            qid += 1
    return rows


def gen_statements():
    """Daily reconciliation statement lines — one per settled B2C/C2B leg
    (sampled). Running balance per shortcode."""
    line_id = 1
    n = max(40, int(n_mpesa_legs() * 0.6))
    bal = {"KE": 5_000_000.0, "TZ": 3_000_000.0}
    for i in range(n):
        r = rng("mpesa_stmt", i)
        country = r.choice(MPESA_MARKETS)
        ts = rand_datetime(r, start=dt.date(2023, 1, 1))
        is_payout = r.random() < 0.7
        amt = kes_amount(r)
        if is_payout:
            paidin, withdrawn = None, amt
            bal[country] -= amt
            ttype = "Business Payment to Customer"
        else:
            paidin, withdrawn = amt, None
            bal[country] += amt
            ttype = r.choice(["Pay Bill", "Buy Goods"])
        if bal[country] < 0:
            bal[country] += 5_000_000.0
        yield (
            line_id, SHORTCODES[country], mpesa_receipt(r),
            stmt_ts(ts), stmt_ts(ts - dt.timedelta(seconds=r.randint(1, 30))),
            ttype, paidin, withdrawn, round(bal[country], 2),
            r.random() < 0.95,                         # BalanceConfirmed
            r.choice(["", "Salary Payment", "Customer Payment"]),
            maybe_null(f"Masked counterparty {r.randint(1000,9999)}", 0.3, r),
            maybe_null(mpesa_receipt(r), 0.6, r),
            maybe_null(SHORTCODES[country], 0.4, r),
            ts.date(),
            "KES" if country == "KE" else "TZS",
            r.random() < 0.01,                         # is_deleted soft delete
            json.dumps({"ReceiptNo": "REDACTED"}),
        )
        line_id += 1


# ---------------------------------------------------------------------
def main(conn):
    ensure_schema(conn, SCHEMA)
    apply_ddl_file(conn, DDL)
    truncate(conn, *TABLES)

    n = bulk_copy(conn, f"{SCHEMA}.b2c_requests", [
        "OriginatorConversationID","ConversationID","TransactionID","InitiatorName",
        "CommandID","Amount","PartyA","PartyB","Remarks","Occasion","QueueTimeOutURL",
        "ResultURL","ResponseCode","ResponseDescription","ResultCode","ResultDesc",
        "TransactionReceipt","TransactionAmount","B2CRecipientIsRegisteredCustomer",
        "B2CChargesPaidAccountAvailableFunds","ReceiverPartyPublicName",
        "B2CUtilityAccountAvailableFunds","B2CWorkingAccountAvailableFunds",
        "TransactionCompletedDateTime","nala_transfer_id","nala_customer_code",
        "currency","created","raw_payload",
    ], gen_b2c_requests())
    print(f"  b2c_requests: {n}")

    n = bulk_copy(conn, f"{SCHEMA}.stk_push_requests", [
        "MerchantRequestID","CheckoutRequestID","BusinessShortCode","TransactionType",
        "Amount","PartyA","PartyB","PhoneNumber","AccountReference","TransactionDesc",
        "ResponseCode","ResponseDescription","CustomerMessage","ResultCode","ResultDesc",
        "MpesaReceiptNumber","nala_transfer_id","nala_customer_code","TransactionDate",
        "created_at","raw_payload",
    ], gen_stk_push_requests())
    print(f"  stk_push_requests: {n}")

    n = bulk_copy(conn, f"{SCHEMA}.c2b_payments", [
        "TransID","TransactionType","TransTime","TransAmount","BusinessShortCode",
        "BillRefNumber","InvoiceNumber","OrgAccountBalance","ThirdPartyTransID","MSISDN",
        "FirstName","MiddleName","LastName","nala_transfer_id","nala_customer_code",
        "currency","ingested_at","raw_payload",
    ], gen_c2b_payments())
    print(f"  c2b_payments: {n}")

    n = bulk_copy(conn, f"{SCHEMA}.callbacks", [
        "callback_id","callback_type","ConversationID","OriginatorConversationID",
        "CheckoutRequestID","MerchantRequestID","ResultType","ResultCode","ResultDesc",
        "TransactionID","received_at_ms","is_duplicate","ResultParameters","raw_payload",
    ], gen_callbacks())
    print(f"  callbacks: {n}")

    n = bulk_copy(conn, f"{SCHEMA}.transaction_status_queries", [
        "OriginatorConversationID","ConversationID","TransactionID","PartyA",
        "IdentifierType","ResultCode","ResultDesc","DebitPartyName","CreditPartyName",
        "TransactionStatus","ReasonType","FinalisedTime","Amount","queried_at","raw_payload",
    ], gen_transaction_status_queries())
    print(f"  transaction_status_queries: {n}")

    n = bulk_copy(conn, f"{SCHEMA}.account_balance_queries", [
        "OriginatorConversationID","ConversationID","BusinessShortCode","ResultCode",
        "ResultDesc","WorkingAccountBalance","UtilityAccountBalance",
        "ChargesPaidAccountBalance","BalanceCurrency","BOCompletedTime","queried_at",
        "raw_payload",
    ], gen_account_balance_queries())
    print(f"  account_balance_queries: {n}")

    n = bulk_copy(conn, f"{SCHEMA}.statements", [
        "statement_line_id","BusinessShortCode","ReceiptNo","CompletionTime",
        "InitiationTime","TransactionType","Paidin","Withdrawn","Balance",
        "BalanceConfirmed","ReasonType","OtherPartyInfo","LinkedTransactionID",
        "AccountNo","statement_date","currency","is_deleted","raw_payload",
    ], gen_statements())
    print(f"  statements: {n}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
    print("raw_mpesa: done")
