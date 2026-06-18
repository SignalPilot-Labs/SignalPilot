"""
Domain 10 — raw_netsuite generator.

ERP / general ledger across NALA's legal subsidiaries. Lookups
(subsidiaries, departments), chart of accounts (gl_accounts), the GL line
FACT (gl_transactions, sized off N["transfers"]), AP master (vendors) and
AP transactions (vendor_bills). NetSuite quirks: integer internalIds,
"tranid" doc numbers, multi-currency with exchange_rate to base, epoch-ms
drift on the fact, free-text status enums. No customer PII here (ERP/AP).
"""
from __future__ import annotations

import datetime as dt
import random
from pathlib import Path

from common import (
    N, SCALE, connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    rng, rand_datetime, maybe_null, ts_epoch_ms, EPOCH_START, EPOCH_END,
    USD_FX,
)

_DDL = Path(__file__).resolve().parent.parent / "sql" / "ddl" / "raw_netsuite.sql"

# NALA's legal entities (subsidiaries). (id, name, country, base_ccy)
SUBSIDIARIES = [
    (1, "NALA Holdings Ltd", "GB", "GBP", False, None),
    (2, "NALA UK Ltd", "GB", "GBP", False, 1),
    (3, "NALA Inc", "US", "USD", False, 1),
    (4, "NALA Money Kenya Ltd", "KE", "KES", False, 1),
    (5, "NALA Tanzania Ltd", "TZ", "TZS", False, 1),
    (6, "NALA Senegal SARL", "SN", "XOF", False, 1),
    (7, "NALA Nigeria Ltd", "NG", "NGN", False, 1),
    (8, "Elimination Subsidiary", "GB", "GBP", True, 1),
]
DEPARTMENTS = [
    (10, "Engineering"), (11, "Product"), (12, "Compliance"),
    (13, "Operations"), (14, "Finance"), (15, "People"),
    (16, "Marketing"), (17, "Customer Support"), (18, "Treasury"),
]
# (acctnumber, name, type, category)
ACCOUNTS = [
    ("1000", "Cash - Operating", "Bank", "asset"),
    ("1010", "Cash - Stablecoin (USDC)", "Bank", "asset"),
    ("1100", "Accounts Receivable", "AcctRec", "asset"),
    ("1200", "Prepaid Expenses", "OthCurrAsset", "asset"),
    ("1500", "Customer Funds Held", "OthCurrAsset", "asset"),
    ("2000", "Accounts Payable", "AcctPay", "liability"),
    ("2100", "Accrued Liabilities", "OthCurrLiab", "liability"),
    ("2500", "Customer Payable (in transit)", "OthCurrLiab", "liability"),
    ("3000", "Common Stock", "Equity", "equity"),
    ("3100", "Retained Earnings", "Equity", "equity"),
    ("4000", "FX Margin Revenue", "Income", "income"),
    ("4010", "Transfer Fee Revenue", "Income", "income"),
    ("4020", "Rafiki Platform Revenue", "Income", "income"),
    ("5000", "Payout Partner Costs", "COGS", "expense"),
    ("5010", "FX / Treasury Costs", "COGS", "expense"),
    ("6000", "Salaries & Wages", "Expense", "expense"),
    ("6100", "Software & Infrastructure", "Expense", "expense"),
    ("6110", "Messaging (Twilio/SendGrid)", "Expense", "expense"),
    ("6200", "Compliance & KYC Vendors", "Expense", "expense"),
    ("6300", "Marketing & Advertising", "Expense", "expense"),
    ("6400", "Office & Admin", "Expense", "expense"),
]
# (company, category, currency-ish vendor)
VENDORS = [
    ("Twilio Inc", "Infrastructure"), ("Twilio SendGrid", "Infrastructure"),
    ("Amazon Web Services", "Infrastructure"), ("Snowflake Inc", "Infrastructure"),
    ("Onfido Ltd", "Compliance"), ("ComplyAdvantage", "Compliance"),
    ("Chainalysis Inc", "Compliance"), ("Flutterwave", "Banking"),
    ("Stripe Inc", "Banking"), ("Plaid Inc", "Banking"),
    ("Fireblocks", "Banking"), ("Circle Internet Financial", "Banking"),
    ("Google Ads", "Marketing"), ("Meta Platforms", "Marketing"),
    ("Braze Inc", "Marketing"), ("Zendesk Inc", "Infrastructure"),
    ("Deloitte LLP", "Professional"), ("WeWork", "Office"),
    ("MoneyGram", "Banking"), ("Thunes", "Banking"),
]
TXN_TYPES = ["Journal", "Journal", "VendBill", "Payment", "Invoice", "Deposit"]
GL_STATUS = ["Open", "Posted", "Paid In Full", "Pending Approval"]
BILL_STATUS = ["Paid In Full", "Paid In Full", "Open", "Pending Approval", "Cancelled"]
APPROVAL = ["Approved", "Approved", "Pending", "Rejected"]
TERMS = ["Net 30", "Net 30", "Net 15", "Net 45", "Due on receipt"]


def _period(d: dt.date) -> str:
    return d.strftime("%b %Y")


def _gen_subsidiaries():
    for sid, name, country, ccy, elim, parent in SUBSIDIARIES:
        r = rng("ns_sub", sid)
        yield (sid, name, f"{name} (Registered)", country, ccy, elim,
               parent, "Standard Jan-Dec", False)


def _gen_departments():
    for did, name in DEPARTMENTS:
        r = rng("ns_dept", did)
        yield (did, name, None, r.choice([1, 2, 3, 4]), False)


def _gen_accounts():
    for idx, (num, name, atype, cat) in enumerate(ACCOUNTS, start=100):
        r = rng("ns_acct", idx)
        yield (idx, num, name, atype, cat, None,
               maybe_null("USD", 0.7, r), False, False,
               rand_datetime(r, EPOCH_START, dt.date(2019, 1, 1)))


def _account_ids():
    return list(range(100, 100 + len(ACCOUNTS)))


def _gen_vendors():
    base = 5000
    for k, (company, cat) in enumerate(VENDORS):
        vid = base + k
        r = rng("ns_vendor", vid)
        sub = r.choice([1, 2, 3])
        ccy = {1: "GBP", 2: "GBP", 3: "USD"}[sub]
        slug = company.lower().replace(" ", "").replace(",", "")[:12]
        yield (
            vid,
            f"V{vid} {company}",
            company,
            cat,
            maybe_null(f"ap@{slug}.com", 0.15, r),
            maybe_null(f"+1{r.randint(2000000000, 2999999999)}", 0.6, r),
            sub,
            ccy,
            maybe_null(f"VAT{r.randint(100000000, 999999999)}", 0.4, r),
            r.choice(TERMS),
            cat in ("Professional", "Office"),
            False,
            rand_datetime(r, EPOCH_START, dt.date(2020, 1, 1)),
        )


def _gen_vendor_bills():
    n = max(200, N["transfers"] // 20)
    base = 700000
    n_vendors = len(VENDORS)
    for k in range(n):
        bid = base + k
        r = rng("ns_bill", bid)
        vendor_id = 5000 + r.randrange(n_vendors)
        sub = r.choice([1, 2, 3])
        ccy = {1: "GBP", 2: "GBP", 3: "USD"}[sub]
        td = rand_datetime(r).date()
        due = td + dt.timedelta(days=r.choice([15, 30, 45]))
        amount = round(r.uniform(120, 85000), 2)
        tax = round(amount * r.choice([0.0, 0.0, 0.2, 0.16]), 2)
        rate = 1.0 if ccy in ("GBP", "USD") else round(1.0 / USD_FX.get(ccy, 1.0), 6)
        base_amt = round((amount + tax) * (1.0 if ccy in ("GBP", "USD") else rate), 2)
        status = r.choice(BILL_STATUS)
        paid = (amount + tax) if status == "Paid In Full" else (
            round((amount + tax) * r.uniform(0, 0.6), 2) if status == "Open" else 0.0)
        remaining = round((amount + tax) - paid, 2)
        yield (
            bid,
            f"BILL{bid}",
            vendor_id,
            sub,
            maybe_null(r.choice([d[0] for d in DEPARTMENTS]), 0.3, r),
            td,
            due,
            _period(td),
            ccy,
            rate,
            amount,
            tax,
            base_amt,
            paid,
            remaining,
            status,
            r.choice(APPROVAL),
            maybe_null(f"Bill from vendor {vendor_id}", 0.4, r),
            dt.datetime.combine(td, dt.time(9, 0)),
            dt.datetime.combine(td, dt.time(9, 0)) + dt.timedelta(days=r.randint(0, 30)),
        )


def _gen_gl_transactions():
    """Balanced double-entry-ish journal lines. Each transaction emits 2 lines
    (a debit + an offsetting credit) so debits == credits per transaction."""
    n = N["transfers"]
    acct_ids = _account_ids()
    n_acct = len(acct_ids)
    txn = 0
    for i in range(n // 2 + 1):
        r = rng("ns_gl", i)
        ttype = r.choice(TXN_TYPES)
        td = rand_datetime(r).date()
        sub = r.choice([1, 2, 3, 4, 5, 6, 7])
        ccy = {1: "GBP", 2: "GBP", 3: "USD", 4: "KES", 5: "TZS",
               6: "XOF", 7: "NGN"}[sub]
        rate = 1.0 if ccy in ("GBP", "USD") else round(1.0 / USD_FX.get(ccy, 1.0), 6)
        amount = round(r.uniform(10, 50000), 2)
        tranid = f"{ttype[:2].upper()}{1000 + i}"
        dept = maybe_null(r.choice([d[0] for d in DEPARTMENTS]), 0.4, r)
        period = _period(td)
        status = r.choice(GL_STATUS)
        created_ms = ts_epoch_ms(dt.datetime.combine(td, dt.time(0, 0)))
        debit_acct = acct_ids[r.randrange(n_acct)]
        credit_acct = acct_ids[r.randrange(n_acct)]
        if credit_acct == debit_acct:
            credit_acct = acct_ids[(r.randrange(n_acct) + 1) % n_acct]
        tid = 800000 + i
        # debit line
        yield (f"{tid}-1", tid, tranid, ttype, 1, debit_acct, sub, dept, td,
               period, maybe_null("Auto-posted line", 0.5, r), amount, 0.0,
               amount, ccy, rate, status != "Pending Approval", status, created_ms)
        txn += 1
        if txn >= n:
            return
        # credit line
        yield (f"{tid}-2", tid, tranid, ttype, 2, credit_acct, sub, dept, td,
               period, maybe_null("Auto-posted line", 0.5, r), 0.0, amount,
               -amount, ccy, rate, status != "Pending Approval", status, created_ms)
        txn += 1
        if txn >= n:
            return


SUB_COLS = ["subsidiary_id", "name", "legal_name", "country", "base_currency",
            "is_elimination", "parent_id", "fiscal_calendar", "is_inactive"]
DEPT_COLS = ["department_id", "name", "parent_id", "subsidiary_id", "is_inactive"]
ACCT_COLS = ["account_id", "acctnumber", "account_name", "account_type",
             "account_category", "parent_id", "currency", "is_summary",
             "is_inactive", "created_at"]
VENDOR_COLS = ["vendor_id", "entityid", "company_name", "category", "email",
               "phone", "subsidiary_id", "currency", "tax_id", "terms",
               "is_1099_eligible", "is_inactive", "created_at"]
BILL_COLS = ["bill_id", "tranid", "vendor_id", "subsidiary_id", "department_id",
             "trandate", "duedate", "period_name", "currency", "exchange_rate",
             "amount", "tax_amount", "amount_base", "amount_paid",
             "amount_remaining", "status", "approval_status", "memo",
             "created_at", "updated_at"]
GL_COLS = ["transaction_line_id", "transaction_id", "tranid", "transaction_type",
           "line_number", "account_id", "subsidiary_id", "department_id",
           "trandate", "period_name", "memo", "debit", "credit", "amount",
           "currency", "exchange_rate", "posting", "status", "created_epoch_ms"]


def main(conn):
    ensure_schema(conn, "raw_netsuite")
    apply_ddl_file(conn, _DDL)
    truncate(conn, "raw_netsuite.gl_transactions", "raw_netsuite.vendor_bills",
             "raw_netsuite.vendors", "raw_netsuite.gl_accounts",
             "raw_netsuite.departments", "raw_netsuite.subsidiaries")
    s = bulk_copy(conn, "raw_netsuite.subsidiaries", SUB_COLS, _gen_subsidiaries())
    d = bulk_copy(conn, "raw_netsuite.departments", DEPT_COLS, _gen_departments())
    a = bulk_copy(conn, "raw_netsuite.gl_accounts", ACCT_COLS, _gen_accounts())
    v = bulk_copy(conn, "raw_netsuite.vendors", VENDOR_COLS, _gen_vendors())
    b = bulk_copy(conn, "raw_netsuite.vendor_bills", BILL_COLS, _gen_vendor_bills())
    g = bulk_copy(conn, "raw_netsuite.gl_transactions", GL_COLS, _gen_gl_transactions())
    print(f"[raw_netsuite] scale={SCALE} subsidiaries={s} departments={d} "
          f"gl_accounts={a} vendors={v} vendor_bills={b} gl_transactions={g}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
