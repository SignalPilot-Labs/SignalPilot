"""
NALA warehouse — Domain 1: Core Transfers (raw_core_transfers).

The heart of the product. Owns the transfer_id space:
    transfer_id = det_uuid(("transfer", i)) for i in range(N["transfers"]).

Other domains reference a random subset of these transfer ids.

Loads (test-scale counts in parens):
  Lookups:   corridors, cancellation_reasons, referral_codes
  Customers: customers (N["customers"]), customer_addresses, customer_devices,
             customer_kyc_status
  Recipients:recipients (N["recipients"]), recipient_payout_methods,
             saved_recipients (legacy messy dup)
  Fact:      transfers (N["transfers"]) + transfer_legs, transfer_status_history,
             transfer_fees, payout_attempts (streamed alongside)
  FX/quotes: quotes, fx_quotes
  Growth:    promo_redemptions, referrals

Idempotent: ensure schema -> apply DDL -> truncate -> load.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from common import *  # noqa: F401,F403

SCHEMA = "raw_core_transfers"
DDL = Path(__file__).resolve().parent.parent / "sql" / "ddl" / f"{SCHEMA}.sql"

# ---- enums / reference vocab local to this domain --------------------
ACCOUNT_STATUSES = ["active", "active", "active", "active", "suspended", "closed"]
KYC_TIERS = ["tier0", "tier1", "tier2", "tier3"]
KYC_STATUSES = ["approved", "approved", "approved", "pending", "rejected", "PENDING_OLD"]
RISK_RATINGS = ["low", "low", "low", "medium", "high"]
DOC_TYPES = ["passport", "national_id", "drivers_license"]
RELATIONSHIPS = ["family", "family", "friend", "self", "business"]
FUNDING_METHODS = ["card", "bank_transfer", "open_banking", "wallet"]
FUNDING_PARTNERS = {"card": "Stripe", "bank_transfer": "Plaid",
                    "open_banking": "TrueLayer", "wallet": "NALA Wallet"}
# Status mix (weighted toward COMPLETED — 98% land fast per profile).
TRANSFER_STATUSES = (["COMPLETED"] * 88 + ["PENDING"] * 4 + ["FAILED"] * 3
                     + ["CANCELLED"] * 3 + ["REFUNDED"] * 1 + ["PENDING_OLD"] * 1)
PROMO_TYPES = ["first_transfer", "fee_waiver", "fx_boost"]
REFERRAL_STATUSES = ["pending", "qualified", "rewarded", "rewarded", "expired"]

# Bank name pool per receive country (kept small + realistic).
BANKS = {
    "KE": "Equity Bank", "TZ": "CRDB Bank", "UG": "Stanbic Uganda",
    "RW": "Bank of Kigali", "NG": "GTBank", "GH": "GCB Bank",
    "SN": "Ecobank Senegal", "CI": "SGBCI", "CM": "Afriland First Bank",
    "GA": "BGFIBank", "CG": "BGFIBank Congo", "ZA": "Capitec",
    "IN": "HDFC Bank", "PK": "HBL", "BD": "BRAC Bank", "PH": "BDO",
}


# =====================================================================
# Reference / lookup builders
# =====================================================================
def build_corridors():
    """Every send-currency x receive-market combination NALA supports."""
    rows = []
    corridor_index = {}  # (send_cur, recv_country) -> corridor_id
    cid = 1
    for send_cur in SEND_CURRENCIES:
        send_country = SEND_COUNTRIES[send_cur][0]  # representative country
        for recv_country, (recv_cur, rails) in RECEIVE_MARKETS.items():
            r = rng("corridor", send_cur, recv_country)
            code = f"{send_country}_{recv_country}"
            rows.append((
                cid, code, send_country, send_cur, recv_country, recv_cur,
                rails[0], True,
                rand_datetime(r, EPOCH_START, dt.date(2022, 1, 1)).date().isoformat(),
                ts_iso(rand_datetime(r, EPOCH_START, dt.date(2022, 1, 1))),
            ))
            corridor_index[(send_cur, recv_country)] = cid
            cid += 1
    return rows, corridor_index


CANCELLATION_REASONS = [
    ("USER_CANCELLED", "Customer cancelled before payout", "user", True),
    ("COMPLIANCE_HOLD", "Held by compliance / sanctions screening", "compliance", False),
    ("KYC_INCOMPLETE", "Sender KYC not complete", "compliance", True),
    ("RECIPIENT_DETAILS_INVALID", "Recipient account details invalid", "user", True),
    ("PARTNER_REJECTED", "Payout partner rejected the payment", "partner", True),
    ("INSUFFICIENT_FUNDS", "Funding failed / insufficient funds", "user", True),
    ("DUPLICATE_TRANSFER", "Detected as duplicate", "system", False),
    ("FX_TIMEOUT", "FX quote expired before funding", "system", True),
    ("FRAUD_SUSPECTED", "Suspected fraudulent transfer", "compliance", False),
]


def build_cancellation_reasons():
    return [(i + 1, code, label, cat, uf)
            for i, (code, label, cat, uf) in enumerate(CANCELLATION_REASONS)]


def build_referral_codes(n_codes: int):
    cm = customer_master()
    rows = []
    for i in range(n_codes):
        r = rng("refcode", i)
        owner = cm[r.randrange(len(cm))]
        cur = owner.currency
        max_red = r.choice([5, 10, 25, 100])
        rows.append((
            i + 1,
            f"{owner.first[:3].upper()}{r.randint(100, 9999)}",
            owner.cid,
            round(r.choice([5, 10, 15]) * 1.0, 2),
            cur,
            max_red,
            r.randint(0, max_red),
            r.random() < 0.85,
            ts_isotz(owner.signup_at + dt.timedelta(days=r.randint(0, 60))),
            ts_isotz(owner.signup_at + dt.timedelta(days=r.randint(120, 800))),
        ))
    return rows


# =====================================================================
# Customers + sub-tables
# =====================================================================
def build_customers():
    cm = customer_master()
    rows = []
    for c in cm:
        r = rng("cust_row", c.cid)
        f = faker_for(("cust_extra", c.cid))
        is_deleted = r.random() < 0.03
        deleted_at = ts_isotz(c.signup_at + dt.timedelta(days=r.randint(30, 800))) if is_deleted else None
        nat_id = f"{c.country}{r.randint(10**8, 10**9 - 1)}"
        updated = c.signup_at + dt.timedelta(days=r.randint(0, 900))
        rows.append((
            c.cid,
            c.uuid,
            c.code,
            c.first,
            c.last,
            maybe_null(dirty_email(c.email, r), 0.04, r),  # ~4% null email
            dirty_phone(c.phone, r),
            c.dob,
            c.country,
            c.currency,
            maybe_null(nat_id, 0.10, r),
            "%032x" % (hash(("natid", nat_id)) & (2**128 - 1)),
            r.choice(KYC_TIERS),
            r.choice(ACCOUNT_STATUSES),
            c.platform,
            c.country,
            r.random() < 0.6,
            is_deleted,
            deleted_at,
            ts_isotz(c.signup_at),
            ts_isotz(updated),
            json_dumps({"acquisition": r.choice(["organic", "referral", "paid", "viral"]),
                        "lang": r.choice(["en", "sw", "fr"]),
                        "lifetime_transfers": r.randint(0, 400)}),
        ))
    return rows


def build_customer_addresses():
    cm = customer_master()
    rows = []
    aid = 1
    for c in cm:
        r = rng("addr", c.cid)
        n_addr = 1 if r.random() < 0.8 else 2
        for k in range(n_addr):
            atype = "home" if k == 0 else r.choice(["billing", "proof_of_address"])
            rows.append((
                aid, c.cid, atype, c.street,
                maybe_null(f"Flat {r.randint(1, 40)}", 0.7, r),
                c.city, c.postcode, c.country,
                k == 0, r.random() < 0.7,
                ts_iso(c.signup_at + dt.timedelta(days=r.randint(0, 30))),  # legacy ISO string
            ))
            aid += 1
    return rows


def build_customer_devices():
    cm = customer_master()
    rows = []
    for c in cm:
        r = rng("dev", c.cid)
        n_dev = r.choice([1, 1, 1, 2, 3])
        for k in range(n_dev):
            plat = c.platform if k == 0 else r.choice(DEVICE_PLATFORMS)
            seen = c.signup_at + dt.timedelta(days=r.randint(0, 1200), seconds=r.randint(0, 86399))
            rows.append((
                det_uuid(("device", c.cid, k)),
                c.cid, plat, r.choice(APP_VERSIONS),
                f"{plat}-{r.randint(12, 18)}.{r.randint(0, 6)}",
                r.choice(["iPhone14,3", "Pixel 7", "SM-G991B", "Chrome/Win", "iPhone15,2"]),
                maybe_null("ExponentPushToken[%032x]" % (r.getrandbits(48)), 0.3, r),
                f"{r.randint(1, 223)}.{r.randint(0, 255)}.{r.randint(0, 255)}.{r.randint(1, 254)}",
                ts_isoz(seen),                         # ISO-Z string drift
                r.random() < 0.65,
                ts_epoch_ms(c.signup_at + dt.timedelta(days=r.randint(0, 5))),
            ))
    return rows


def build_kyc_status():
    cm = customer_master()
    rows = []
    kid = 1
    for c in cm:
        r = rng("kyc", c.cid)
        provider = r.choice(PARTNERS["kyc"])
        f = faker_for(("kycdoc", c.cid))
        submitted = c.signup_at + dt.timedelta(hours=r.randint(0, 72))
        decided = submitted + dt.timedelta(hours=r.randint(1, 96))
        dtype = r.choice(DOC_TYPES)
        rows.append((
            kid, c.cid, provider, r.choice(KYC_TIERS),
            r.choice(KYC_STATUSES), r.choice(RISK_RATINGS),
            ts_iso(submitted), ts_isotz(decided),
            dtype,
            maybe_null(f.bothify("??######").upper(), 0.08, r),  # PII doc number
            True,
        ))
        kid += 1
    return rows


# =====================================================================
# Recipients + payout methods + legacy saved_recipients
# =====================================================================
def _recipient_for(idx: int):
    """Deterministically derive a recipient bound to a sender customer."""
    r = rng("recipient", idx)
    f = faker_for(("recipient", idx))
    cm = customer_master()
    customer = cm[r.randrange(len(cm))]
    recv_country = r.choice(RECEIVE_COUNTRIES)
    recv_cur = RECEIVE_MARKETS[recv_country][0]
    first, last = f.first_name(), f.last_name()
    return r, f, customer, recv_country, recv_cur, first, last


def build_recipients():
    rows = []
    for idx in range(N["recipients"]):
        r, f, customer, recv_country, recv_cur, first, last = _recipient_for(idx)
        created = customer.signup_at + dt.timedelta(days=r.randint(0, 800),
                                                    seconds=r.randint(0, 86399))
        phone_cc = {"KE": "+254", "TZ": "+255", "UG": "+256", "RW": "+250",
                    "NG": "+234", "GH": "+233", "SN": "+221", "CI": "+225",
                    "CM": "+237", "GA": "+241", "CG": "+242", "ZA": "+27",
                    "IN": "+91", "PK": "+92", "BD": "+880", "PH": "+63"}[recv_country]
        phone = f"{phone_cc}{r.randint(700000000, 799999999)}"
        email = f"{first}.{last}{r.randint(1,99)}@{r.choice(['gmail.com','yahoo.com'])}".lower()
        rows.append((
            idx + 1,
            det_uuid(("recipient", idx)),
            customer.cid,
            first, last, f"{first} {last}",
            recv_country, recv_cur,
            r.choice(RELATIONSHIPS),
            dirty_phone(phone, r),
            maybe_null(dirty_email(email, r), 0.55, r),     # recipients rarely have email
            maybe_null(f.date_of_birth(minimum_age=18, maximum_age=80).isoformat(), 0.7, r),
            r.random() < 0.92,
            r.random() < 0.05,
            ts_isotz(created),
            ts_isotz(created + dt.timedelta(days=r.randint(0, 200))),
        ))
    return rows


def build_payout_methods():
    rows = []
    pid = 1
    for idx in range(N["recipients"]):
        r, f, customer, recv_country, recv_cur, first, last = _recipient_for(idx)
        rails = RECEIVE_MARKETS[recv_country][1]
        n_methods = r.choice([1, 1, 1, 2])
        chosen = r.sample(rails, min(n_methods, len(rails)))
        for k, rail in enumerate(chosen):
            is_mm = rail not in ("Bank",)
            phone_cc = {"KE": "254", "TZ": "255", "UG": "256", "RW": "250",
                        "NG": "234", "GH": "233", "SN": "221", "CI": "225",
                        "CM": "237", "GA": "241", "CG": "242", "ZA": "27",
                        "IN": "91", "PK": "92", "BD": "880", "PH": "63"}[recv_country]
            msisdn = f"{phone_cc}{r.randint(700000000, 799999999)}" if is_mm else None
            acct = f"{r.randint(10**9, 10**10 - 1)}" if not is_mm else None
            iban = maybe_null(f.iban(), 0.85, r) if not is_mm else None
            rows.append((
                pid, idx + 1,
                "mobile_money" if is_mm else "bank",
                rail,
                rail if is_mm else BANKS[recv_country],
                msisdn,
                BANKS[recv_country] if not is_mm else None,
                acct,
                f"{first} {last}",
                iban,
                maybe_null(f.swift(), 0.85, r) if not is_mm else None,
                k == 0,
                r.random() < 0.8,
                ts_isotz(customer.signup_at + dt.timedelta(days=r.randint(0, 800))),
            ))
            pid += 1
    return rows


def build_saved_recipients():
    """LEGACY messy near-duplicate. Only ~40% of recipients have a legacy row;
    formats are inconsistent (country sometimes full name, payment_type casing)."""
    rows = []
    sid = 1
    country_full = {"KE": "Kenya", "NG": "Nigeria", "TZ": "Tanzania", "UG": "Uganda"}
    for idx in range(N["recipients"]):
        r, f, customer, recv_country, recv_cur, first, last = _recipient_for(idx)
        if r.random() > 0.4:
            continue
        rail = RECEIVE_MARKETS[recv_country][1][0]
        is_mm = rail != "Bank"
        # country dirty: sometimes ISO2, sometimes full name
        country_val = country_full.get(recv_country, recv_country) if r.random() < 0.3 else recv_country
        # payment_type inconsistent casing/values
        ptype = r.choice(["MPESA", "mpesa", "MOMO", "momo", "BANK", "bank", "mobile_money"])
        created_ms = ts_epoch_ms(customer.signup_at + dt.timedelta(days=r.randint(0, 400)))
        rows.append((
            sid, customer.cid,
            f"{first} {last}" if r.random() < 0.7 else f"{first}",  # sometimes just first name
            country_val, recv_cur,
            f"0{r.randint(700000000, 799999999)}" if is_mm else None,  # legacy local format
            f"{r.randint(10**9, 10**10 - 1)}" if not is_mm else None,
            ptype,
            created_ms,
            created_ms + r.randint(0, 10**8),
            1 if r.random() < 0.1 else 0,
            maybe_null(idx + 1, 0.5, r),  # migrated link often null
        ))
        sid += 1
    return rows


# =====================================================================
# TRANSFERS fact + child rows (streamed)
# =====================================================================
def _pick_corridor(r, corridor_index):
    send_cur = r.choice(SEND_CURRENCIES)
    recv_country = r.choice(RECEIVE_COUNTRIES)
    recv_cur, rails = RECEIVE_MARKETS[recv_country]
    corridor_id = corridor_index[(send_cur, recv_country)]
    send_country = SEND_COUNTRIES[send_cur][0]
    return send_cur, send_country, recv_country, recv_cur, rails, corridor_id


def _transfer_record(i, corridor_index):
    """Compute the full transfer + derive child rows. Returns a dict of lists."""
    tid = det_uuid(("transfer", i))
    r = rng("transfer", i)
    cm = customer_master()
    customer = cm[r.randrange(len(cm))]
    send_cur, send_country, recv_country, recv_cur, rails, corridor_id = _pick_corridor(r, corridor_index)

    # recipient owned by this same customer is ideal, but cheap approach:
    # reference any recipient id in range; demos join on customer_id anyway.
    recipient_id = r.randint(1, N["recipients"])

    send_amount = round(r.choice([20, 50, 100, 150, 200, 300, 500, 750, 1000,
                                  1500, 2500, 5000]) * (0.5 + r.random()), 2)
    # fee: many corridors fee-free (mobile money), bank ~0.99, some up to 5.99
    rail = r.choice(rails)
    if rail == "Bank":
        fee = round(r.choice([0.99, 1.99, 2.99, 3.99]), 2)
    else:
        fee = 0.0 if r.random() < 0.7 else round(r.choice([0.99, 1.49]), 2)

    mid = round(USD_FX[recv_cur] / USD_FX[send_cur], 8)
    margin_bps = r.choice([50, 75, 100, 125, 150])
    fx_rate = round(mid * (1 - margin_bps / 10000.0), 8)
    receive_amount = round((send_amount - 0) * fx_rate, 2)

    status = r.choice(TRANSFER_STATUSES)
    created = rand_datetime(r, customer.signup_at.date(), EPOCH_END) \
        if customer.signup_at.date() < EPOCH_END else customer.signup_at
    funded = created + dt.timedelta(seconds=r.randint(20, 600))
    completed = funded + dt.timedelta(seconds=r.randint(60, 1200)) \
        if status in ("COMPLETED", "REFUNDED") else None
    updated = completed or funded

    cancel_reason = r.randint(1, len(CANCELLATION_REASONS)) if status == "CANCELLED" else None
    funding_method = r.choice(FUNDING_METHODS)
    is_first = r.random() < 0.18
    promo = maybe_null(r.choice(["WELCOME10", "REFER5", "FEEFREE", "FX0"]), 0.85, r)
    quote_id = det_uuid(("quote", i))
    partner = r.choice(PARTNERS["payout_rail"])

    transfer_row = (
        tid,
        f"NALA-{i:08d}",
        customer.cid, recipient_id, corridor_id,
        send_country, send_cur, recv_country, recv_cur,
        send_amount, receive_amount, fee, send_cur,
        fx_rate, mid, margin_bps,
        status, rail, partner, funding_method, FUNDING_PARTNERS[funding_method],
        promo, cancel_reason, is_first, quote_id,
        ts_isotz(created),
        ts_isotz(funded),
        ts_isotz(completed) if completed else None,
        ts_isotz(updated),
        f"{r.randint(1,223)}.{r.randint(0,255)}.{r.randint(0,255)}.{r.randint(1,254)}",
        json_dumps({"channel": customer.platform, "app_version": r.choice(APP_VERSIONS),
                    "promo": promo}),
    )

    # --- child: legs ---
    legs = []
    leg_defs = [("funding", send_cur, send_cur, FUNDING_PARTNERS[funding_method]),
                ("fx", send_cur, recv_cur, "NALA FX"),
                ("payout", recv_cur, recv_cur, partner)]
    for seq, (ltype, fc, tc, lpartner) in enumerate(leg_defs, start=1):
        amt = send_amount if ltype != "payout" else receive_amount
        lstatus = "SUCCESS" if status == "COMPLETED" else (
            "PENDING" if status == "PENDING" else "FAILED" if (status == "FAILED" and ltype == "payout") else "SUCCESS")
        lstart = created + dt.timedelta(seconds=20 * seq)
        legs.append((
            None, tid, ltype, seq, fc, tc, amt, lpartner,
            f"{lpartner[:3].upper()}-{r.randint(10**6, 10**7)}",
            lstatus, ts_isotz(lstart),
            ts_isotz(lstart + dt.timedelta(seconds=r.randint(10, 300))) if lstatus != "PENDING" else None,
        ))

    # --- child: status history ---
    hist = []
    chain = ["CREATED", "FUNDED"]
    if status == "COMPLETED":
        chain += ["PROCESSING", "COMPLETED"]
    elif status == "FAILED":
        chain += ["PROCESSING", "FAILED"]
    elif status == "CANCELLED":
        chain += ["CANCELLED"]
    elif status == "REFUNDED":
        chain += ["PROCESSING", "COMPLETED", "REFUNDED"]
    else:
        chain += [status]
    prev = None
    for h, st in enumerate(chain):
        hist.append((
            None, tid, prev, st,
            ts_isoz(created + dt.timedelta(seconds=30 * h)),
            r.choice(["system", "partner_webhook", "ops@nala.com"]),
            None,
        ))
        prev = st

    # --- child: fees ---
    fees = [(None, tid, "transfer", fee, send_cur, fee == 0.0, "Transfer fee",
             ts_isotz(created))]
    fx_fee = round(send_amount * margin_bps / 10000.0, 2)
    fees.append((None, tid, "fx_margin", fx_fee, send_cur, False,
                 f"FX margin {margin_bps}bps", ts_isotz(created)))
    if promo:
        fees.append((None, tid, "promo_discount", -round(min(fee, 0.99), 2), send_cur,
                     True, f"Promo {promo}", ts_isotz(created)))

    # --- child: payout attempts ---
    attempts = []
    n_att = 1 if status in ("COMPLETED", "PENDING", "REFUNDED") else r.choice([1, 2, 2, 3])
    target_msisdn = f"{r.randint(700000000,799999999)}" if rail != "Bank" else None
    target_acct = f"{r.randint(10**9,10**10-1)}" if rail == "Bank" else None
    for a in range(1, n_att + 1):
        last = a == n_att
        astatus = ("SUCCESS" if (last and status in ("COMPLETED", "REFUNDED"))
                   else "PENDING" if (last and status == "PENDING")
                   else "FAILED")
        req = funded + dt.timedelta(seconds=120 * a)
        attempts.append((
            None, tid, a, partner, rail,
            f"{partner[:3].upper()}-{r.randint(10**6, 10**7)}",
            target_msisdn, target_acct, astatus,
            "00" if astatus == "SUCCESS" else r.choice(["E51", "TIMEOUT", "INVALID_ACC", "E91"]),
            "Success" if astatus == "SUCCESS" else r.choice(
                ["Insufficient float", "Invalid account", "Timeout", "Recipient barred"]),
            ts_isoz(req),
            ts_isotz(req + dt.timedelta(seconds=r.randint(5, 120))) if astatus != "PENDING" else None,
            json_dumps({"partner": partner, "code": astatus}),
        ))

    # --- quote + fx_quote (one per transfer; some quotes never convert -> built separately) ---
    quote_row = (
        quote_id, customer.cid, send_cur, recv_cur, send_amount, receive_amount,
        fee, fx_rate, rail, True, tid,
        ts_isotz(created - dt.timedelta(seconds=r.randint(10, 300))),
        ts_isotz(created + dt.timedelta(minutes=30)),
    )
    fxq_row = (
        det_uuid(("fxquote", i)), quote_id, send_cur, recv_cur, mid, fx_rate,
        margin_bps, r.choice(["internal", "OpenExchange"]), True,
        ts_epoch_ms(created - dt.timedelta(seconds=r.randint(10, 300))),
        ts_epoch_ms(created + dt.timedelta(minutes=30)),
    )

    # --- promo redemption (only when promo applied) ---
    promo_row = None
    if promo:
        promo_row = (None, customer.cid, tid, promo, r.choice(PROMO_TYPES),
                     round(min(fee, 0.99), 2), send_cur, ts_isotz(created))

    return {"transfer": transfer_row, "legs": legs, "hist": hist, "fees": fees,
            "attempts": attempts, "quote": quote_row, "fxq": fxq_row,
            "promo": promo_row}


def build_referrals(n: int):
    cm = customer_master()
    n_codes = max(50, N["customers"] // 20)
    rows = []
    for i in range(n):
        r = rng("referral", i)
        referrer = cm[r.randrange(len(cm))]
        referee = cm[r.randrange(len(cm))]
        if referee.cid == referrer.cid:
            referee = cm[(referrer.cid + 1) % len(cm)]
        status = r.choice(REFERRAL_STATUSES)
        referred = referrer.signup_at + dt.timedelta(days=r.randint(0, 600))
        rewarded = ts_isotz(referred + dt.timedelta(days=r.randint(1, 30))) if status == "rewarded" else None
        rows.append((
            i + 1, r.randint(1, n_codes), referrer.cid, referee.cid, status,
            round(r.choice([5, 10, 15]) * 1.0, 2), referrer.currency,
            det_uuid(("transfer", r.randrange(N["transfers"]))) if status in ("qualified", "rewarded") else None,
            ts_isotz(referred), rewarded,
        ))
    return rows


# Extra (non-converting) quotes — quotes that never became transfers.
def build_orphan_quotes(n: int):
    cm = customer_master()
    rows = []
    for i in range(n):
        r = rng("orphanquote", i)
        c = cm[r.randrange(len(cm))]
        send_cur = c.currency
        recv_country = r.choice(RECEIVE_COUNTRIES)
        recv_cur, rails = RECEIVE_MARKETS[recv_country]
        send_amount = round(r.choice([50, 100, 200, 500]) * (0.5 + r.random()), 2)
        mid = round(USD_FX[recv_cur] / USD_FX[send_cur], 8)
        margin = r.choice([75, 100, 150])
        fx = round(mid * (1 - margin / 10000.0), 8)
        created = rand_datetime(r, c.signup_at.date(), EPOCH_END) \
            if c.signup_at.date() < EPOCH_END else c.signup_at
        rows.append((
            det_uuid(("orphanquote", i)), c.cid, send_cur, recv_cur,
            send_amount, round(send_amount * fx, 2), 0.0, fx, r.choice(rails),
            False, None,
            ts_isotz(created), ts_isotz(created + dt.timedelta(minutes=30)),
        ))
    return rows


# =====================================================================
# helpers
# =====================================================================
def ts_isotz(d):
    """tz-aware ISO string suitable for a timestamptz column."""
    if d is None:
        return None
    return d.strftime("%Y-%m-%d %H:%M:%S+00")


def json_dumps(obj):
    import json
    return json.dumps(obj)


# =====================================================================
# Streaming loader for the fact + children
# =====================================================================
def _stream_transfers_and_children(conn, corridor_index):
    """COPY-load transfers and all per-transfer child tables in one pass.

    To avoid building a 3M-row Python list per child table, we buffer rows in
    bounded batches and flush each child table's batch via bulk_copy on small
    in-memory chunks.
    """
    import io, csv

    # We use one shared cursor + COPY per table, fed by generator pipes.
    # Simpler + robust: accumulate into per-table buffers, flush at threshold.
    BATCH = 20_000

    tables = {
        "transfers": (TRANSFER_COLS, []),
        "transfer_legs": (LEG_COLS, []),
        "transfer_status_history": (HIST_COLS, []),
        "transfer_fees": (FEE_COLS, []),
        "payout_attempts": (ATTEMPT_COLS, []),
        "quotes": (QUOTE_COLS, []),
        "fx_quotes": (FXQ_COLS, []),
        "promo_redemptions": (PROMO_COLS, []),
    }
    # serial counters for child surrogate keys
    counters = {"leg": 0, "hist": 0, "fee": 0, "attempt": 0, "promo": 0}

    def flush(name, force=False):
        cols, buf = tables[name]
        if buf and (force or len(buf) >= BATCH):
            bulk_copy(conn, f"{SCHEMA}.{name}", cols, buf)
            buf.clear()

    total = 0
    for i in range(N["transfers"]):
        rec = _transfer_record(i, corridor_index)
        tables["transfers"][1].append(rec["transfer"])
        for leg in rec["legs"]:
            counters["leg"] += 1
            tables["transfer_legs"][1].append((counters["leg"],) + leg[1:])
        for h in rec["hist"]:
            counters["hist"] += 1
            tables["transfer_status_history"][1].append((counters["hist"],) + h[1:])
        for fe in rec["fees"]:
            counters["fee"] += 1
            tables["transfer_fees"][1].append((counters["fee"],) + fe[1:])
        for at in rec["attempts"]:
            counters["attempt"] += 1
            tables["payout_attempts"][1].append((counters["attempt"],) + at[1:])
        tables["quotes"][1].append(rec["quote"])
        tables["fx_quotes"][1].append(rec["fxq"])
        if rec["promo"]:
            counters["promo"] += 1
            tables["promo_redemptions"][1].append((counters["promo"],) + rec["promo"][1:])

        total += 1
        if total % BATCH == 0:
            for name in tables:
                flush(name)

    for name in tables:
        flush(name, force=True)
    return total


# Column orders (must match DDL + tuple construction) -----------------
TRANSFER_COLS = ["transfer_id", "reference", "customer_id", "recipient_id",
                 "corridor_id", "send_country", "send_currency", "receive_country",
                 "receive_currency", "send_amount", "receive_amount", "fee_amount",
                 "fee_currency", "fx_rate", "mid_market_rate", "fx_margin_bps",
                 "status", "rail", "payout_partner", "funding_method", "funding_partner",
                 "promo_code", "cancellation_reason_id", "is_first_transfer", "quote_id",
                 "created_at", "funded_at", "completed_at", "updated_at", "source_ip",
                 "raw_payload"]
LEG_COLS = ["leg_id", "transfer_id", "leg_type", "sequence_no", "from_currency",
            "to_currency", "amount", "partner", "partner_reference", "status",
            "started_at", "finished_at"]
HIST_COLS = ["status_event_id", "transfer_id", "from_status", "to_status",
             "changed_at", "changed_by", "note"]
FEE_COLS = ["fee_id", "transfer_id", "fee_type", "amount", "currency", "is_waived",
            "description", "created_at"]
ATTEMPT_COLS = ["attempt_id", "transfer_id", "attempt_no", "partner", "rail",
                "partner_reference", "msisdn", "account_number", "status",
                "response_code", "response_message", "requested_at", "completed_at",
                "raw_response"]
QUOTE_COLS = ["quote_id", "customer_id", "send_currency", "receive_currency",
              "send_amount", "receive_amount", "fee_amount", "fx_rate", "rail",
              "converted", "transfer_id", "created_at", "expires_at"]
FXQ_COLS = ["fx_quote_id", "quote_id", "base_currency", "quote_currency",
            "mid_market_rate", "customer_rate", "margin_bps", "rate_source",
            "locked", "created", "valid_until"]
PROMO_COLS = ["redemption_id", "customer_id", "transfer_id", "promo_code",
              "promo_type", "discount_amount", "discount_currency", "redeemed_at"]


# =====================================================================
# main
# =====================================================================
def main(conn):
    ensure_schema(conn, SCHEMA)
    apply_ddl_file(conn, DDL)

    tbls = ["corridors", "cancellation_reasons", "referral_codes", "customers",
            "customer_addresses", "customer_devices", "customer_kyc_status",
            "recipients", "recipient_payout_methods", "saved_recipients",
            "transfers", "transfer_legs", "transfer_status_history",
            "transfer_fees", "quotes", "fx_quotes", "payout_attempts",
            "promo_redemptions", "referrals"]
    truncate(conn, *[f"{SCHEMA}.{t}" for t in tbls])

    # ---- lookups ----
    corridors, corridor_index = build_corridors()
    bulk_copy(conn, f"{SCHEMA}.corridors",
              ["corridor_id", "corridor_code", "send_country", "send_currency",
               "receive_country", "receive_currency", "default_rail", "is_active",
               "launched_on", "created_at"], corridors)
    bulk_copy(conn, f"{SCHEMA}.cancellation_reasons",
              ["reason_id", "reason_code", "reason_label", "category", "is_user_facing"],
              build_cancellation_reasons())
    n_codes = max(50, N["customers"] // 20)
    bulk_copy(conn, f"{SCHEMA}.referral_codes",
              ["referral_code_id", "code", "owner_cid", "reward_amount",
               "reward_currency", "max_redemptions", "times_redeemed", "is_active",
               "created_at", "expires_at"], build_referral_codes(n_codes))

    # ---- customers + subtables ----
    bulk_copy(conn, f"{SCHEMA}.customers",
              ["customer_id", "customer_uuid", "customer_code", "first_name",
               "last_name", "email", "phone", "date_of_birth", "country", "currency",
               "national_id", "national_id_hash", "kyc_tier", "account_status",
               "signup_platform", "signup_country", "marketing_opt_in", "is_deleted",
               "deleted_at", "created_at", "updated_at", "raw_attributes"],
              build_customers())
    bulk_copy(conn, f"{SCHEMA}.customer_addresses",
              ["address_id", "customer_id", "address_type", "line1", "line2", "city",
               "postcode", "country", "is_primary", "verified", "created"],
              build_customer_addresses())
    bulk_copy(conn, f"{SCHEMA}.customer_devices",
              ["device_id", "customer_id", "platform", "app_version", "os_version",
               "device_model", "push_token", "ip_address", "last_seen_at",
               "is_trusted", "first_seen_epoch_ms"], build_customer_devices())
    bulk_copy(conn, f"{SCHEMA}.customer_kyc_status",
              ["kyc_status_id", "customer_id", "provider", "tier", "status",
               "risk_rating", "submitted_at", "decided_at", "document_type",
               "document_number", "is_current"], build_kyc_status())

    # ---- recipients ----
    bulk_copy(conn, f"{SCHEMA}.recipients",
              ["recipient_id", "recipient_uuid", "customer_id", "first_name",
               "last_name", "full_name", "receive_country", "receive_currency",
               "relationship", "phone", "email", "date_of_birth", "is_active",
               "is_deleted", "created_at", "updated_at"], build_recipients())
    bulk_copy(conn, f"{SCHEMA}.recipient_payout_methods",
              ["payout_method_id", "recipient_id", "method_type", "rail", "provider",
               "msisdn", "bank_name", "account_number", "account_name", "iban",
               "swift_bic", "is_default", "is_verified", "created_at"],
              build_payout_methods())
    bulk_copy(conn, f"{SCHEMA}.saved_recipients",
              ["id", "user_id", "name", "country", "currency", "mobile", "acct_no",
               "payment_type", "created", "updated", "deleted", "migrated_recipient_id"],
              build_saved_recipients())

    # ---- transfers fact + children (streamed) ----
    n_transfers = _stream_transfers_and_children(conn, corridor_index)

    # ---- orphan (non-converting) quotes appended after converted ones ----
    n_orphans = max(100, N["transfers"] // 10)
    bulk_copy(conn, f"{SCHEMA}.quotes", QUOTE_COLS, build_orphan_quotes(n_orphans))

    # ---- referrals ----
    n_referrals = max(100, N["customers"] // 4)
    bulk_copy(conn, f"{SCHEMA}.referrals",
              ["referral_id", "referral_code_id", "referrer_cid", "referee_cid",
               "status", "reward_amount", "reward_currency", "qualifying_transfer_id",
               "referred_at", "rewarded_at"], build_referrals(n_referrals))

    print(f"[raw_core_transfers] loaded {n_transfers} transfers "
          f"(+ legs/history/fees/attempts/quotes), scale={SCALE}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
