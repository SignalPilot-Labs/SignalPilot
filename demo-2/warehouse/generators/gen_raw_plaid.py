"""
gen_raw_plaid — Domain 6 (Funding & Banking Rails): raw_plaid schema.

Plaid links a NALA user's external bank account (ACH debit funding + identity
verification). Plaid style: opaque item/account ids, ISO-8601 STRING timestamps
(not epoch), amounts/balances in MAJOR units. Heavy PII: account/routing
numbers, names, emails, phones, addresses.

Idempotent: ensure schema -> apply DDL -> truncate -> load.
"""
from __future__ import annotations

import json
import datetime as dt

from common import (
    connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    customer_master, rng, rand_datetime, det_uuid, maybe_null,
    dirty_email, dirty_phone, ts_isoz, N,
)

DDL = "sql/ddl/raw_plaid.sql"

# A subset of NALA customers link a bank via Plaid (mostly US/EU ACH funders).
N_CUSTOMERS = max(40, int(N["customers"] * 0.35))
# Transactions per linked account.
TXN_PER_ACCT = (2, 14)

INSTITUTIONS = [
    ("ins_109508", "Chase"), ("ins_56", "Wells Fargo"), ("ins_127989", "Bank of America"),
    ("ins_117650", "Barclays"), ("ins_118923", "Monzo"), ("ins_116236", "Revolut"),
    ("ins_133022", "HSBC"), ("ins_119019", "Citi"), ("ins_117181", "Lloyds"),
]
ITEM_STATUS = (["good"] * 80 + ["login_required"] * 8 + ["pending_expiration"] * 5 +
               ["ITEM_LOGIN_REQUIRED"] * 4 + ["good"] * 3)  # legacy enum mixed in
VERIF_STATUS = (["automatically_verified"] * 70 + ["manually_verified"] * 15 +
                ["pending_manual_verification"] * 10 + ["verification_expired"] * 5)
PFC = ["TRANSFER_OUT", "TRANSFER_IN", "GENERAL_MERCHANDISE", "FOOD_AND_DRINK",
       "TRAVEL", "BANK_FEES", "INCOME"]
LEGACY_CAT = ["Transfer,Debit", "Payment,Credit Card", "Food and Drink,Restaurants",
              "Travel,Airlines", "Bank Fees,Overdraft"]
MERCHANTS = ["NALA", "Uber", "Tesco", "Amazon", "Starbucks", "British Airways",
             "Shell", "ASDA", "Spotify"]


def iso(d):
    return ts_isoz(d)


def signup_date(c):
    return c.signup_at.date() if isinstance(c.signup_at, dt.datetime) else dt.date(2018, 1, 1)


def gen_items():
    cm = customer_master()
    for k in range(N_CUSTOMERS):
        c = cm[k % len(cm)]
        r = rng("plaid_item", k)
        inst_id, inst_name = r.choice(INSTITUTIONS)
        created = rand_datetime(r, start=signup_date(c), end=dt.date(2026, 6, 18))
        updated = rand_datetime(r, start=created.date(), end=dt.date(2026, 6, 18))
        status = r.choice(ITEM_STATUS)
        item_id = det_uuid(("plaid_item", k)).replace("-", "")
        yield (
            item_id, inst_id, inst_name, c.code,
            maybe_null(dirty_email(c.email, r), 0.1, r),
            "auth,transactions,identity", "auth,transactions",
            status,
            iso(created + dt.timedelta(days=90)) if status == "pending_expiration" else None,
            "ITEM_LOGIN_REQUIRED" if status in ("login_required", "ITEM_LOGIN_REQUIRED") else None,
            iso(created), iso(updated),
        )


def _item_id(k):
    return det_uuid(("plaid_item", k)).replace("-", "")


def gen_accounts():
    cm = customer_master()
    for k in range(N_CUSTOMERS):
        c = cm[k % len(cm)]
        r = rng("plaid_acct", k)
        item_id = _item_id(k)
        n_acct = r.choice([1, 1, 1, 2])
        for j in range(n_acct):
            rj = rng("plaid_acct", k, j)
            acct_id = det_uuid(("plaid_acct", k, j)).replace("-", "")
            subtype = rj.choice(["checking", "checking", "savings"])
            cur_bal = round(rj.uniform(50, 25000), 2)
            yield (
                acct_id, item_id,
                "Plaid Checking" if subtype == "checking" else "Plaid Saving",
                maybe_null(f"{c.first} {c.last} {subtype.title()}", 0.4, rj),
                f"{rj.randint(0, 9999):04d}",                 # mask (last4 PII)
                "depository", subtype,
                maybe_null(round(cur_bal * rj.uniform(0.8, 1.0), 2), 0.15, rj),
                cur_bal, c.currency,
                rj.choice(VERIF_STATUS),
                iso(rand_datetime(rj, start=signup_date(c), end=dt.date(2026, 6, 18))),
            )


def gen_auth_numbers():
    cm = customer_master()
    for k in range(N_CUSTOMERS):
        c = cm[k % len(cm)]
        r = rng("plaid_auth", k)
        item_id = _item_id(k)
        n_acct = r.choice([1, 1, 1, 2])
        for j in range(n_acct):
            rj = rng("plaid_auth", k, j)
            acct_id = det_uuid(("plaid_acct", k, j)).replace("-", "")
            if c.country == "US":
                routing = f"{rj.randint(11, 99)}{rj.randint(1000000, 9999999)}"
                acct = f"{rj.randint(10**9, 10**12 - 1)}"
                atype = "ach"
                wire = maybe_null(f"021{rj.randint(100000, 999999)}", 0.4, rj)
            else:
                routing = f"{rj.randint(100000, 999999)}"  # UK sort code style
                acct = f"{rj.randint(10000000, 99999999)}"
                atype = "international"
                wire = None
            yield (acct_id, item_id, routing, acct, wire, atype,
                   iso(rand_datetime(rj, start=signup_date(c), end=dt.date(2026, 6, 18))))


def gen_transactions():
    cm = customer_master()
    for k in range(N_CUSTOMERS):
        c = cm[k % len(cm)]
        r = rng("plaid_txn", k)
        item_id = _item_id(k)
        n_acct = r.choice([1, 1, 1, 2])
        for j in range(n_acct):
            acct_id = det_uuid(("plaid_acct", k, j)).replace("-", "")
            n_txn = r.randint(*TXN_PER_ACCT)
            for t in range(n_txn):
                rt = rng("plaid_txn", k, j, t)
                txn_id = det_uuid(("plaid_txn", k, j, t)).replace("-", "")
                is_nala = rt.random() < 0.4
                merch = "NALA" if is_nala else rt.choice(MERCHANTS)
                amount = round(rt.uniform(5, 5000), 2)  # positive = money OUT (Plaid sign)
                posted = rand_datetime(rt, start=signup_date(c), end=dt.date(2026, 6, 18))
                pending = rt.random() < 0.08
                ttransfer = None
                if is_nala and rt.random() < 0.8:
                    i = rt.randrange(N["transfers"])
                    ttransfer = det_uuid(("transfer", i))
                    if rt.random() < 0.1:
                        ttransfer = ttransfer.upper()  # dirty casing
                yield (
                    txn_id, acct_id, item_id, amount, c.currency,
                    posted.date().isoformat(),
                    maybe_null((posted - dt.timedelta(days=rt.randint(0, 2))).date().isoformat(), 0.3, rt),
                    f"{merch} {rt.choice(['PURCHASE', 'PMT', 'POS', 'DEBIT'])}",
                    maybe_null(merch, 0.25, rt),
                    rt.choice(["online", "in store", "other"]),
                    rt.choice(LEGACY_CAT),
                    "TRANSFER_OUT" if is_nala else rt.choice(PFC),
                    None if not pending else det_uuid(("plaid_txn", k, j, t, "pend")).replace("-", ""),
                    ttransfer,
                    iso(posted),
                )


def gen_identity():
    cm = customer_master()
    for k in range(N_CUSTOMERS):
        c = cm[k % len(cm)]
        r = rng("plaid_id", k)
        item_id = _item_id(k)
        acct_id = det_uuid(("plaid_acct", k, 0)).replace("-", "")
        emails = [c.email]
        if r.random() < 0.3:
            emails.append(c.email.replace("@", ".alt@"))
        yield (
            acct_id, item_id, c.code,
            f"{c.first} {c.last}",
            maybe_null(dirty_email(c.email, r), 0.05, r),
            maybe_null(dirty_phone(c.phone, r), 0.15, r),
            maybe_null(c.street, 0.1, r),
            maybe_null(c.city, 0.1, r),
            maybe_null(c.city, 0.5, r),  # region approx
            maybe_null(c.postcode, 0.1, r),
            c.country,
            json.dumps([{"data": e, "primary": (idx == 0)} for idx, e in enumerate(emails)]),
            iso(rand_datetime(r, start=signup_date(c), end=dt.date(2026, 6, 18))),
        )


def main(conn):
    ensure_schema(conn, "raw_plaid")
    apply_ddl_file(conn, DDL)
    truncate(conn, "raw_plaid.items", "raw_plaid.accounts",
             "raw_plaid.auth_numbers", "raw_plaid.transactions",
             "raw_plaid.identity_data")

    bulk_copy(conn, "raw_plaid.items", [
        "item_id", "institution_id", "institution_name", "nala_customer_code",
        "nala_customer_email", "available_products", "billed_products", "status",
        "consent_expiration_time", "error_code", "created_at", "updated_at",
    ], gen_items())

    bulk_copy(conn, "raw_plaid.accounts", [
        "account_id", "item_id", "name", "official_name", "mask", "type",
        "subtype", "available_balance", "current_balance", "iso_currency_code",
        "verification_status", "created_at",
    ], gen_accounts())

    bulk_copy(conn, "raw_plaid.auth_numbers", [
        "account_id", "item_id", "routing", "account", "wire_routing",
        "account_type", "created_at",
    ], gen_auth_numbers())

    bulk_copy(conn, "raw_plaid.transactions", [
        "transaction_id", "account_id", "item_id", "amount", "iso_currency_code",
        "date", "authorized_date", "name", "merchant_name", "payment_channel",
        "category", "personal_finance_category", "pending_transaction_id",
        "nala_transfer_id", "created_at",
    ], gen_transactions())

    # pending column is set independently; fix: transactions generator emits
    # pending_transaction_id but not the boolean. Add the boolean inline:
    # (handled below via UPDATE for simplicity / correctness)
    with conn.cursor() as cur:
        cur.execute("UPDATE raw_plaid.transactions SET pending = (pending_transaction_id IS NOT NULL)")
    conn.commit()

    bulk_copy(conn, "raw_plaid.identity_data", [
        "account_id", "item_id", "nala_customer_code", "full_name",
        "primary_email", "primary_phone", "street", "city", "region",
        "postal_code", "country", "emails_json", "created_at",
    ], gen_identity())

    with conn.cursor() as cur:
        for t in ("items", "accounts", "auth_numbers", "transactions", "identity_data"):
            cur.execute(f"SELECT count(*) FROM raw_plaid.{t}")
            print(f"  raw_plaid.{t:18s} {cur.fetchone()[0]:>8d}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
