"""
Domain 5 — Mobile-Money Rails: raw_flutterwave generator.

Flutterwave v3 Transfers API landing tables. Flutterwave is one of NALA's
pan-African payout rails (PARTNERS["payout_rail"]). These are the bank /
mobile-money payout legs across multiple African receive markets.

Field naming follows Flutterwave's snake_case JSON style — deliberately
different from M-PESA's CamelCase (cross-vendor naming drift).

Run:  NALA_SCALE=test ./.venv/Scripts/python.exe generators/gen_raw_flutterwave.py
"""
from __future__ import annotations

import json
import datetime as dt
from pathlib import Path

from common import (
    connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    random_customer, rng, rand_datetime, det_uuid,
    maybe_null, dirty_phone, dirty_email, ts_isoz, ts_epoch_s,
    RECEIVE_MARKETS, RECEIVE_COUNTRIES, USD_FX, N,
)

DDL = Path(__file__).resolve().parent.parent / "sql" / "ddl" / "raw_flutterwave.sql"

SCHEMA = "raw_flutterwave"
TABLES = [
    f"{SCHEMA}.transfers",
    f"{SCHEMA}.transfer_retries",
    f"{SCHEMA}.balances",
    f"{SCHEMA}.banks",
    f"{SCHEMA}.beneficiaries",
    f"{SCHEMA}.webhooks",
    f"{SCHEMA}.settlements",
]

# Flutterwave covers NALA's non-East-Africa African markets (and overlaps).
# Exclude the Asian markets (FW Africa rail) — keep African receive countries.
FW_COUNTRIES = [c for c in RECEIVE_COUNTRIES
                if c in ("NG", "GH", "UG", "RW", "SN", "CI", "CM", "GA", "CG", "ZA", "KE", "TZ")]

# A small bank lookup per country (real-ish Flutterwave bank codes for NG).
BANKS = [
    (1,  "044", "Access Bank",            "NG", "NGN", False),
    (2,  "058", "GTBank",                  "NG", "NGN", False),
    (3,  "057", "Zenith Bank",             "NG", "NGN", False),
    (4,  "011", "First Bank of Nigeria",   "NG", "NGN", False),
    (5,  "MPS", "M-PESA",                  "KE", "KES", True),
    (6,  "MPS", "M-PESA",                  "TZ", "TZS", True),
    (7,  "MTN", "MTN Mobile Money",        "UG", "UGX", True),
    (8,  "MTN", "MTN Mobile Money",        "RW", "RWF", True),
    (9,  "MTN", "MTN Mobile Money",        "GH", "GHS", True),
    (10, "VOD", "Vodafone Cash",           "GH", "GHS", True),
    (11, "GH030", "Standard Chartered GH", "GH", "GHS", False),
    (12, "WAVE", "Wave",                   "SN", "XOF", True),
    (13, "OM",  "Orange Money",            "CI", "XOF", True),
    (14, "OM",  "Orange Money",            "CM", "XAF", True),
    (15, "ABSA","ABSA Bank",               "ZA", "ZAR", False),
    (16, "CAP", "Capitec",                 "ZA", "ZAR", False),
    (17, "AIRT","Airtel Money",            "GA", "XAF", True),
    (18, "MTN", "MTN Mobile Money",        "CG", "XAF", True),
]
BANKS_BY_COUNTRY = {}
for b in BANKS:
    BANKS_BY_COUNTRY.setdefault(b[3], []).append(b)


def hex_id(parts, width: int = 9) -> int:
    """Stable bigint id from a det_uuid seed (strip dashes first).

    Uses >=15 hex digits regardless of the requested width so distinct seeds
    don't collide at demo/large volume (9 digits = ~10^11 space, which suffers
    birthday collisions past ~500k rows). 15 hex digits stays within bigint.
    PK/FK consistency is preserved: same parts -> same value everywhere."""
    h = det_uuid(parts).replace("-", "")
    return int(h[:max(width, 15)], 16)


def receive_amount(country: str, r, usd_lo=10, usd_hi=2000) -> float:
    cur = RECEIVE_MARKETS[country][0]
    usd = r.uniform(usd_lo, usd_hi)
    return round(usd * USD_FX[cur], 2)


def acct_or_msisdn(bank, country: str, r) -> str:
    """Mobile-money beneficiaries carry an MSISDN; banks a 10-digit acct (PII)."""
    if bank[5]:  # is_mobile_money
        cc = {"KE": "+254", "TZ": "+255", "UG": "+256", "RW": "+250", "GH": "+233",
              "SN": "+221", "CI": "+225", "CM": "+237", "GA": "+241", "CG": "+242"}.get(country, "+234")
        return dirty_phone(f"{cc}7{r.randint(10000000, 99999999)}", r)
    return str(r.randint(10**9, 10**10 - 1))


N_BENEFICIARIES = max(40, int(N["recipients"] * 0.25))


def n_fw_transfers() -> int:
    return max(50, int(N["transfers"] * 0.22))


# ---------------------------------------------------------------------
def gen_banks():
    base = dt.datetime(2020, 1, 1)
    for b in BANKS:
        yield (b[0], b[1], b[2], b[3], b[4], b[5], base.strftime("%Y-%m-%d %H:%M:%S"))


def gen_beneficiaries():
    for i in range(N_BENEFICIARIES):
        r = rng("fw_benef", i)
        country = r.choice(FW_COUNTRIES)
        bank = r.choice(BANKS_BY_COUNTRY[country])
        cust = random_customer(r)
        cur = RECEIVE_MARKETS[country][0]
        acct = acct_or_msisdn(bank, country, r)
        full = f"{cust.first} {cust.last}"
        # beneficiary_name is a dirty near-dup: sometimes reordered/upper/typo'd
        bn_roll = r.random()
        if bn_roll < 0.5:
            bname = full
        elif bn_roll < 0.7:
            bname = full.upper()
        elif bn_roll < 0.85:
            bname = f"{cust.last} {cust.first}"      # order swapped
        else:
            bname = maybe_null(full, 0.3, r)
        created = rand_datetime(r)
        yield (
            hex_id(("fw_benef", i), 8),  # stable bigint id
            acct, bank[1], bank[2], full, bname,
            maybe_null(dirty_email(cust.email, r), 0.25, r),
            maybe_null(dirty_phone(cust.phone, r), 0.2, r),
            cur, country, cust.code, str(cust.uuid),
            r.random() < 0.05,
            json.dumps({"source": "nala_app", "verified": r.random() < 0.8}),
            ts_isoz(created),
        )


def gen_transfers():
    """The payout fact."""
    n = n_fw_transfers()
    for i in range(n):
        r = rng("fw_transfer", i)
        country = r.choice(FW_COUNTRIES)
        bank = r.choice(BANKS_BY_COUNTRY[country])
        cust = random_customer(r)
        cur = RECEIVE_MARKETS[country][0]
        ts = rand_datetime(r)
        amount = receive_amount(country, r)
        fee = round(amount * r.uniform(0.0, 0.012), 2)
        roll = r.random()
        if roll < 0.86:
            status, msg, bank_ref = "SUCCESSFUL", "Transaction was successful", f"FLW{r.randint(10**8, 10**9)}"
        elif roll < 0.95:
            status = r.choice(["FAILED", "QUEUED"])    # QUEUED is a legacy/stuck value
            msg = r.choice([
                "DISABLED MMO ACCOUNT", "Insufficient funds in beneficiary wallet",
                "Invalid account number", "Transaction limit exceeded",
            ])
            bank_ref = None
        else:
            status, msg, bank_ref = "PENDING", "Transaction is being processed", None

        acct = acct_or_msisdn(bank, country, r)
        full = f"{cust.first} {cust.last}"
        benef_id = hex_id(("fw_benef", r.randrange(N_BENEFICIARIES)), 8)
        nala_tid = str(det_uuid(("transfer", r.randrange(N["transfers"]))))
        tid = hex_id(("fw_transfer", i), 9)
        payload = {"data": {"id": tid, "status": status, "currency": cur, "amount": amount}}
        yield (
            tid,
            f"NALA_{det_uuid(('fw_transfer', i))[:18]}",
            acct, bank[1], bank[2], full, amount, fee, cur,
            r.choice(["NALA remittance payout", "Transfer", "Remittance", "NALA payout"]),
            status, msg,
            r.choice([0, 0, 0, 1]),                    # requires_approval
            r.choice([1, 1, 1, 0]),                    # is_approved
            bank_ref,
            json.dumps({"beneficiary_id": benef_id}),
            benef_id, nala_tid, cust.code,
            maybe_null(dirty_phone(cust.phone, r), 0.4, r),
            r.choice(["USD", "USDC", "GBP", "EUR"]),    # debit_currency
            ts_isoz(ts),                                # created_at string
            (ts + dt.timedelta(seconds=r.randint(0, 5))).strftime("%Y-%m-%d %H:%M:%S"),  # date_created drift
            json.dumps(payload),
        )


def gen_transfer_retries():
    """Retries for the failed/queued transfers."""
    n = n_fw_transfers()
    rid = 1
    for i in range(n):
        r = rng("fw_transfer", i)
        # reproduce status decision
        r.choice(FW_COUNTRIES); r.choice([1])  # keep stream aligned loosely
        roll = rng("fw_retry_roll", i).random()
        if roll >= 0.14:                 # only ~14% (failed/pending) get retried
            continue
        rr = rng("fw_retry", i)
        tid = hex_id(("fw_transfer", i), 9)
        attempts = rr.randint(1, 3)
        ts = rand_datetime(rr)
        for a in range(1, attempts + 1):
            final = (a == attempts)
            status = "SUCCESSFUL" if (final and rr.random() < 0.6) else r_status(rr, final)
            yield (
                rid, tid, a, status,
                f"NALA_{det_uuid(('fw_transfer', i))[:18]}_r{a}",
                str(rr.choice([0, 1, 2001])),
                rr.choice(["Transaction was successful", "DISABLED MMO ACCOUNT",
                           "Transaction is being processed"]),
                (ts + dt.timedelta(minutes=a * rr.randint(5, 60))).strftime("%Y-%m-%d %H:%M:%S"),
                json.dumps({"attempt": a, "status": status}),
            )
            rid += 1


def r_status(rr, final):
    return "FAILED" if rr.random() < 0.5 else "PENDING"


def gen_balances():
    rows = []
    start = dt.date(2023, 1, 1)
    end = dt.date(2026, 6, 18)
    days = (end - start).days
    bid = 1
    currencies = sorted({RECEIVE_MARKETS[c][0] for c in FW_COUNTRIES} | {"USD"})
    for d in range(0, days, 2):          # every 2 days
        day = start + dt.timedelta(days=d)
        for cur in currencies:
            r = rng("fw_bal", bid)
            ts = dt.datetime.combine(day, dt.time(r.randint(0, 6), r.randint(0, 59)))
            avail = round(r.uniform(1e4, 5e6) * (USD_FX.get(cur, 1.0)), 2)
            rows.append((
                bid, cur, avail, round(avail * r.uniform(1.0, 1.1), 2),
                ts_epoch_s(ts), json.dumps({"currency": cur}),
            ))
            bid += 1
    return rows


def gen_webhooks():
    """Webhook events for transfers — ~3% duplicate, some hash-invalid."""
    n = n_fw_transfers()
    wid = 1
    for i in range(n):
        r = rng("fw_transfer", i)
        country = r.choice(FW_COUNTRIES)
        r.choice(BANKS_BY_COUNTRY[country]); random_customer(r)
        cur = RECEIVE_MARKETS[country][0]
        ts = rand_datetime(r)
        amount = receive_amount(country, r)
        roll = r.random()
        if roll < 0.86:
            status = "SUCCESSFUL"
        elif roll < 0.95:
            status = r.choice(["FAILED", "QUEUED"])
        else:
            continue                     # pending: no terminal webhook yet
        tid = hex_id(("fw_transfer", i), 9)
        wr = rng("fw_wh", i)
        recv = ts + dt.timedelta(seconds=wr.randint(1, 120))
        dup = wr.random() < 0.03
        payload = {"event": "transfer.completed",
                   "data": {"id": tid, "status": status, "amount": amount, "currency": cur}}
        row = (
            wid, "transfer.completed", "Transfer", tid,
            f"NALA_{det_uuid(('fw_transfer', i))[:18]}", status,
            wr.random() < 0.97,                        # verif_hash_valid
            recv.strftime("%Y-%m-%dT%H:%M:%S"),        # naive ISO, no tz
            dup, json.dumps(payload),
        )
        yield row
        wid += 1
        if dup:
            yield (wid,) + row[1:]
            wid += 1


def gen_settlements():
    """Weekly settlement batches per currency."""
    rows = []
    start = dt.date(2023, 1, 1)
    end = dt.date(2026, 6, 18)
    sid = 1
    currencies = sorted({RECEIVE_MARKETS[c][0] for c in FW_COUNTRIES})
    week = start
    while week < end:
        for cur in currencies:
            r = rng("fw_settle", sid)
            if r.random() < 0.3:         # not every currency settles every week
                sid += 1
                continue
            gross = round(r.uniform(1e4, 2e6) * USD_FX.get(cur, 1.0), 2)
            app_fee = round(gross * r.uniform(0.005, 0.015), 2)
            merch_fee = round(gross * r.uniform(0.0, 0.005), 2)
            chargeback = round(gross * r.uniform(0.0, 0.002), 2) if r.random() < 0.1 else 0.0
            net = round(gross - app_fee - merch_fee - chargeback, 2)
            completed = r.random() < 0.92
            settled_ts = dt.datetime.combine(week + dt.timedelta(days=2), dt.time(9, 0))
            rows.append((
                sid, f"SETTLE-{cur}-{week.isoformat()}", cur, gross, app_fee,
                merch_fee, chargeback, net, r.randint(5, 500),
                "completed" if completed else "pending",
                (week + dt.timedelta(days=2)),
                settled_ts.strftime("%Y-%m-%d %H:%M:%S") if completed else None,
                json.dumps({"reference": f"SETTLE-{cur}-{week.isoformat()}"}),
            ))
            sid += 1
        week += dt.timedelta(days=7)
    return rows


# ---------------------------------------------------------------------
def main(conn):
    ensure_schema(conn, SCHEMA)
    apply_ddl_file(conn, DDL)
    truncate(conn, *TABLES)

    n = bulk_copy(conn, f"{SCHEMA}.banks",
        ["id","code","name","country","currency","is_mobile_money","created_at"],
        gen_banks())
    print(f"  banks: {n}")

    n = bulk_copy(conn, f"{SCHEMA}.beneficiaries", [
        "id","account_number","account_bank","bank_name","full_name","beneficiary_name",
        "email","mobilenumber","currency","country","nala_customer_code",
        "nala_recipient_uuid","is_deleted","meta","created_at",
    ], gen_beneficiaries())
    print(f"  beneficiaries: {n}")

    n = bulk_copy(conn, f"{SCHEMA}.transfers", [
        "id","reference","account_number","bank_code","bank_name","fullname","amount",
        "fee","currency","narration","status","complete_message","requires_approval",
        "is_approved","bank_reference","meta","beneficiary_id","nala_transfer_id",
        "nala_customer_code","recipient_phone","debit_currency","created_at",
        "date_created","raw_payload",
    ], gen_transfers())
    print(f"  transfers: {n}")

    n = bulk_copy(conn, f"{SCHEMA}.transfer_retries", [
        "id","transfer_id","attempt_number","status","reference","response_code",
        "response_message","retried_at","raw_payload",
    ], gen_transfer_retries())
    print(f"  transfer_retries: {n}")

    n = bulk_copy(conn, f"{SCHEMA}.balances", [
        "balance_id","currency","available_balance","ledger_balance","snapshot_at",
        "raw_payload",
    ], gen_balances())
    print(f"  balances: {n}")

    n = bulk_copy(conn, f"{SCHEMA}.webhooks", [
        "webhook_id","event","event_type","transfer_id","reference","status",
        "verif_hash_valid","received_at","is_duplicate","payload",
    ], gen_webhooks())
    print(f"  webhooks: {n}")

    n = bulk_copy(conn, f"{SCHEMA}.settlements", [
        "id","settlement_reference","currency","gross_amount","app_fee","merchant_fee",
        "chargeback_amount","net_amount","transfer_count","status","due_date",
        "settled_at","raw_payload",
    ], gen_settlements())
    print(f"  settlements: {n}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
    print("raw_flutterwave: done")
