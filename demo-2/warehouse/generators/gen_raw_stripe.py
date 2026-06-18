"""
gen_raw_stripe — Domain 6 (Funding & Banking Rails): raw_stripe schema.

Authentic Stripe API style: ch_/pi_/cus_/po_/re_/dp_/txn_/pm_/evt_ ids,
`created` as epoch SECONDS (bigint), amounts in MINOR units (cents, integer),
`metadata` jsonb. Models how NALA app users FUND their transfers via card/debit.

Idempotent: ensure schema -> apply DDL -> truncate -> load.
"""
from __future__ import annotations

import json
import datetime as dt

from common import (
    connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    customer_master, rng, rand_datetime, det_uuid, maybe_null,
    dirty_email, dirty_phone, ts_epoch_s, N,
)

DDL = "sql/ddl/raw_stripe.sql"

# Roughly: a subset of NALA customers fund via Stripe (card). Size off customers.
N_CUSTOMERS = max(50, int(N["customers"] * 0.55))
# Each funding customer makes a handful of card top-ups; scale off transfers.
N_INTENTS = max(200, int(N["transfers"] * 0.30))

CARD_BRANDS = ["visa", "mastercard", "amex", "discover"]
CARD_BINS = {"visa": "453201", "mastercard": "552012", "amex": "371449", "discover": "601100"}
FUNDING = ["debit", "credit", "prepaid"]
SEND_CCY = ["gbp", "usd", "eur"]  # lowercase per Stripe
INTENT_STATUS = (["succeeded"] * 80 + ["requires_payment_method"] * 8 +
                 ["processing"] * 5 + ["canceled"] * 5 + ["requires_capture"] * 2)
CHARGE_STATUS = ["succeeded"] * 85 + ["failed"] * 10 + ["pending"] * 3 + ["paid"] * 2  # 'paid' legacy
FAIL_CODES = ["card_declined", "insufficient_funds", "expired_card", "incorrect_cvc",
              "processing_error", "do_not_honor"]


def _epoch(d):
    return ts_epoch_s(d)


# --------------------------------------------------------------------------
def gen_customers():
    cm = customer_master()
    for k in range(N_CUSTOMERS):
        c = cm[k % len(cm)]
        r = rng("stripe_cus", k)
        cus_id = "cus_" + det_uuid(("stripe_cus", k)).replace("-", "")[:14]
        created = rand_datetime(r, start=c_signup_date(c), end=dt.date(2026, 6, 18))
        deleted = r.random() < 0.03
        yield (
            cus_id, "customer", _epoch(created),
            maybe_null(dirty_email(c.email, r), 0.06, r),
            f"{c.first} {c.last}",
            maybe_null(dirty_phone(c.phone, r), 0.15, r),
            maybe_null(f"NALA app user {c.code}", 0.4, r),
            r.choice(SEND_CCY),
            r.random() < 0.02,                      # delinquent
            True,                                   # livemode
            c.code,                                 # nala_customer_code
            maybe_null("card_" + det_uuid(("stripe_src", k)).replace("-", "")[:14], 0.5, r),
            "NALA" + str(r.randint(1000, 9999)),
            deleted,
            _epoch(rand_datetime(r, start=created.date(), end=dt.date(2026, 6, 18))) if deleted else None,
            json.dumps({"nala_cid": c.cid, "platform": c.platform}),
        )


def c_signup_date(c):
    # Customer.signup_at is a datetime; clamp to a date for range start.
    return c.signup_at.date() if isinstance(c.signup_at, dt.datetime) else dt.date(2018, 1, 1)


def gen_payment_methods():
    cm = customer_master()
    for k in range(N_CUSTOMERS):
        c = cm[k % len(cm)]
        r = rng("stripe_pm", k)
        n_pm = r.choice([1, 1, 1, 2])
        cus_id = "cus_" + det_uuid(("stripe_cus", k)).replace("-", "")[:14]
        for j in range(n_pm):
            rj = rng("stripe_pm", k, j)
            pm_id = "pm_" + det_uuid(("stripe_pm", k, j)).replace("-", "")[:24]
            ptype = "card" if rj.random() < 0.9 else rj.choice(["us_bank_account", "link"])
            created = rand_datetime(rj, start=c_signup_date(c), end=dt.date(2026, 6, 18))
            if ptype == "card":
                brand = rj.choice(CARD_BRANDS)
                last4 = f"{rj.randint(0, 9999):04d}"
                bin_ = CARD_BINS[brand]
                exp_y = rj.randint(2026, 2031)
                yield (
                    pm_id, "payment_method", _epoch(created), cus_id, ptype,
                    brand, last4, bin_, rj.randint(1, 12), exp_y,
                    rj.choice(FUNDING), c.country,
                    "fp_" + det_uuid(("stripe_fp", brand, last4)).replace("-", "")[:16],
                    maybe_null(dirty_email(c.email, rj), 0.5, rj),
                    True, json.dumps({"nala_customer_code": c.code}),
                )
            else:
                yield (
                    pm_id, "payment_method", _epoch(created), cus_id, ptype,
                    None, maybe_null(f"{rj.randint(0,9999):04d}", 0.2, rj), None, None, None,
                    None, c.country, None,
                    maybe_null(dirty_email(c.email, rj), 0.5, rj),
                    True, json.dumps({"nala_customer_code": c.code}),
                )


# A subset of transfer ids exists; reference a random portion (dirty/uuid).
def _transfer_uuid(r):
    if r.random() < 0.7:
        i = r.randrange(N["transfers"])
        return det_uuid(("transfer", i))
    return None


def gen_intents_charges_etc():
    """Stream payment_intents and emit linked charges/refunds/disputes/
    balance_txns/payouts/events. We yield via shared lists collected in main."""
    raise NotImplementedError  # handled inline in main for cross-table linkage


def main(conn):
    ensure_schema(conn, "raw_stripe")
    apply_ddl_file(conn, DDL)
    truncate(conn,
             "raw_stripe.customers", "raw_stripe.payment_methods",
             "raw_stripe.payment_intents", "raw_stripe.charges",
             "raw_stripe.refunds", "raw_stripe.disputes",
             "raw_stripe.payouts", "raw_stripe.balance_transactions",
             "raw_stripe.events")

    bulk_copy(conn, "raw_stripe.customers", [
        "id", "object", "created", "email", "name", "phone", "description",
        "currency", "delinquent", "livemode", "nala_customer_code",
        "default_source", "invoice_prefix", "deleted", "deleted_at", "metadata",
    ], gen_customers())

    bulk_copy(conn, "raw_stripe.payment_methods", [
        "id", "object", "created", "customer", "type", "card_brand", "card_last4",
        "card_bin", "card_exp_month", "card_exp_year", "card_funding",
        "card_country", "card_fingerprint", "billing_email", "livemode", "metadata",
    ], gen_payment_methods())

    cm = customer_master()
    cols_pi = ["id", "object", "created", "amount", "amount_received", "currency",
               "status", "customer", "payment_method", "latest_charge",
               "capture_method", "confirmation_method", "description",
               "statement_descriptor", "nala_transfer_id", "canceled_at",
               "cancellation_reason", "metadata"]
    cols_ch = ["id", "object", "created", "amount", "amount_captured",
               "amount_refunded", "currency", "status", "paid", "captured",
               "refunded", "disputed", "customer", "payment_intent",
               "payment_method", "balance_transaction", "card_brand", "card_last4",
               "card_funding", "card_country", "receipt_email", "failure_code",
               "failure_message", "outcome_type", "risk_level", "livemode", "metadata"]
    cols_re = ["id", "object", "created", "amount", "currency", "charge",
               "payment_intent", "balance_transaction", "reason", "status",
               "receipt_number", "metadata"]
    cols_dp = ["id", "object", "created", "amount", "currency", "charge",
               "payment_intent", "balance_transaction", "reason", "status",
               "is_charge_refundable", "evidence_due_by", "metadata"]
    cols_bt = ["id", "object", "created", "available_on", "amount", "net", "fee",
               "currency", "type", "status", "source", "reporting_category",
               "description"]
    cols_ev = ["id", "object", "created", "type", "api_version", "livemode",
               "request_id", "object_id", "data"]
    cols_po = ["id", "object", "created", "arrival_date", "amount", "currency",
               "status", "type", "method", "destination", "bank_name",
               "bank_last4", "statement_descriptor", "failure_code", "automatic",
               "metadata"]

    pi_rows, ch_rows, re_rows, dp_rows, bt_rows, ev_rows = [], [], [], [], [], []

    DISPUTE_REASON = ["fraudulent", "product_not_received", "duplicate",
                      "subscription_canceled", "unrecognized"]
    DISPUTE_STATUS = (["warning_needs_response"] * 1 + ["needs_response"] * 3 +
                      ["under_review"] * 2 + ["won"] * 2 + ["lost"] * 2)
    REFUND_REASON = ["requested_by_customer", "duplicate", "fraudulent"]

    for i in range(N_INTENTS):
        r = rng("stripe_pi", i)
        cust = cm[r.randrange(len(cm))]
        cus_k = cust.cid % N_CUSTOMERS
        cus_id = "cus_" + det_uuid(("stripe_cus", cus_k)).replace("-", "")[:14]
        pm_id = "pm_" + det_uuid(("stripe_pm", cus_k, 0)).replace("-", "")[:24]
        pi_id = "pi_" + det_uuid(("stripe_pi", i)).replace("-", "")[:24]
        ch_id = "ch_" + det_uuid(("stripe_ch", i)).replace("-", "")[:24]
        ccy = r.choice(SEND_CCY)
        # Transfers up to ~5000 in major units; minor = *100.
        amount_major = r.randint(5, 5000)
        amount = amount_major * 100  # MINOR units (cents)
        created = rand_datetime(r)
        pi_status = r.choice(INTENT_STATUS)
        ch_status = "succeeded" if pi_status == "succeeded" else (
            "pending" if pi_status == "processing" else r.choice(CHARGE_STATUS))
        brand = r.choice(CARD_BRANDS)
        last4 = f"{r.randint(0, 9999):04d}"
        funding = r.choice(FUNDING)
        succeeded = ch_status in ("succeeded", "paid")
        txn_id = "txn_" + det_uuid(("stripe_bt", i)).replace("-", "")[:24] if succeeded else None
        ttransfer = _transfer_uuid(r)

        canceled = pi_status == "canceled"
        pi_rows.append((
            pi_id, "payment_intent", _epoch(created), amount,
            amount if succeeded else 0, ccy, pi_status, cus_id, pm_id,
            ch_id if succeeded or ch_status in ("failed", "pending") else None,
            "automatic", "automatic",
            maybe_null("NALA transfer funding", 0.3, r),
            "NALA",
            ttransfer if r.random() < 0.85 else (ttransfer.upper() if ttransfer else None),
            _epoch(created + dt.timedelta(minutes=r.randint(1, 120))) if canceled else None,
            r.choice(["requested_by_customer", "abandoned", "failed_invoice"]) if canceled else None,
            json.dumps({"nala_customer_code": cust.code}),
        ))

        fail = (None, None) if succeeded else (
            r.choice(FAIL_CODES), "Your card was declined.")
        disputed = succeeded and r.random() < 0.012
        amount_refunded = 0
        if succeeded and r.random() < 0.05:
            amount_refunded = amount if r.random() < 0.4 else amount_major * 100 // 2

        ch_rows.append((
            ch_id, "charge", _epoch(created), amount,
            amount if succeeded else 0, amount_refunded, ccy, ch_status,
            succeeded, succeeded, amount_refunded > 0, disputed,
            cus_id, pi_id, pm_id, txn_id, brand, last4, funding, cust.country,
            maybe_null(dirty_email(cust.email, r), 0.3, r),
            fail[0], fail[1],
            "authorized" if succeeded else "issuer_declined",
            r.choice(["normal"] * 9 + ["elevated"]),
            True, json.dumps({"nala_customer_code": cust.code}),
        ))

        if succeeded:
            fee = max(20, int(amount * 0.014) + 20)  # ~1.4% + 20c, minor units
            bt_rows.append((
                txn_id, "balance_transaction", _epoch(created),
                _epoch(created + dt.timedelta(days=2)), amount, amount - fee, fee,
                ccy, "charge", "available", ch_id, "charge", "NALA card funding",
            ))

        if amount_refunded > 0:
            rr = rng("stripe_re", i)
            re_id = "re_" + det_uuid(("stripe_re", i)).replace("-", "")[:24]
            re_txn = "txn_" + det_uuid(("stripe_bt_re", i)).replace("-", "")[:24]
            r_created = created + dt.timedelta(days=rr.randint(1, 30))
            re_rows.append((
                re_id, "refund", _epoch(r_created), amount_refunded, ccy, ch_id,
                pi_id, re_txn, rr.choice(REFUND_REASON), "succeeded",
                "rcpt_" + str(rr.randint(1000000, 9999999)),
                json.dumps({}),
            ))
            bt_rows.append((
                re_txn, "balance_transaction", _epoch(r_created),
                _epoch(r_created), -amount_refunded, -amount_refunded, 0, ccy,
                "refund", "available", re_id, "refund", "Refund",
            ))

        if disputed:
            dr = rng("stripe_dp", i)
            dp_id = "dp_" + det_uuid(("stripe_dp", i)).replace("-", "")[:24]
            dp_txn = "txn_" + det_uuid(("stripe_bt_dp", i)).replace("-", "")[:24]
            d_created = created + dt.timedelta(days=dr.randint(2, 45))
            dp_rows.append((
                dp_id, "dispute", _epoch(d_created), amount, ccy, ch_id, pi_id,
                dp_txn, dr.choice(DISPUTE_REASON), dr.choice(DISPUTE_STATUS),
                dr.random() < 0.5,
                _epoch(d_created + dt.timedelta(days=7)),
                json.dumps({}),
            ))

        # An event per intent creation + charge outcome.
        ev_rows.append((
            "evt_" + det_uuid(("stripe_ev", i, "pi")).replace("-", "")[:24],
            "event", _epoch(created), "payment_intent.created",
            r.choice(["2022-11-15", "2023-10-16", "2024-06-20"]), True,
            maybe_null("req_" + det_uuid(("stripe_req", i)).replace("-", "")[:14], 0.2, r),
            pi_id, json.dumps({"id": pi_id, "amount": amount, "currency": ccy}),
        ))
        ev_rows.append((
            "evt_" + det_uuid(("stripe_ev", i, "ch")).replace("-", "")[:24],
            "event", _epoch(created), f"charge.{'succeeded' if succeeded else 'failed'}",
            r.choice(["2022-11-15", "2023-10-16", "2024-06-20"]), True,
            maybe_null("req_" + det_uuid(("stripe_req2", i)).replace("-", "")[:14], 0.2, r),
            ch_id, json.dumps({"id": ch_id, "status": ch_status}),
        ))

        if len(pi_rows) >= 20000:
            bulk_copy(conn, "raw_stripe.payment_intents", cols_pi, pi_rows); pi_rows.clear()
            bulk_copy(conn, "raw_stripe.charges", cols_ch, ch_rows); ch_rows.clear()
            if re_rows: bulk_copy(conn, "raw_stripe.refunds", cols_re, re_rows); re_rows.clear()
            if dp_rows: bulk_copy(conn, "raw_stripe.disputes", cols_dp, dp_rows); dp_rows.clear()
            bulk_copy(conn, "raw_stripe.balance_transactions", cols_bt, bt_rows); bt_rows.clear()
            bulk_copy(conn, "raw_stripe.events", cols_ev, ev_rows); ev_rows.clear()

    if pi_rows: bulk_copy(conn, "raw_stripe.payment_intents", cols_pi, pi_rows)
    if ch_rows: bulk_copy(conn, "raw_stripe.charges", cols_ch, ch_rows)
    if re_rows: bulk_copy(conn, "raw_stripe.refunds", cols_re, re_rows)
    if dp_rows: bulk_copy(conn, "raw_stripe.disputes", cols_dp, dp_rows)
    if bt_rows: bulk_copy(conn, "raw_stripe.balance_transactions", cols_bt, bt_rows)
    if ev_rows: bulk_copy(conn, "raw_stripe.events", cols_ev, ev_rows)

    # Payouts: NALA's Stripe balance settling to its bank (program-level, not per-customer).
    n_payouts = max(20, N_INTENTS // 300)
    PO_STATUS = ["paid"] * 88 + ["in_transit"] * 5 + ["pending"] * 4 + ["failed"] * 2 + ["canceled"]
    payouts = []
    for i in range(n_payouts):
        r = rng("stripe_po", i)
        created = rand_datetime(r)
        ccy = r.choice(SEND_CCY)
        status = r.choice(PO_STATUS)
        payouts.append((
            "po_" + det_uuid(("stripe_po", i)).replace("-", "")[:24], "payout",
            _epoch(created), _epoch(created + dt.timedelta(days=r.randint(1, 3))),
            r.randint(10000, 50000000), ccy, status, "bank_account",
            r.choice(["standard"] * 9 + ["instant"]),
            "ba_" + det_uuid(("stripe_ba", i % 4)).replace("-", "")[:18],
            r.choice(["JPMORGAN CHASE", "Barclays", "Citibank", "Deutsche Bank"]),
            f"{r.randint(0, 9999):04d}", "NALA PAYOUT",
            r.choice(FAIL_CODES) if status == "failed" else None,
            True, json.dumps({"program": "nala"}),
        ))
    bulk_copy(conn, "raw_stripe.payouts", cols_po, payouts)

    with conn.cursor() as cur:
        for t in ("customers", "payment_methods", "payment_intents", "charges",
                  "refunds", "disputes", "payouts", "balance_transactions", "events"):
            cur.execute(f"SELECT count(*) FROM raw_stripe.{t}")
            print(f"  raw_stripe.{t:22s} {cur.fetchone()[0]:>8d}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
