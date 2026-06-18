"""
gen_raw_circle — Circle API style (USDC wallets, transfers, payments, chargebacks).

Schema: raw_circle
Tables: usdc_wallets, usdc_transfers, usdc_payments, chargebacks.

Circle quirks reproduced:
  * id is a uuid; createDate/updateDate are ISO-Z STRINGS (stored as text).
  * transfer amount as a decimal STRING; payment amount as a number.
  * customer_ref is the dirty cross-source join key (CUS_...), often null.
  * card PII stored as last4 + bin only (governed), never the full PAN.

Idempotent: ensure schema -> apply DDL -> truncate -> load.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from common import (
    N, connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    customer_master, rng, rand_datetime, det_uuid, maybe_null,
    ts_isoz,
)

DDL = Path(__file__).resolve().parent.parent / "sql" / "ddl" / "raw_circle.sql"
SCHEMA = "raw_circle"

CHAINS = ["ETH", "MATIC", "SOL", "ALGO"]
CARD_NETWORKS = ["VISA", "MASTERCARD"]
BINS = {"VISA": ["453201", "414709", "424242"], "MASTERCARD": ["555544", "521729", "510510"]}
N_WALLETS = 250  # 1 merchant + customer end-user wallets


def hex_address(r):
    return "0x" + "".join(r.choice("0123456789abcdef") for _ in range(40))


def sol_address(r):
    b58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    return "".join(r.choice(b58) for _ in range(44))


def addr_for(r, chain):
    if chain == "SOL":
        return sol_address(r)
    if chain == "ALGO":
        return "".join(r.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567") for _ in range(58))
    return hex_address(r)


def tx_hash(r, chain):
    if chain == "SOL":
        return sol_address(r) + sol_address(r)[:44]
    return "0x" + "".join(r.choice("0123456789abcdef") for _ in range(64))


def build_wallets():
    rows = []
    wallet_ids = []   # (wallet_id, type)
    cust = customer_master()
    r = rng("circle", "wallets")

    # 1 merchant wallet (NALA's own collection wallet).
    merchant_id = "1000000001"
    rows.append((
        merchant_id, "merchant", "NALA Rafiki merchant wallet", None,
        round(r.uniform(100_000, 5_000_000), 6), None, None, None,
        ts_isoz(rand_datetime(r, start=dt.date(2021, 1, 1))), None,
        json.dumps({"type": "merchant"}),
    ))
    wallet_ids.append((merchant_id, "merchant"))

    chosen = r.sample(range(N["customers"]), min(N_WALLETS - 1, N["customers"]))
    wid = 1000100001
    for cid in chosen:
        c = cust[cid]
        wr = rng("circle", "wallet", cid)
        chain = wr.choice(CHAINS)
        hosted = wr.random() < 0.4
        created = rand_datetime(wr, start=dt.date(2022, 1, 1))
        rows.append((
            str(wid), "end_user_wallet", f"USDC wallet {c.code}",
            maybe_null(c.code, 0.12, wr),   # dirty: ~12% missing customer ref
            round(wr.uniform(0, 20_000), 6),
            None if hosted else chain,
            None if hosted else addr_for(wr, chain),
            maybe_null(str(wr.randint(100000, 999999)), 0.9, wr),  # address_tag rarely set
            ts_isoz(created),
            maybe_null(ts_isoz(created + dt.timedelta(days=wr.randint(0, 200))), 0.4, wr),
            json.dumps({"type": "end_user_wallet", "customerRef": c.code}),
        ))
        wallet_ids.append((str(wid), "end_user_wallet"))
        wid += 1
    return rows, wallet_ids, merchant_id


def gen_transfers(wallet_ids):
    n_target = max(300, N["transfers"] // 10)
    for i in range(n_target):
        r = rng("circle", "transfer", i)
        src_wallet, _ = r.choice(wallet_ids)
        src_from_blockchain = r.random() < 0.25
        dest_blockchain = r.random() < 0.5
        chain = r.choice(CHAINS)
        amount = round(r.uniform(1, 100_000), 6)
        status = r.choices(["complete", "pending", "failed"], weights=[88, 8, 4])[0]
        created = rand_datetime(r, start=dt.date(2022, 1, 1))
        yield (
            det_uuid(("circle_tx", i)),
            None if src_from_blockchain else src_wallet,
            "blockchain" if src_from_blockchain else "wallet",
            "blockchain" if dest_blockchain else "wallet",
            addr_for(r, chain) if dest_blockchain else None,
            chain if dest_blockchain else None,
            f"{amount:.6f}", "USD",
            tx_hash(r, chain) if status == "complete" else None,
            status,
            maybe_null("transfer_failed", 0.0, r) if status == "failed" else None,
            maybe_null(det_uuid(("settlement", r.randrange(max(1, N["transfers"] // 50)))), 0.4, r),
            ts_isoz(created),
            maybe_null(ts_isoz(created + dt.timedelta(minutes=r.randint(1, 240))), 0.2, r),
            json.dumps({"status": status}),
        )


def gen_payments(merchant_id):
    """FACT-ish: card/ACH funding payments. Returns rows + list of (payment_id,
    merchant_wallet_id, amount, currency, create_date) eligible for chargebacks."""
    rows = []
    paid_card = []   # for chargeback linkage
    cust = customer_master()
    n_target = max(400, N["transfers"] // 8)
    for i in range(n_target):
        r = rng("circle", "payment", i)
        ptype = r.choices(["payment", "refund"], weights=[94, 6])[0]
        c = cust[r.randrange(N["customers"])]
        source = r.choices(["card", "ach", "wire", "blockchain"], weights=[55, 25, 10, 10])[0]
        ccy = r.choice(["USD", "EUR", "GBP"])
        amount = round(r.uniform(5, 8000), 2)
        status = r.choices(["paid", "confirmed", "pending", "failed", "refunded"],
                           weights=[55, 25, 8, 7, 5])[0]
        created = rand_datetime(r, start=dt.date(2022, 1, 1))
        net = CARD_NETWORKS and r.choice(CARD_NETWORKS)
        is_card = source == "card"
        last4 = f"{r.randint(0, 9999):04d}" if is_card else None
        binv = r.choice(BINS[net]) if is_card else None
        pid = det_uuid(("circle_pay", i))
        rows.append((
            pid, ptype, merchant_id, maybe_null(c.code, 0.10, r),
            amount, ccy, source,
            last4, binv, net if is_card else None,
            status, maybe_null(r.randint(0, 100), 0.15, r),
            round(amount * r.uniform(0.005, 0.03), 2),
            f"{ptype} via {source}",
            ts_isoz(created),
            maybe_null(ts_isoz(created + dt.timedelta(minutes=r.randint(1, 120))), 0.2, r),
            json.dumps({"sourceType": source}),
        ))
        if is_card and status in ("paid", "confirmed") and ptype == "payment":
            paid_card.append((pid, merchant_id, amount, ccy, created))
    return rows, paid_card


def gen_chargebacks(paid_card):
    rows = []
    r0 = rng("circle", "chargebacks")
    # ~1.5% of paid card payments get a chargeback.
    sample = [p for p in paid_card if rng("circle", "cb_flag", p[0]).random() < 0.015]
    cats = ["Fraudulent", "Authorization", "Processing Error", "Consumer Dispute"]
    reason_codes = ["10.4", "10.1", "13.1", "13.3", "12.5", "4853"]
    for i, (pid, mwid, amount, ccy, created) in enumerate(sample):
        r = rng("circle", "cb", i)
        status = r.choices(["pending", "under_review", "won", "lost"],
                           weights=[15, 25, 35, 25])[0]
        opened = created + dt.timedelta(days=r.randint(2, 90))
        rows.append((
            det_uuid(("circle_cb", i)), pid, mwid,
            round(amount, 2), ccy,
            r.choice(cats), status, r.choice(reason_codes),
            ts_isoz(opened),
            ts_isoz(opened + dt.timedelta(days=r.randint(5, 45))) if status in ("won", "lost") else None,
            json.dumps({"category": r.choice(cats)}),
        ))
    return rows


def main(conn):
    ensure_schema(conn, SCHEMA)
    apply_ddl_file(conn, DDL)
    truncate(conn,
             f"{SCHEMA}.chargebacks",
             f"{SCHEMA}.usdc_payments",
             f"{SCHEMA}.usdc_transfers",
             f"{SCHEMA}.usdc_wallets")

    wallet_rows, wallet_ids, merchant_id = build_wallets()
    bulk_copy(conn, f"{SCHEMA}.usdc_wallets",
              ["wallet_id", "type", "description", "customer_ref", "balance_usdc",
               "chain", "address", "address_tag", "create_date", "update_date",
               "raw_payload"], wallet_rows)

    nt = bulk_copy(conn, f"{SCHEMA}.usdc_transfers",
              ["id", "source_wallet_id", "source_type", "dest_type", "dest_address",
               "dest_chain", "amount", "currency", "tx_hash", "status", "error_code",
               "reference_id", "create_date", "update_date", "raw_payload"],
              gen_transfers(wallet_ids))

    payment_rows, paid_card = gen_payments(merchant_id)
    bulk_copy(conn, f"{SCHEMA}.usdc_payments",
              ["id", "type", "merchant_wallet_id", "customer_ref", "amount",
               "currency", "source_type", "card_last4", "card_bin", "card_network",
               "status", "risk_score", "fees", "description", "create_date",
               "update_date", "raw_payload"], payment_rows)

    cb_rows = gen_chargebacks(paid_card)
    bulk_copy(conn, f"{SCHEMA}.chargebacks",
              ["id", "payment_id", "merchant_wallet_id", "amount", "currency",
               "category", "status", "reason_code", "create_date", "resolved_date",
               "raw_payload"], cb_rows)

    print(f"[{SCHEMA}] usdc_wallets={len(wallet_rows)} usdc_transfers={nt} "
          f"usdc_payments={len(payment_rows)} chargebacks={len(cb_rows)}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
