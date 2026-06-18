"""
NALA warehouse — Domain 2 generator: raw_rafiki (Rafiki B2B payments API).

Builds the Rafiki B2B slice: merchants and their users / API keys / KYB,
inbound stablecoin collections, outbound local-currency payouts, daily
settlements (+ lines), invoices (+ line items), balances, balance txns,
fx locks, rate cards, webhooks and deliveries.

Idempotent: ensure schema -> apply DDL -> truncate -> load.
Sized off N["merchants"]. Big tables (collections/payouts/balance_txns/
webhook_deliveries) stream rows.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from common import (
    N, connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    rng, faker_for, maybe_null, dirty_email, dirty_phone,
    ts_iso, ts_isoz, ts_epoch_ms, rand_datetime, det_uuid,
    random_customer, customer_master,
    STABLECOINS, RECEIVE_MARKETS, RECEIVE_COUNTRIES, SEND_COUNTRIES,
    USD_FX, PARTNERS, EPOCH_START, EPOCH_END,
)

SCHEMA = "raw_rafiki"
DDL_PATH = Path(__file__).resolve().parent.parent / "sql" / "ddl" / "raw_rafiki.sql"

CHAINS = ["ethereum", "polygon", "tron", "solana", "base"]
INDUSTRIES = ["Payroll", "Marketplace", "Remittance", "iGaming", "Logistics",
              "Crypto Exchange", "NGO / Aid", "E-commerce", "Gig Platform"]
TIERS = ["standard", "scale", "enterprise"]
MERCHANT_STATUS = ["active", "active", "active", "suspended", "churned", "PENDING_KYB"]
ROLES = ["owner", "admin", "developer", "finance", "viewer"]
WEBHOOK_EVENTS = ["collection.confirmed", "collection.pending", "payout.paid",
                  "payout.failed", "settlement.created", "invoice.paid",
                  "balance.updated"]

# Send-from countries (where B2B HQs sit), flattened.
HQ_COUNTRIES = sorted({c for v in SEND_COUNTRIES.values() for c in v})


def _hexid(prefix, key):
    return f"{prefix}_{det_uuid(key).replace('-', '')[:18]}"


def _company_name(f, r):
    base = f.company().replace(",", "")
    suffix = r.choice(["", "", " Ltd", " Inc", " GmbH", " B.V.", " Group", " Pay"])
    return f"{base}{suffix}"


# --------------------------------------------------------------------------
# merchant master — built once, deterministically (other tables reference it)
# --------------------------------------------------------------------------
class Merchant:
    __slots__ = ("idx", "merchant_id", "legal_name", "display_name", "country",
                 "settle_ccy", "stablecoins", "tier", "status", "signup_at",
                 "industry", "destinations")

    def __init__(self, idx):
        r = rng("rafiki_merchant", idx)
        f = faker_for(("rafiki_merchant", idx))
        self.idx = idx
        self.merchant_id = _hexid("mrc", ("rafiki_merchant", idx))
        self.legal_name = _company_name(f, r)
        self.display_name = self.legal_name.replace(" Ltd", "").replace(" Inc", "")
        self.country = r.choice(HQ_COUNTRIES)
        # merchants pay out into a subset of receive markets
        k = r.randint(1, 4)
        self.destinations = r.sample(RECEIVE_COUNTRIES, k)
        self.settle_ccy = RECEIVE_MARKETS[self.destinations[0]][0]
        self.stablecoins = r.sample(STABLECOINS, r.randint(1, 3))
        self.tier = r.choices(TIERS, weights=[6, 3, 1])[0]
        self.status = r.choice(MERCHANT_STATUS)
        # Rafiki launched ~March 2024
        self.signup_at = rand_datetime(r, start=dt.date(2024, 3, 1), end=EPOCH_END)
        self.industry = r.choice(INDUSTRIES)


def _merchants():
    return [Merchant(i) for i in range(N["merchants"])]


# --------------------------------------------------------------------------
# Row builders
# --------------------------------------------------------------------------
def rows_merchants(merchants):
    cols = ["merchant_id", "legal_name", "display_name", "website", "country",
            "default_settlement_currency", "accepts_stablecoins", "industry",
            "status", "tier", "mrr_usd", "account_manager", "is_test",
            "is_deleted", "deleted_at", "metadata", "created_at", "updated"]

    def gen():
        for m in merchants:
            r = rng("rafiki_merchant_row", m.idx)
            f = faker_for(("rafiki_merchant_am", m.idx))
            mrr = round(r.uniform(200, 90_000) * (1 if m.tier == "standard"
                        else 4 if m.tier == "scale" else 18), 2)
            is_deleted = m.status == "churned" and r.random() < 0.4
            deleted_at = ts_iso(rand_datetime(r, start=dt.date(2024, 6, 1))) if is_deleted else None
            website = maybe_null(
                f"https://{m.display_name.split()[0].lower()}.com", 0.15, r)
            am = maybe_null(f.name(), 0.2, r)
            meta = ('{"signup_source":"%s","sandbox_only":%s}'
                    % (r.choice(["direct", "referral", "sales", "partner"]),
                       "true" if r.random() < 0.05 else "false"))
            yield (
                m.merchant_id, m.legal_name, m.display_name, website, m.country,
                m.settle_ccy, ",".join(m.stablecoins), m.industry, m.status,
                m.tier, mrr, am, r.random() < 0.04, is_deleted, deleted_at,
                meta, ts_isoz(m.signup_at),
                ts_iso(rand_datetime(r, start=m.signup_at.date())),
            )
    return cols, gen()


def rows_merchant_users(merchants):
    cols = ["user_id", "merchant_id", "full_name", "email", "phone", "role",
            "canonical_cid", "last_login_at", "is_active", "invited_by",
            "created", "mfa_enabled"]

    def gen():
        for m in merchants:
            r = rng("rafiki_user", m.idx)
            n_users = r.randint(1, 5)
            owner_id = None
            for u in range(n_users):
                ur = rng("rafiki_user", m.idx, u)
                f = faker_for(("rafiki_user", m.idx, u))
                uid = _hexid("usr", ("rafiki_user", m.idx, u))
                role = "owner" if u == 0 else ur.choice(ROLES[1:])
                if u == 0:
                    owner_id = uid
                # ~15% of merchant users are also app customers (cross-source join)
                cid = None
                email = f"{f.first_name()}.{f.last_name()}@{m.display_name.split()[0].lower()}.com".lower()
                phone = None
                if ur.random() < 0.15:
                    cust = random_customer(ur)
                    cid = cust.cid
                    email = cust.email
                    phone = cust.phone
                else:
                    phone = f"+{ur.randint(1, 44)}{ur.randint(7000000000, 7999999999)}"
                yield (
                    uid, m.merchant_id, f.name(),
                    dirty_email(email, ur), dirty_phone(phone, ur), role, cid,
                    maybe_null(ts_epoch_ms(rand_datetime(ur, start=m.signup_at.date())), 0.1, ur),
                    ur.random() < 0.9,
                    None if u == 0 else owner_id,
                    ts_isoz(rand_datetime(ur, start=m.signup_at.date())),
                    ur.random() < 0.6,
                )
    return cols, gen()


def rows_api_keys(merchants):
    cols = ["api_key_id", "merchant_id", "key_prefix", "key_hash", "mode",
            "scopes", "label", "created_by", "last_used_at", "revoked",
            "revoked_at", "created_at"]

    def gen():
        for m in merchants:
            r = rng("rafiki_apikey", m.idx)
            n_keys = r.randint(1, 4)
            for k in range(n_keys):
                kr = rng("rafiki_apikey", m.idx, k)
                kid = _hexid("ak", ("rafiki_apikey", m.idx, k))
                mode = kr.choice(["live", "live", "test"])
                rawhex = det_uuid(("rafiki_keyraw", m.idx, k)).replace("-", "")
                prefix = f"rk_{mode}_{rawhex[:6]}"
                khash = (det_uuid(("rafiki_keyhash", m.idx, k)).replace("-", "")
                         + det_uuid(("rafiki_keyhash2", m.idx, k)).replace("-", ""))
                revoked = kr.random() < 0.2
                created = rand_datetime(kr, start=m.signup_at.date())
                scopes = '["collections:read","collections:write","payouts:write","balances:read"]' \
                    if mode == "live" else '["collections:read","payouts:read"]'
                yield (
                    kid, m.merchant_id, prefix, khash, mode, scopes,
                    kr.choice(["Production", "Server key", "Backend", "CI", "Default"]),
                    _hexid("usr", ("rafiki_user", m.idx, 0)),
                    maybe_null(ts_iso(rand_datetime(kr, start=created.date())), 0.15, kr),
                    revoked,
                    ts_iso(rand_datetime(kr, start=created.date())) if revoked else None,
                    ts_isoz(created),
                )
    return cols, gen()


def rows_kyb(merchants):
    cols = ["kyb_id", "merchant_id", "legal_entity_name", "registration_number",
            "tax_id", "incorporation_country", "incorporation_date",
            "beneficial_owner_name", "beneficial_owner_dob", "risk_rating",
            "kyb_status", "provider", "verified_at", "documents", "created_at"]

    def gen():
        for m in merchants:
            r = rng("rafiki_kyb", m.idx)
            f = faker_for(("rafiki_kyb", m.idx))
            status = ("approved" if m.status in ("active", "suspended", "churned")
                      else r.choice(["pending", "review", "rejected"]))
            verified = (ts_isoz(rand_datetime(r, start=m.signup_at.date()))
                        if status == "approved" else None)
            inc_date = f.date_between(start_date="-25y", end_date="-1y")
            risk = r.choices(["low", "medium", "high"], weights=[5, 3, 2])[0]
            docs = '["certificate_of_incorporation","proof_of_address","ubo_register"]'
            yield (
                _hexid("kyb", ("rafiki_kyb", m.idx)), m.merchant_id, m.legal_name,
                f.bothify("REG-########"),
                maybe_null(f.bothify("TAX-#########"), 0.1, r),
                m.country, inc_date.isoformat(), f.name(),
                f.date_of_birth(minimum_age=30, maximum_age=70).isoformat(),
                risk, status, r.choice(["Onfido", "Persona", "internal"]),
                verified, docs, ts_isoz(rand_datetime(r, start=m.signup_at.date())),
            )
    return cols, gen()


def rows_rate_cards(merchants):
    cols = ["rate_card_id", "merchant_id", "name", "collection_fee_bps",
            "payout_fee_bps", "fx_margin_bps", "flat_fee_usd", "min_payout_usd",
            "effective_from", "effective_to", "is_current", "created_at"]
    # carry a current rate-card-id per merchant for downstream pricing refs
    current = {}

    def gen():
        for m in merchants:
            r = rng("rafiki_ratecard", m.idx)
            # 1-2 historical + 1 current
            n = r.randint(1, 3)
            start = m.signup_at.date()
            for i in range(n):
                cr = rng("rafiki_ratecard", m.idx, i)
                rid = _hexid("rc", ("rafiki_ratecard", m.idx, i))
                is_current = (i == n - 1)
                eff_from = start + dt.timedelta(days=180 * i)
                eff_to = None if is_current else start + dt.timedelta(days=180 * (i + 1))
                if is_current:
                    current[m.idx] = rid
                yield (
                    rid, m.merchant_id,
                    cr.choice(["Standard", "Negotiated", "Enterprise", "Launch"]),
                    cr.randint(20, 120), cr.randint(20, 150), cr.randint(50, 180),
                    round(cr.uniform(0, 0.5), 4), round(cr.uniform(1, 50), 2),
                    eff_from.isoformat(),
                    eff_to.isoformat() if eff_to else None,
                    is_current, ts_isoz(rand_datetime(cr, start=eff_from)),
                )
    return cols, gen(), current


def _local_amount(usd, ccy, r):
    rate = USD_FX.get(ccy, 1.0)
    return round(usd * rate * r.uniform(0.98, 1.02), 2)


# Collections / payouts are the big fact tables. Volume ~ tier-weighted.
def _txn_count(m, r):
    base = {"standard": 8, "scale": 40, "enterprise": 160}[m.tier]
    return max(1, int(base * r.uniform(0.4, 1.6)))


def rows_collections(merchants, current_rc, sink):
    """sink: dict merchant_idx -> list of (collection_id, amount_usd, received_dt)."""
    cols = ["collection_id", "merchant_id", "reference", "stablecoin", "chain",
            "amount_crypto", "amount_usd", "fee_usd", "from_wallet", "to_wallet",
            "tx_hash", "confirmations", "status", "rate_card_id", "settlement_id",
            "received_at", "confirmed_at", "metadata"]

    def gen():
        for m in merchants:
            if m.status == "PENDING_KYB":
                continue
            r = rng("rafiki_collection", m.idx)
            n = _txn_count(m, r)
            for i in range(n):
                cr = rng("rafiki_collection", m.idx, i)
                cid = _hexid("col", ("rafiki_collection", m.idx, i))
                coin = cr.choice(m.stablecoins)
                amt_usd = round(cr.uniform(50, 25_000), 2)
                fee = round(amt_usd * cr.uniform(0.001, 0.01), 2)
                status = cr.choices(
                    ["confirmed", "pending", "failed", "CONFIRMED_OLD"],
                    weights=[80, 8, 7, 5])[0]
                received = rand_datetime(cr, start=m.signup_at.date())
                from_w = "0x" + det_uuid(("colwallet", m.idx, i)).replace("-", "")[:40]
                to_w = "0x" + det_uuid(("rafikiwallet", m.idx)).replace("-", "")[:40]
                txh = "0x" + (det_uuid(("txh", m.idx, i)).replace("-", "")
                              + det_uuid(("txh2", m.idx, i)).replace("-", ""))[:64]
                meta = '{"network_fee_usd":%.2f,"sender_memo":%s}' % (
                    cr.uniform(0.1, 5.0),
                    '"%s"' % cr.choice(["invoice", "payroll", "topup", "refund"]))
                if status in ("confirmed", "CONFIRMED_OLD"):
                    sink.setdefault(m.idx, []).append((cid, amt_usd, received))
                yield (
                    cid, m.merchant_id, det_uuid(("colref", m.idx, i))[:18],
                    coin, cr.choice(CHAINS),
                    round(amt_usd / USD_FX.get(coin, 1.0), 6), amt_usd, fee,
                    from_w, to_w, txh, cr.randint(1, 64), status,
                    current_rc.get(m.idx), None,  # settlement_id filled later via settlements? kept null at raw
                    ts_isoz(received),
                    maybe_null(ts_epoch_ms(received + dt.timedelta(minutes=cr.randint(1, 30))), 0.1, cr),
                    meta,
                )
    return cols, gen()


def rows_payouts(merchants, sink):
    """sink: merchant_idx -> list of (payout_id, amount_usd, created_dt)."""
    cols = ["payout_id", "merchant_id", "idempotency_key", "recipient_name",
            "recipient_account", "recipient_type", "rail", "destination_country",
            "currency", "amount_local", "amount_usd", "fx_rate", "fee_usd",
            "fx_lock_id", "status", "failure_reason", "partner", "settlement_id",
            "canonical_cid", "created", "completed_at", "metadata"]

    def gen():
        for m in merchants:
            if m.status == "PENDING_KYB":
                continue
            r = rng("rafiki_payout", m.idx)
            n = _txn_count(m, r)
            for i in range(n):
                pr = rng("rafiki_payout", m.idx, i)
                f = faker_for(("rafiki_payout", m.idx, i))
                pid = _hexid("pyt", ("rafiki_payout", m.idx, i))
                dest = pr.choice(m.destinations)
                ccy, rails = RECEIVE_MARKETS[dest]
                rail = pr.choice(rails)
                rtype = "bank" if rail == "Bank" else "mobile_money"
                amt_usd = round(pr.uniform(20, 12_000), 2)
                rate = round(USD_FX.get(ccy, 1.0) * pr.uniform(0.99, 1.01), 8)
                status = pr.choices(
                    ["paid", "processing", "failed", "reversed", "PENDING_OLD"],
                    weights=[78, 9, 7, 3, 3])[0]
                # cross-source: some B2B payouts land to app customers
                cid = None
                rname = f.name()
                if rtype == "bank":
                    racct = f.iban() if dest in ("ZA",) or pr.random() < 0.3 else f.bothify("##########")
                else:
                    racct = f"+{pr.randint(1, 260)}{pr.randint(700000000, 799999999)}"
                if pr.random() < 0.12:
                    cust = random_customer(pr)
                    cid = cust.cid
                    rname = f"{cust.first} {cust.last}"
                created = rand_datetime(pr, start=m.signup_at.date())
                completed = (ts_iso(created + dt.timedelta(minutes=pr.randint(1, 120)))
                             if status == "paid" else None)
                fail = (pr.choice(["insufficient_balance", "invalid_account",
                        "rail_timeout", "compliance_hold"])
                        if status == "failed" else None)
                meta = '{"purpose":%s}' % ('"%s"' % pr.choice(
                    ["salary", "supplier", "commission", "refund", "aid_disbursement"]))
                if status in ("paid", "processing"):
                    sink.setdefault(m.idx, []).append((pid, amt_usd, created))
                yield (
                    pid, m.merchant_id, det_uuid(("payidem", m.idx, i)),
                    rname, racct, rtype, rail, dest, ccy,
                    _local_amount(amt_usd, ccy, pr), amt_usd, rate,
                    round(amt_usd * pr.uniform(0.0, 0.012), 2),
                    _hexid("fxl", ("rafiki_fxlock", m.idx, i)) if pr.random() < 0.7 else None,
                    status, fail,
                    pr.choice(PARTNERS["payout_rail"]), None, cid,
                    ts_epoch_ms(created), completed, meta,
                )
    return cols, gen()


def rows_settlements(merchants, col_sink, pay_sink, settle_index):
    """Build daily settlements by netting collections vs payouts.
    settle_index: merchant_idx -> list of (settlement_id, date, lines[]) for line gen."""
    cols = ["settlement_id", "merchant_id", "settlement_date", "currency",
            "gross_collected_usd", "gross_paid_out_usd", "total_fees_usd",
            "net_amount_usd", "line_count", "status", "statement_url",
            "created_at", "settled_at"]

    def gen():
        for m in merchants:
            r = rng("rafiki_settlement", m.idx)
            # group collections + payouts by date
            by_day = {}
            for (cid, amt, d) in col_sink.get(m.idx, []):
                by_day.setdefault(d.date(), {"col": [], "pay": []})["col"].append((cid, amt))
            for (pid, amt, d) in pay_sink.get(m.idx, []):
                by_day.setdefault(d.date(), {"col": [], "pay": []})["pay"].append((pid, amt))
            for day, grp in sorted(by_day.items()):
                sr = rng("rafiki_settlement", m.idx, day.toordinal())
                sid = _hexid("set", ("rafiki_settlement", m.idx, day.toordinal()))
                gross_col = round(sum(a for _, a in grp["col"]), 2)
                gross_pay = round(sum(a for _, a in grp["pay"]), 2)
                fees = round((gross_col + gross_pay) * sr.uniform(0.005, 0.02), 2)
                net = round(gross_col - gross_pay - fees, 2)
                lc = len(grp["col"]) + len(grp["pay"])
                status = sr.choices(["settled", "pending", "on_hold"],
                                    weights=[85, 10, 5])[0]
                created = dt.datetime.combine(day, dt.time(23, 0))
                settled = (created + dt.timedelta(days=1)) if status == "settled" else None
                settle_index.setdefault(m.idx, []).append((sid, day, grp, status))
                yield (
                    sid, m.merchant_id, day.isoformat(), m.settle_ccy,
                    gross_col, gross_pay, fees, net, lc, status,
                    f"https://dashboard.rafiki.com/statements/{sid}.pdf",
                    ts_iso(created), ts_iso(settled) if settled else None,
                )
    return cols, gen()


def rows_settlement_lines(merchants, settle_index):
    cols = ["settlement_line_id", "settlement_id", "merchant_id", "line_type",
            "source_id", "description", "amount_usd", "direction", "created_at"]

    def gen():
        for m in merchants:
            for (sid, day, grp, status) in settle_index.get(m.idx, []):
                ln = 0
                created = ts_iso(dt.datetime.combine(day, dt.time(23, 5)))
                for (cid, amt) in grp["col"]:
                    yield (f"{sid}_l{ln}", sid, m.merchant_id, "collection", cid,
                           "Stablecoin collection", amt, "credit", created)
                    ln += 1
                for (pid, amt) in grp["pay"]:
                    yield (f"{sid}_l{ln}", sid, m.merchant_id, "payout", pid,
                           "Local-currency payout", amt, "debit", created)
                    ln += 1
    return cols, gen()


def rows_balances(merchants):
    cols = ["balance_id", "merchant_id", "currency", "available_amount",
            "pending_amount", "reserved_amount", "as_of", "updated_at"]
    now = dt.datetime(2026, 6, 18, 0, 0, 0)

    def gen():
        for m in merchants:
            r = rng("rafiki_balance", m.idx)
            ccys = list(dict.fromkeys(["USD"] + m.stablecoins + [m.settle_ccy]))
            for ccy in ccys:
                br = rng("rafiki_balance", m.idx, ccy)
                yield (
                    _hexid("bal", ("rafiki_balance", m.idx, ccy)), m.merchant_id,
                    ccy, round(br.uniform(0, 250_000), 2),
                    round(br.uniform(0, 30_000), 2), round(br.uniform(0, 10_000), 2),
                    ts_iso(now), ts_iso(now),
                )
    return cols, gen()


def rows_balance_transactions(merchants, col_sink, pay_sink):
    cols = ["balance_txn_id", "merchant_id", "currency", "type", "amount",
            "running_balance", "source_id", "description", "created_at", "metadata"]

    def gen():
        for m in merchants:
            r = rng("rafiki_btxn", m.idx)
            events = []
            for (cid, amt, d) in col_sink.get(m.idx, []):
                events.append((d, "collection", amt, cid))
            for (pid, amt, d) in pay_sink.get(m.idx, []):
                events.append((d, "payout", -amt, pid))
            events.sort(key=lambda e: e[0])
            running = 0.0
            for j, (d, typ, amt, src) in enumerate(events):
                running = round(running + amt, 2)
                yield (
                    _hexid("btxn", ("rafiki_btxn", m.idx, j)), m.merchant_id, "USD",
                    typ, amt, running, src,
                    "Stablecoin collection" if typ == "collection" else "B2B payout",
                    ts_epoch_ms(d), '{"settled":%s}' % ("true" if r.random() < 0.9 else "false"),
                )
                # interleave a fee txn occasionally
                if r.random() < 0.3:
                    fee = -round(abs(amt) * 0.008, 2)
                    running = round(running + fee, 2)
                    yield (
                        _hexid("btxn", ("rafiki_btxnfee", m.idx, j)), m.merchant_id,
                        "USD", "fee", fee, running, src, "Processing fee",
                        ts_epoch_ms(d + dt.timedelta(seconds=1)), '{"settled":true}')
    return cols, gen()


def rows_invoices(merchants, inv_index):
    cols = ["invoice_id", "merchant_id", "invoice_number", "period_start",
            "period_end", "currency", "subtotal_usd", "tax_usd", "total_usd",
            "amount_paid_usd", "status", "due_date", "issued_at", "paid_at",
            "pdf_url", "metadata"]

    def gen():
        for m in merchants:
            if m.status == "PENDING_KYB":
                continue
            r = rng("rafiki_invoice", m.idx)
            # monthly invoices from signup to now (cap a few months at test scale)
            start = m.signup_at.replace(day=1)
            months = []
            cur = dt.date(start.year, start.month, 1)
            while cur < EPOCH_END and len(months) < 12:
                months.append(cur)
                cur = (cur.replace(day=28) + dt.timedelta(days=7)).replace(day=1)
            for mi, pstart in enumerate(months):
                ir = rng("rafiki_invoice", m.idx, mi)
                pend = (pstart.replace(day=28) + dt.timedelta(days=7)).replace(day=1) - dt.timedelta(days=1)
                iid = _hexid("inv", ("rafiki_invoice", m.idx, mi))
                subtotal = round(ir.uniform(50, 12_000), 2)
                tax = round(subtotal * 0.0, 2)
                total = round(subtotal + tax, 2)
                status = ir.choices(["paid", "open", "past_due", "void", "draft"],
                                    weights=[70, 12, 8, 5, 5])[0]
                paid_amt = total if status == "paid" else (
                    round(total * ir.uniform(0, 0.6), 2) if status == "past_due" else 0)
                issued = dt.datetime.combine(pend + dt.timedelta(days=1), dt.time(8, 0))
                due = pend + dt.timedelta(days=15)
                paid_at = ts_iso(issued + dt.timedelta(days=ir.randint(1, 14))) if status == "paid" else None
                inv_index.setdefault(m.idx, []).append((iid, subtotal, mi))
                yield (
                    iid, m.merchant_id, f"RAF-{pstart.year}-{m.idx:05d}{mi:02d}",
                    pstart.isoformat(), pend.isoformat(), "USD",
                    subtotal, tax, total, paid_amt, status, due.isoformat(),
                    ts_iso(issued), paid_at,
                    f"https://dashboard.rafiki.com/invoices/{iid}.pdf",
                    '{"auto_charged":%s}' % ("true" if ir.random() < 0.5 else "false"),
                )
    return cols, gen()


def rows_invoice_line_items(merchants, inv_index):
    cols = ["line_item_id", "invoice_id", "merchant_id", "item_type",
            "description", "quantity", "unit_amount_usd", "amount_usd", "created_at"]
    ITEM_TYPES = [("collection_fees", "Collection fees"),
                  ("payout_fees", "Payout fees"),
                  ("fx_margin", "FX margin"),
                  ("platform_fee", "Platform subscription")]

    def gen():
        for m in merchants:
            for (iid, subtotal, mi) in inv_index.get(m.idx, []):
                lr = rng("rafiki_invline", m.idx, mi)
                n = lr.randint(2, 4)
                chosen = lr.sample(ITEM_TYPES, n)
                remaining = subtotal
                created = ts_iso(rand_datetime(lr, start=m.signup_at.date()))
                for li, (itype, desc) in enumerate(chosen):
                    amt = round(remaining / (n - li), 2) if li < n - 1 else round(remaining, 2)
                    remaining = round(remaining - amt, 2)
                    qty = lr.randint(1, 500)
                    unit = round(amt / qty, 4) if qty else amt
                    yield (f"{iid}_li{li}", iid, m.merchant_id, itype, desc,
                           qty, unit, amt, created)
    return cols, gen()


def rows_fx_locks(merchants):
    cols = ["fx_lock_id", "merchant_id", "base_currency", "quote_currency",
            "rate", "margin_bps", "amount_base", "expires_at", "consumed",
            "consumed_by", "created_at"]

    def gen():
        for m in merchants:
            if m.status == "PENDING_KYB":
                continue
            r = rng("rafiki_fxlock", m.idx)
            n = _txn_count(m, r)
            for i in range(n):
                fr = rng("rafiki_fxlock", m.idx, i)
                if fr.random() > 0.7:
                    continue  # not every payout uses a lock
                dest = fr.choice(m.destinations)
                ccy, _ = RECEIVE_MARKETS[dest]
                base = fr.choice(["USD"] + m.stablecoins)
                created = rand_datetime(fr, start=m.signup_at.date())
                consumed = fr.random() < 0.8
                yield (
                    _hexid("fxl", ("rafiki_fxlock", m.idx, i)), m.merchant_id,
                    base, ccy, round(USD_FX.get(ccy, 1.0) * fr.uniform(0.99, 1.01), 8),
                    fr.randint(50, 180), round(fr.uniform(100, 50_000), 2),
                    ts_iso(created + dt.timedelta(minutes=fr.randint(5, 60))),
                    consumed,
                    _hexid("pyt", ("rafiki_payout", m.idx, i)) if consumed else None,
                    ts_iso(created),
                )
    return cols, gen()


def rows_webhooks(merchants, wh_index):
    cols = ["webhook_id", "merchant_id", "url", "events", "secret_hash",
            "is_active", "api_version", "created_at", "disabled_at"]

    def gen():
        for m in merchants:
            r = rng("rafiki_webhook", m.idx)
            if r.random() < 0.25:
                continue  # not every merchant configures webhooks
            n = r.randint(1, 2)
            for w in range(n):
                wr = rng("rafiki_webhook", m.idx, w)
                wid = _hexid("wh", ("rafiki_webhook", m.idx, w))
                active = wr.random() < 0.85
                evs = wr.sample(WEBHOOK_EVENTS, wr.randint(1, len(WEBHOOK_EVENTS)))
                wh_index.setdefault(m.idx, []).append((wid, evs))
                created = rand_datetime(wr, start=m.signup_at.date())
                yield (
                    wid, m.merchant_id,
                    f"https://{m.display_name.split()[0].lower()}.com/webhooks/rafiki",
                    '[' + ",".join('"%s"' % e for e in evs) + ']',
                    det_uuid(("whsecret", m.idx, w)).replace("-", ""),
                    active, wr.choice(["2024-06-01", "2025-01-01", "2025-09-01"]),
                    ts_iso(created),
                    None if active else ts_iso(rand_datetime(wr, start=created.date())),
                )
    return cols, gen()


def rows_webhook_deliveries(merchants, wh_index):
    cols = ["delivery_id", "webhook_id", "merchant_id", "event_type", "event_id",
            "response_status", "attempt", "success", "duration_ms",
            "delivered_at", "next_retry_at"]

    def gen():
        for m in merchants:
            r = rng("rafiki_whdel", m.idx)
            for (wid, evs) in wh_index.get(m.idx, []):
                n = r.randint(3, 25)
                for d in range(n):
                    dr = rng("rafiki_whdel", m.idx, wid, d)
                    success = dr.random() < 0.88
                    status = (dr.choice([200, 201, 204]) if success
                              else dr.choice([400, 401, 500, 502, 503, None]))
                    attempt = 1 if success else dr.randint(1, 5)
                    delivered = rand_datetime(dr, start=m.signup_at.date())
                    yield (
                        _hexid("whd", ("rafiki_whdel", m.idx, wid, d)), wid,
                        m.merchant_id, dr.choice(evs),
                        _hexid("evt", ("rafiki_evt", m.idx, wid, d)),
                        status, attempt, success, dr.randint(20, 4000),
                        ts_epoch_ms(delivered),
                        ts_epoch_ms(delivered + dt.timedelta(minutes=5)) if not success else None,
                    )
    return cols, gen()


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main(conn):
    ensure_schema(conn, SCHEMA)
    apply_ddl_file(conn, DDL_PATH)

    tables = [
        "merchants", "merchant_users", "merchant_api_keys", "merchant_kyb",
        "rate_cards", "collections", "payouts", "settlements",
        "settlement_lines", "invoices", "invoice_line_items", "balances",
        "balance_transactions", "fx_locks", "webhooks", "webhook_deliveries",
    ]
    truncate(conn, *[f"{SCHEMA}.{t}" for t in tables])

    merchants = _merchants()

    # cross-table sinks / indexes
    col_sink, pay_sink = {}, {}
    settle_index, inv_index, wh_index = {}, {}, {}

    # merchants + people + creds + kyb
    c, g = rows_merchants(merchants)
    bulk_copy(conn, f"{SCHEMA}.merchants", c, g)
    c, g = rows_merchant_users(merchants)
    bulk_copy(conn, f"{SCHEMA}.merchant_users", c, g)
    c, g = rows_api_keys(merchants)
    bulk_copy(conn, f"{SCHEMA}.merchant_api_keys", c, g)
    c, g = rows_kyb(merchants)
    bulk_copy(conn, f"{SCHEMA}.merchant_kyb", c, g)

    # rate cards (returns current map)
    c, g, current_rc = rows_rate_cards(merchants)
    bulk_copy(conn, f"{SCHEMA}.rate_cards", c, g)

    # facts: collections + payouts (populate sinks)
    c, g = rows_collections(merchants, current_rc, col_sink)
    bulk_copy(conn, f"{SCHEMA}.collections", c, g)
    c, g = rows_payouts(merchants, pay_sink)
    bulk_copy(conn, f"{SCHEMA}.payouts", c, g)

    # settlements derived from facts
    c, g = rows_settlements(merchants, col_sink, pay_sink, settle_index)
    bulk_copy(conn, f"{SCHEMA}.settlements", c, g)
    c, g = rows_settlement_lines(merchants, settle_index)
    bulk_copy(conn, f"{SCHEMA}.settlement_lines", c, g)

    # invoices + line items
    c, g = rows_invoices(merchants, inv_index)
    bulk_copy(conn, f"{SCHEMA}.invoices", c, g)
    c, g = rows_invoice_line_items(merchants, inv_index)
    bulk_copy(conn, f"{SCHEMA}.invoice_line_items", c, g)

    # balances + balance txns
    c, g = rows_balances(merchants)
    bulk_copy(conn, f"{SCHEMA}.balances", c, g)
    c, g = rows_balance_transactions(merchants, col_sink, pay_sink)
    bulk_copy(conn, f"{SCHEMA}.balance_transactions", c, g)

    # fx locks
    c, g = rows_fx_locks(merchants)
    bulk_copy(conn, f"{SCHEMA}.fx_locks", c, g)

    # webhooks + deliveries
    c, g = rows_webhooks(merchants, wh_index)
    bulk_copy(conn, f"{SCHEMA}.webhooks", c, g)
    c, g = rows_webhook_deliveries(merchants, wh_index)
    bulk_copy(conn, f"{SCHEMA}.webhook_deliveries", c, g)

    print(f"[{SCHEMA}] loaded {len(merchants)} merchants + dependent tables")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
