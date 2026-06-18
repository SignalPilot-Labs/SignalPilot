"""
gen_raw_ledger — NALA internal double-entry general ledger + treasury wallets.

Schema: raw_ledger
Tables: account_types, accounts, journal_entries, journal_lines (FACT),
        wallets, wallet_transactions, balance_snapshots, reconciliation_runs,
        reconciliation_breaks.

Double-entry invariant: for every journal_entry, sum(debit lines) == sum(credit
lines). Enforced by construction in gen_journal().

Idempotent: ensure schema -> apply DDL -> truncate -> load.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from common import (
    N, connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    customer_master, rng, rand_datetime, det_uuid, maybe_null,
    ts_iso, STABLECOINS, EPOCH_END,
)

DDL = Path(__file__).resolve().parent.parent / "sql" / "ddl" / "raw_ledger.sql"
SCHEMA = "raw_ledger"

CHAINS = ["ethereum", "polygon", "solana"]
FIAT = ["USD", "GBP", "EUR", "KES", "NGN", "TZS", "UGX"]
ALL_CCY = FIAT + STABLECOINS

# --------------------------------------------------------------------------
# Account types (lookup) + chart of accounts
# --------------------------------------------------------------------------
ACCOUNT_TYPES = [
    (1, "ASSET",     "Assets",      "DEBIT",  "Cash, custody, receivables"),
    (2, "LIABILITY", "Liabilities", "CREDIT", "Customer balances payable, fees collected"),
    (3, "EQUITY",    "Equity",      "CREDIT", "Retained earnings, contributed capital"),
    (4, "REVENUE",   "Revenue",     "CREDIT", "FX margin, transfer fees"),
    (5, "EXPENSE",   "Expenses",    "DEBIT",  "Partner costs, network fees"),
]

# Fixed GL accounts (non-customer). (account_code, name, type_id, currency)
GL_ACCOUNTS = [
    ("1000-CASH-USD",      "Operating Cash USD",         1, "USD"),
    ("1000-CASH-GBP",      "Operating Cash GBP",         1, "GBP"),
    ("1000-CASH-EUR",      "Operating Cash EUR",         1, "EUR"),
    ("1100-CUSTODY-USDC",  "Fireblocks Custody USDC",    1, "USDC"),
    ("1100-CUSTODY-USDT",  "Fireblocks Custody USDT",    1, "USDT"),
    ("1110-CIRCLE-USDC",   "Circle Custody USDC",        1, "USDC"),
    ("1200-PARTNER-RECV",  "Partner Receivable",         1, "USD"),
    ("2000-CUST-LIAB-USD", "Customer Balances USD",      2, "USD"),
    ("2000-CUST-LIAB-KES", "Customer Balances KES",      2, "KES"),
    ("2000-CUST-LIAB-NGN", "Customer Balances NGN",      2, "NGN"),
    ("2100-FEES-PAYABLE",  "Fees Payable",               2, "USD"),
    ("3000-RETAINED",      "Retained Earnings",          3, "USD"),
    ("4000-FX-MARGIN",     "FX Margin Revenue",          4, "USD"),
    ("4100-TRANSFER-FEES", "Transfer Fee Revenue",       4, "USD"),
    ("5000-PARTNER-COST",  "Partner Payout Cost",        5, "USD"),
    ("5100-NETWORK-FEES",  "Blockchain Network Fees",    5, "USD"),
    ("9000-SUSPENSE",      "Suspense / Clearing",        1, "USD"),
]
N_CUSTOMER_ACCOUNTS = 200  # subset of customers have an explicit ledger wallet account


def gen_account_types():
    for t in ACCOUNT_TYPES:
        yield t


def build_accounts():
    """Return (rows, account_index). account_index maps a logical name to
    account_id so journal generation can pick valid accounts."""
    rows = []
    idx = {}            # account_code -> (account_id, currency, type_id)
    aid = 1
    base = dt.datetime(2018, 1, 1)
    for code, name, type_id, ccy in GL_ACCOUNTS:
        rows.append((
            aid, code, name, type_id, ccy, None, None,
            False, True, False, None,
            ts_iso(base), ts_iso(base),
            json.dumps({"system": "core_ledger", "class": "gl"}),
        ))
        idx[code] = (aid, ccy, type_id)
        aid += 1

    # Customer wallet accounts (liability accounts, one per sampled customer).
    cust = customer_master()
    r = rng("ledger", "cust_accounts")
    chosen = r.sample(range(N["customers"]), min(N_CUSTOMER_ACCOUNTS, N["customers"]))
    cust_account_ids = []
    for cid in chosen:
        c = cust[cid]
        ar = rng("ledger", "acct", cid)
        opened = rand_datetime(ar, start=dt.date(2019, 1, 1))
        deleted = ar.random() < 0.05
        rows.append((
            aid, f"2000-CUST-{c.code}", f"Customer Wallet {c.code}", 2, c.currency,
            idx["2000-CUST-LIAB-USD"][0], c.code,
            False, not deleted, deleted,
            ts_iso(rand_datetime(ar, start=opened.date())) if deleted else None,
            ts_iso(opened), ts_iso(opened),
            json.dumps({"customer_code": c.code, "wallet": True}),
        ))
        cust_account_ids.append((aid, c.currency, c.code))
        aid += 1

    return rows, idx, cust_account_ids


# --------------------------------------------------------------------------
# Wallets
# --------------------------------------------------------------------------
def hex_address(r) -> str:
    return "0x" + "".join(r.choice("0123456789abcdef") for _ in range(40))


def sol_address(r) -> str:
    b58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    return "".join(r.choice(b58) for _ in range(44))


def crypto_address(r, chain: str) -> str:
    return sol_address(r) if chain == "solana" else hex_address(r)


def build_wallets(idx, cust_account_ids):
    """Return (rows, wallet_list). wallet_list = [(wallet_id, currency, type)]."""
    rows = []
    wallets = []
    wid = 1
    base = dt.datetime(2019, 1, 1)

    # Treasury / fee / suspense wallets (some stablecoin -> have addresses).
    treasury_specs = [
        ("TREASURY", "USDC", "1100-CUSTODY-USDC"),
        ("TREASURY", "USDT", "1100-CUSTODY-USDT"),
        ("TREASURY", "USDC", "1110-CIRCLE-USDC"),
        ("TREASURY", "USD",  "1000-CASH-USD"),
        ("TREASURY", "GBP",  "1000-CASH-GBP"),
        ("TREASURY", "EUR",  "1000-CASH-EUR"),
        ("FEE",      "USD",  "2100-FEES-PAYABLE"),
        ("SUSPENSE", "USD",  "9000-SUSPENSE"),
    ]
    for wtype, ccy, acode in treasury_specs:
        wr = rng("ledger", "wallet", wid)
        is_crypto = ccy in STABLECOINS
        chain = wr.choice(CHAINS) if is_crypto else None
        rows.append((
            wid, det_uuid(("ledger_wallet", wid)), None, wtype, ccy,
            idx[acode][0],
            crypto_address(wr, chain) if is_crypto else None,
            chain, "ACTIVE", ts_iso(base), None,
            json.dumps({"treasury": True}),
        ))
        wallets.append((wid, ccy, wtype))
        wid += 1

    # Customer wallets — fiat + some stablecoin (USDC).
    for acct_id, ccy, code in cust_account_ids:
        wr = rng("ledger", "custwallet", acct_id)
        opened = rand_datetime(wr, start=dt.date(2019, 6, 1))
        status = wr.choices(["ACTIVE", "FROZEN", "CLOSED"], weights=[90, 5, 5])[0]
        rows.append((
            wid, det_uuid(("ledger_wallet", wid)), code, "CUSTOMER", ccy,
            acct_id, None, None, status, ts_iso(opened),
            ts_iso(rand_datetime(wr, start=opened.date())) if status == "CLOSED" else None,
            json.dumps({"customer_code": code}),
        ))
        wallets.append((wid, ccy, "CUSTOMER"))
        wid += 1
        # ~40% of customer wallets also have a USDC stablecoin wallet.
        if wr.random() < 0.40:
            chain = wr.choice(CHAINS)
            rows.append((
                wid, det_uuid(("ledger_wallet", wid)), code, "CUSTOMER", "USDC",
                idx["1110-CIRCLE-USDC"][0], crypto_address(wr, chain), chain,
                "ACTIVE", ts_iso(opened), None,
                json.dumps({"customer_code": code, "stablecoin": True}),
            ))
            wallets.append((wid, "USDC", "CUSTOMER"))
            wid += 1

    return rows, wallets


# --------------------------------------------------------------------------
# Journal entries + lines (the FACT). Double-entry by construction.
# --------------------------------------------------------------------------
# Each "shape" is a list of (account_code, direction) using GL codes. We pick
# one amount per entry and apply it; multi-line shapes split the credit/debit so
# debits total == credits total.
ENTRY_SHAPES = [
    # (source_system, reference_type, [(code, direction, weight_of_amount)])
    ("transfers", "transfer", [
        ("1000-CASH-USD", "DEBIT", 1.0),
        ("2000-CUST-LIAB-USD", "CREDIT", 0.97),
        ("4100-TRANSFER-FEES", "CREDIT", 0.03),
    ]),
    ("transfers", "transfer", [
        ("2000-CUST-LIAB-USD", "DEBIT", 1.0),
        ("1200-PARTNER-RECV", "CREDIT", 1.0),
    ]),
    ("fees", "fee", [
        ("2000-CUST-LIAB-USD", "DEBIT", 1.0),
        ("4100-TRANSFER-FEES", "CREDIT", 1.0),
    ]),
    ("fx", "fx", [
        ("1000-CASH-USD", "DEBIT", 1.0),
        ("4000-FX-MARGIN", "CREDIT", 1.0),
    ]),
    ("treasury", "settlement", [
        ("1100-CUSTODY-USDC", "DEBIT", 1.0),
        ("1000-CASH-USD", "CREDIT", 1.0),
    ]),
    ("treasury", "settlement", [
        ("1110-CIRCLE-USDC", "DEBIT", 1.0),
        ("1100-CUSTODY-USDC", "CREDIT", 1.0),
    ]),
    ("rafiki", "settlement", [
        ("1100-CUSTODY-USDC", "DEBIT", 1.0),
        ("2000-CUST-LIAB-USD", "CREDIT", 0.98),
        ("4000-FX-MARGIN", "CREDIT", 0.02),
    ]),
    ("manual", "adjustment", [
        ("9000-SUSPENSE", "DEBIT", 1.0),
        ("1000-CASH-USD", "CREDIT", 1.0),
    ]),
]


def gen_journals(idx):
    """Yield (entry_rows_iter, line_rows_iter) is awkward; instead yield two
    separate generators. We produce entries and lines together so we keep the
    invariant, streaming both."""
    n_lines_target = N["ledger_lines"]
    entries = []
    lines = []
    entry_id = 1
    line_id = 1
    lines_made = 0
    transfer_pool = N["transfers"]

    while lines_made < n_lines_target:
        er = rng("ledger", "entry", entry_id)
        src, ref_type, shape = er.choice(ENTRY_SHAPES)
        posted = rand_datetime(er, start=dt.date(2019, 1, 1))
        amount = round(er.uniform(5, 25000), 4)
        ccy = idx[shape[0][0]][1]

        # Reference id: link a subset of transfer entries to core transfers.
        ref_id = None
        if ref_type == "transfer":
            ref_id = det_uuid(("transfer", er.randrange(transfer_pool)))
        elif ref_type == "settlement":
            ref_id = det_uuid(("settlement", er.randrange(max(1, transfer_pool // 50))))

        status = er.choices(["POSTED", "posted", "DRAFT", "REVERSED"],
                            weights=[88, 6, 3, 3])[0]
        is_rev = status == "REVERSED"

        entries.append((
            entry_id, det_uuid(("ledger_entry", entry_id)),
            posted.date().isoformat(), ts_iso(posted), ccy, src, ref_type,
            ref_id, f"{ref_type} posting {entry_id}", status, is_rev,
            (entry_id - 1) if is_rev and entry_id > 1 else None,
            er.choice(["system", "treasury-bot", "ops@nala.com", "recon-job"]),
            json.dumps({"shape": src}),
            maybe_null(f"BATCH-{posted.year}-{er.randint(1,9999)}", 0.92, er),
        ))

        # Build lines: split the credit side (or debit side) across shape entries.
        debit_codes = [(c, w) for c, d, w in shape if d == "DEBIT"]
        credit_codes = [(c, w) for c, d, w in shape if d == "CREDIT"]
        # Normalize weights on the side that has >1 entry; the single side gets full amount.
        def split(codes):
            total_w = sum(w for _, w in codes)
            out = []
            running = 0.0
            for i, (c, w) in enumerate(codes):
                if i == len(codes) - 1:
                    amt = round(amount - running, 4)  # last absorbs rounding
                else:
                    amt = round(amount * (w / total_w), 4)
                    running += amt
                out.append((c, amt))
            return out

        debit_split = split(debit_codes)
        credit_split = split(credit_codes)

        line_no = 1
        for code, amt in debit_split:
            aid = idx[code][0]
            lines.append((line_id, entry_id, line_no, aid, "DEBIT", amt,
                          idx[code][1], amt, None, f"dr {code}", ts_iso(posted)))
            line_id += 1; line_no += 1; lines_made += 1
        for code, amt in credit_split:
            aid = idx[code][0]
            lines.append((line_id, entry_id, line_no, aid, "CREDIT", amt,
                          idx[code][1], None, amt, f"cr {code}", ts_iso(posted)))
            line_id += 1; line_no += 1; lines_made += 1

        entry_id += 1

    return entries, lines


# --------------------------------------------------------------------------
# Wallet transactions
# --------------------------------------------------------------------------
def gen_wallet_txns(wallets, n_entries):
    """One or two txns per wallet plus a tail of activity. wallet_txn references
    a random entry_id in [1, n_entries]."""
    wtid = 1
    for wid, ccy, wtype in wallets:
        wr = rng("ledger", "wtxn", wid)
        n = wr.randint(1, 6) if wtype == "CUSTOMER" else wr.randint(3, 12)
        balance = round(wr.uniform(0, 5000), 4)
        for _ in range(n):
            tr = rng("ledger", "wtxn", wid, wtid)
            ttype = tr.choice(["CREDIT", "DEBIT"])
            amt = round(tr.uniform(1, 3000), 4)
            balance = round(balance + (amt if ttype == "CREDIT" else -amt), 4)
            occurred = rand_datetime(tr, start=dt.date(2020, 1, 1))
            yield (
                wtid, wid, maybe_null(tr.randint(1, n_entries), 0.10, tr),
                ttype, amt, ccy,
                maybe_null(balance, 0.08, tr),
                maybe_null(det_uuid(("transfer", tr.randrange(max(1, N["transfers"])))), 0.3, tr),
                f"{ttype.lower()} wallet movement",
                ts_iso(occurred),
                maybe_null(ts_iso(occurred), 0.6, tr),
            )
            wtid += 1


# --------------------------------------------------------------------------
# Balance snapshots
# --------------------------------------------------------------------------
def gen_balance_snapshots(account_rows):
    sid = 1
    # Monthly snapshots for the GL accounts (first 17), for the last 18 months.
    months = []
    d = dt.date(EPOCH_END.year, EPOCH_END.month, 1)
    for _ in range(18):
        months.append(d)
        d = (d.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
    for arow in account_rows[:len(GL_ACCOUNTS)]:
        aid = arow[0]; ccy = arow[4]
        for m in months:
            sr = rng("ledger", "snap", aid, m.toordinal())
            dr = round(sr.uniform(0, 5_000_000), 4)
            cr = round(sr.uniform(0, 5_000_000), 4)
            yield (sid, aid, m.isoformat(), ccy, dr, cr, round(dr - cr, 4),
                   ts_iso(dt.datetime.combine(m, dt.time(2, 0))))
            sid += 1


# --------------------------------------------------------------------------
# Reconciliation runs + breaks
# --------------------------------------------------------------------------
def gen_recon(account_rows):
    runs = []
    breaks = []
    run_id = 1
    break_id = 1
    recon_types = ["FIREBLOCKS", "CIRCLE", "BANK", "INTERNAL"]
    gl_ids = [a[0] for a in account_rows[:len(GL_ACCOUNTS)]]
    # Daily-ish runs over the last 120 days, per recon type.
    for day_off in range(120):
        as_of = (EPOCH_END - dt.timedelta(days=day_off))
        for rtype in recon_types:
            rr = rng("ledger", "recon", run_id)
            if rr.random() < 0.5 and rtype in ("BANK", "INTERNAL"):
                run_id += 1
                continue  # not every type runs every day
            started = dt.datetime.combine(as_of, dt.time(3, 0)) + dt.timedelta(minutes=rr.randint(0, 90))
            status = rr.choices(["COMPLETED", "RUNNING", "FAILED"], weights=[92, 4, 4])[0]
            completed = started + dt.timedelta(minutes=rr.randint(1, 25)) if status == "COMPLETED" else None
            n_breaks = rr.choices([0, 0, 0, 1, 2, 3], weights=[50, 15, 10, 12, 8, 5])[0] if status == "COMPLETED" else 0
            total_amt = 0.0
            for _ in range(n_breaks):
                br = rng("ledger", "break", break_id)
                aid = br.choice(gl_ids)
                ccy = next(a[4] for a in account_rows if a[0] == aid)
                ledger_bal = round(br.uniform(1000, 2_000_000), 4)
                diff = round(br.uniform(-50000, 50000), 4)
                ext_bal = round(ledger_bal - diff, 4)
                total_amt += abs(diff)
                bstatus = br.choices(["OPEN", "INVESTIGATING", "RESOLVED"], weights=[30, 20, 50])[0]
                breaks.append((
                    break_id, run_id, aid, ccy, ledger_bal, ext_bal, diff,
                    br.choice(["TIMING", "MISSING_TXN", "FX", "UNKNOWN"]),
                    bstatus,
                    ts_iso(completed + dt.timedelta(hours=br.randint(1, 72))) if (completed and bstatus == "RESOLVED") else None,
                    maybe_null("auto-resolved by recon job", 0.5, br),
                ))
                break_id += 1
            runs.append((
                run_id, det_uuid(("recon_run", run_id)), rtype, as_of.isoformat(),
                ts_iso(started), ts_iso(completed) if completed else None, status,
                n_breaks, round(total_amt, 4),
                rr.choice(["recon-job", "treasury-bot", "ops@nala.com"]),
                json.dumps({"recon_type": rtype}),
            ))
            run_id += 1
    return runs, breaks


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main(conn):
    ensure_schema(conn, SCHEMA)
    apply_ddl_file(conn, DDL)
    truncate(conn,
             f"{SCHEMA}.reconciliation_breaks",
             f"{SCHEMA}.reconciliation_runs",
             f"{SCHEMA}.balance_snapshots",
             f"{SCHEMA}.wallet_transactions",
             f"{SCHEMA}.journal_lines",
             f"{SCHEMA}.journal_entries",
             f"{SCHEMA}.wallets",
             f"{SCHEMA}.accounts",
             f"{SCHEMA}.account_types")

    # account_types
    bulk_copy(conn, f"{SCHEMA}.account_types",
              ["account_type_id", "code", "name", "normal_balance", "description"],
              gen_account_types())

    # accounts
    account_rows, idx, cust_account_ids = build_accounts()
    bulk_copy(conn, f"{SCHEMA}.accounts",
              ["account_id", "account_code", "account_name", "account_type_id",
               "currency", "parent_account_id", "customer_code", "is_contra",
               "is_active", "is_deleted", "deleted_at", "created_at", "updated_at",
               "metadata"], account_rows)

    # journal entries + lines
    entries, lines = gen_journals(idx)
    bulk_copy(conn, f"{SCHEMA}.journal_entries",
              ["entry_id", "entry_uuid", "entry_date", "posted_at", "currency",
               "source_system", "reference_type", "reference_id", "description",
               "status", "is_reversal", "reverses_entry_id", "created_by",
               "metadata", "legacy_batch_id"], entries)
    bulk_copy(conn, f"{SCHEMA}.journal_lines",
              ["line_id", "entry_id", "line_no", "account_id", "direction",
               "amount", "currency", "debit", "credit", "memo", "posted_at"],
              lines)

    # wallets
    wallet_rows, wallets = build_wallets(idx, cust_account_ids)
    bulk_copy(conn, f"{SCHEMA}.wallets",
              ["wallet_id", "wallet_uuid", "customer_code", "wallet_type",
               "currency", "ledger_account_id", "address", "chain", "status",
               "opened_at", "closed_at", "metadata"], wallet_rows)

    # wallet transactions
    bulk_copy(conn, f"{SCHEMA}.wallet_transactions",
              ["wallet_txn_id", "wallet_id", "entry_id", "txn_type", "amount",
               "currency", "balance_after", "reference_id", "description",
               "occurred_at", "created"],
              gen_wallet_txns(wallets, len(entries)))

    # balance snapshots
    bulk_copy(conn, f"{SCHEMA}.balance_snapshots",
              ["snapshot_id", "account_id", "snapshot_date", "currency",
               "debit_total", "credit_total", "balance", "created_at"],
              gen_balance_snapshots(account_rows))

    # reconciliation
    runs, breaks = gen_recon(account_rows)
    bulk_copy(conn, f"{SCHEMA}.reconciliation_runs",
              ["run_id", "run_uuid", "recon_type", "as_of_date", "started_at",
               "completed_at", "status", "total_breaks", "total_break_amount",
               "run_by", "metadata"], runs)
    bulk_copy(conn, f"{SCHEMA}.reconciliation_breaks",
              ["break_id", "run_id", "account_id", "currency", "ledger_balance",
               "external_balance", "break_amount", "break_type", "status",
               "resolved_at", "notes"], breaks)

    print(f"[{SCHEMA}] account_types={len(ACCOUNT_TYPES)} accounts={len(account_rows)} "
          f"entries={len(entries)} lines={len(lines)} wallets={len(wallet_rows)} "
          f"runs={len(runs)} breaks={len(breaks)}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
