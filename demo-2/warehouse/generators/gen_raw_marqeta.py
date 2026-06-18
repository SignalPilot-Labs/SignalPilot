"""
gen_raw_marqeta — Domain 6 (Funding & Banking Rails): raw_marqeta schema.

NALA issues its own cards via Marqeta (multi-currency wallet / spend product).
Marqeta style: uuid-ish `token` on every object, ISO-8601 WITH OFFSET string
timestamps, amounts in MAJOR units. PII: cardholder name/email/phone, card
last_four, pan_token (NEVER full PAN).

Idempotent: ensure schema -> apply DDL -> truncate -> load.
"""
from __future__ import annotations

import datetime as dt

from common import (
    connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    customer_master, rng, rand_datetime, det_uuid, maybe_null,
    dirty_email, dirty_phone, N,
)

DDL = "sql/ddl/raw_marqeta.sql"

# A subset of NALA customers hold a Marqeta-issued card.
N_CUSTOMERS = max(40, int(N["customers"] * 0.30))
TXN_PER_CARD = (1, 12)

CH_STATUS = ["ACTIVE"] * 82 + ["SUSPENDED"] * 8 + ["UNVERIFIED"] * 7 + ["LIMITED"] * 3
CARD_STATE = ["ACTIVE"] * 80 + ["SUSPENDED"] * 6 + ["TERMINATED"] * 6 + ["UNACTIVATED"] * 8
NETWORK = ["VISA", "MASTERCARD", "PULSE", "MAESTRO"]
TXN_TYPE = (["authorization"] * 30 + ["authorization.clearing"] * 50 +
            ["refund"] * 8 + ["authorization.reversal"] * 7 + ["pindebit"] * 5)
TXN_STATE = ["CLEARED"] * 70 + ["COMPLETION"] * 12 + ["PENDING"] * 8 + ["DECLINED"] * 8 + ["ERROR"] * 2
MCCS = [("5411", "Grocery"), ("5812", "Restaurants"), ("4814", "Telecom"),
        ("5999", "Retail"), ("6011", "ATM"), ("4900", "Utilities")]
MERCHANTS = ["TESCO STORES", "UBER BV", "AMAZON EU", "SHELL", "NALA TOPUP",
             "STARBUCKS", "MTN MOMO", "SAFARICOM"]


def isooff(d):
    return d.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def signup_date(c):
    return c.signup_at.date() if isinstance(c.signup_at, dt.datetime) else dt.date(2018, 1, 1)


def gen_cardholders():
    cm = customer_master()
    for k in range(N_CUSTOMERS):
        c = cm[k % len(cm)]
        r = rng("mq_ch", k)
        token = det_uuid(("mq_ch", k))
        created = rand_datetime(r, start=signup_date(c), end=dt.date(2026, 6, 18))
        modified = rand_datetime(r, start=created.date(), end=dt.date(2026, 6, 18))
        status = r.choice(CH_STATUS)
        yield (
            token, c.code, c.first, c.last,
            maybe_null(dirty_email(c.email, r), 0.05, r),
            maybe_null(dirty_phone(c.phone, r), 0.1, r),
            maybe_null(c.dob, 0.2, r),
            maybe_null(c.street, 0.1, r),
            maybe_null(c.city, 0.1, r),
            maybe_null(c.city, 0.5, r),
            maybe_null(c.postcode, 0.1, r),
            c.country,
            status == "ACTIVE", status,
            False, isooff(created), isooff(modified),
        )


def _ch_token(k):
    return det_uuid(("mq_ch", k))


def gen_cards():
    cm = customer_master()
    for k in range(N_CUSTOMERS):
        c = cm[k % len(cm)]
        r = rng("mq_card", k)
        n_card = r.choice([1, 1, 1, 2])
        for j in range(n_card):
            rj = rng("mq_card", k, j)
            token = det_uuid(("mq_card", k, j))
            state = rj.choice(CARD_STATE)
            instr = rj.choice(["VIRTUAL_PAN"] * 7 + ["PHYSICAL_MSR"] * 3)
            exp_m, exp_y = rj.randint(1, 12), rj.randint(26, 31)
            created = rand_datetime(rj, start=signup_date(c), end=dt.date(2026, 6, 18))
            yield (
                token, _ch_token(k),
                "nala_card_gbp" if c.currency == "GBP" else f"nala_card_{c.currency.lower()}",
                f"{rj.randint(0, 9999):04d}",
                "pan_" + det_uuid(("mq_pan", k, j)).replace("-", "")[:24],
                f"{exp_m:02d}{exp_y}",
                isooff(dt.datetime(2000 + exp_y, exp_m, 28)),
                maybe_null(str(rj.randint(10**11, 10**12)), 0.7, rj),
                rj.random() < 0.7,
                state,
                maybe_null(rj.choice(["customer_request", "fraud_hold", "expired"]),
                           0.8, rj) if state != "ACTIVE" else None,
                rj.choice(["ISSUED", "DIGITALLY_PRESENTED", "SHIPPED", "ORDERED"]),
                instr, isooff(created),
            )


def gen_funding_sources():
    cm = customer_master()
    # Program-level funding sources (NALA's GPA per currency).
    for idx, ccy in enumerate(["GBP", "USD", "EUR"]):
        r = rng("mq_fs_prog", idx)
        yield (
            det_uuid(("mq_fs_prog", ccy)), None, "program",
            f"NALA {ccy} Program Funding", None, None, True, True, ccy,
            isooff(dt.datetime(2021, 1, 1)),
        )
    # Per-cardholder GPA funding sources.
    for k in range(N_CUSTOMERS):
        c = cm[k % len(cm)]
        r = rng("mq_fs", k)
        created = rand_datetime(r, start=signup_date(c), end=dt.date(2026, 6, 18))
        yield (
            det_uuid(("mq_fs", k)), _ch_token(k), "gpa",
            f"{c.first} {c.last} Wallet",
            maybe_null(f"{c.first} {c.last}", 0.3, r),
            maybe_null(f"{r.randint(0, 9999):04d}", 0.6, r),
            True, True, c.currency, isooff(created),
        )


def gen_card_transactions():
    cm = customer_master()
    for k in range(N_CUSTOMERS):
        c = cm[k % len(cm)]
        r = rng("mq_txn", k)
        n_card = r.choice([1, 1, 1, 2])
        for j in range(n_card):
            card_token = det_uuid(("mq_card", k, j))
            n_txn = r.randint(*TXN_PER_CARD)
            for t in range(n_txn):
                rt = rng("mq_txn", k, j, t)
                token = det_uuid(("mq_txn", k, j, t))
                ttype = rt.choice(TXN_TYPE)
                state = rt.choice(TXN_STATE)
                declined = state in ("DECLINED", "ERROR")
                merch = rt.choice(MERCHANTS)
                mcc, _ = rt.choice(MCCS)
                amount = round(rt.uniform(1, 1200), 2)
                if ttype.startswith("refund") or ttype.endswith("reversal"):
                    amount = -amount
                txn_time = rand_datetime(rt, start=signup_date(c), end=dt.date(2026, 6, 18))
                ttransfer = None
                if merch == "NALA TOPUP" and rt.random() < 0.7:
                    i = rt.randrange(N["transfers"])
                    ttransfer = det_uuid(("transfer", i))
                    if rt.random() < 0.1:
                        ttransfer = ttransfer.upper()
                settled = not declined and state in ("CLEARED", "COMPLETION")
                yield (
                    token, ttype, state, _ch_token(k), card_token, amount,
                    c.currency,
                    maybe_null(f"{rt.randint(100000, 999999)}", 0.3, rt) if not declined else None,
                    "0000" if not declined else rt.choice(["1016", "1888", "5400"]),
                    "APPROVED" if not declined else "INSUFFICIENT FUNDS",
                    rt.choice(NETWORK),
                    str(rt.randint(100000000000, 999999999999)),
                    merch, mcc, rt.choice([c.country, "KE", "TZ", "NG", "GB", "US"]),
                    rt.random() < 0.1, ttransfer,
                    det_uuid(("mq_fs", k)),
                    isooff(txn_time),
                    (txn_time + dt.timedelta(days=rt.randint(0, 2))).date().isoformat() if settled else None,
                )


def main(conn):
    ensure_schema(conn, "raw_marqeta")
    apply_ddl_file(conn, DDL)
    truncate(conn, "raw_marqeta.cardholders", "raw_marqeta.cards",
             "raw_marqeta.card_transactions", "raw_marqeta.funding_sources")

    bulk_copy(conn, "raw_marqeta.cardholders", [
        "token", "nala_customer_code", "first_name", "last_name", "email",
        "phone", "birth_date", "address1", "city", "state", "postal_code",
        "country", "active", "status", "uses_parent_account", "created_time",
        "last_modified_time",
    ], gen_cardholders())

    bulk_copy(conn, "raw_marqeta.cards", [
        "token", "user_token", "card_product_token", "last_four", "pan_token",
        "expiration", "expiration_time", "barcode", "pin_is_set", "state",
        "state_reason", "fulfillment_status", "instrument_type", "created_time",
    ], gen_cards())

    bulk_copy(conn, "raw_marqeta.funding_sources", [
        "token", "user_token", "type", "name", "name_on_account",
        "account_suffix", "active", "is_default_account", "currency_code",
        "created_time",
    ], gen_funding_sources())

    bulk_copy(conn, "raw_marqeta.card_transactions", [
        "token", "type", "state", "user_token", "card_token", "amount",
        "currency_code", "approval_code", "response_code", "response_memo",
        "network", "acquirer_mid", "merchant_name", "mcc", "merchant_country",
        "is_recurring", "nala_transfer_id", "funding_source_token",
        "user_transaction_time", "settlement_date",
    ], gen_card_transactions())

    with conn.cursor() as cur:
        for t in ("cardholders", "cards", "card_transactions", "funding_sources"):
            cur.execute(f"SELECT count(*) FROM raw_marqeta.{t}")
            print(f"  raw_marqeta.{t:20s} {cur.fetchone()[0]:>8d}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
