"""
NALA warehouse — shared generation contract.

EVERY generator script imports from this module. It is the single source of
truth for:
  * the connection (reads warehouse/.env)
  * global population sizes + the date range (scale-aware)
  * the canonical reference data (currencies, countries, corridors, partners)
  * DETERMINISTIC identity helpers so the SAME canonical customer_id produces
    the SAME email / phone / name / dob across every source system (this is what
    makes cross-source identity-resolution demos possible) — while still being
    realistically messy (typos, nulls, casing drift, format drift).
  * a fast CSV/COPY bulk loader.

Do NOT hardcode connection details or row counts in individual generators.
Pull everything from here.
"""
from __future__ import annotations

import csv
import io
import os
import random
import functools
import datetime as dt
from pathlib import Path

import psycopg2
from faker import Faker

# --------------------------------------------------------------------------
# Config / scale
# --------------------------------------------------------------------------
_ENV = Path(__file__).resolve().parent.parent / ".env"
if _ENV.exists():
    for line in _ENV.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

SCALE = os.environ.get("NALA_SCALE", "demo").lower()

# Row counts by scale tier. "demo" ~ a few GB, minutes to load.
_SCALES = {
    # Tiny tier for subagent self-validation (loads in seconds).
    "test": {
        "customers":    500,
        "recipients":   1_000,
        "merchants":    40,
        "transfers":    6_000,
        "events":       9_000,
        "ledger_lines": 14_000,
    },
    "demo": {
        "customers":    60_000,
        "recipients":   120_000,
        "merchants":    1_200,      # Rafiki B2B
        "transfers":    3_000_000,  # the primary fact
        "events":       5_000_000,  # segment/amplitude product events
        "ledger_lines": 8_000_000,
    },
    "large": {
        "customers":    500_000,
        "recipients":   1_000_000,
        "merchants":    8_000,
        "transfers":    25_000_000,
        "events":       60_000_000,
        "ledger_lines": 70_000_000,
    },
}
N = _SCALES.get(SCALE, _SCALES["demo"])

# Years of history — NALA's international remittance era through "today".
EPOCH_START = dt.date(2018, 1, 1)
EPOCH_END = dt.date(2026, 6, 18)
GLOBAL_SEED = 42

# --------------------------------------------------------------------------
# Reference data — real-world currencies / countries / partners NALA uses
# --------------------------------------------------------------------------
# Send-from (debit) currencies and their countries.
SEND_CURRENCIES = ["GBP", "USD", "EUR"]
SEND_COUNTRIES = {
    "GBP": ["GB"],
    "USD": ["US"],
    "EUR": ["IE", "FR", "DE", "ES", "IT", "NL", "BE", "PT", "AT", "FI",
            "GR", "LU", "MT", "CY", "EE", "LV", "LT", "SK", "SI"],
}

# Receive (credit) markets: country -> (currency, [mobile_money_or_bank rails])
RECEIVE_MARKETS = {
    "KE": ("KES", ["M-PESA", "Airtel Money", "Bank"]),
    "TZ": ("TZS", ["M-PESA", "Tigo Pesa", "Airtel Money", "Bank"]),
    "UG": ("UGX", ["MTN MoMo", "Airtel Money", "Bank"]),
    "RW": ("RWF", ["MTN MoMo", "Airtel Money", "Bank"]),
    "NG": ("NGN", ["Bank", "OPay", "PalmPay"]),
    "GH": ("GHS", ["MTN MoMo", "Vodafone Cash", "Bank"]),
    "SN": ("XOF", ["Wave", "Orange Money", "Bank"]),
    "CI": ("XOF", ["Wave", "Orange Money", "MTN MoMo", "Bank"]),
    "CM": ("XAF", ["MTN MoMo", "Orange Money", "Bank"]),
    "GA": ("XAF", ["Airtel Money", "Bank"]),
    "CG": ("XAF", ["MTN MoMo", "Airtel Money", "Bank"]),
    "ZA": ("ZAR", ["Bank", "Capitec Pay"]),
    "IN": ("INR", ["Bank", "UPI"]),
    "PK": ("PKR", ["Bank", "Easypaisa", "JazzCash"]),
    "BD": ("BDT", ["bKash", "Nagad", "Bank"]),
    "PH": ("PHP", ["GCash", "PayMaya", "Bank"]),
}
RECEIVE_COUNTRIES = list(RECEIVE_MARKETS.keys())
STABLECOINS = ["USDC", "USDT", "PYUSD"]

# Approx indicative FX (per 1 USD) for plausible amounts. Not for accuracy.
USD_FX = {
    "USD": 1.0, "GBP": 0.79, "EUR": 0.92, "KES": 129.0, "TZS": 2600.0,
    "UGX": 3750.0, "RWF": 1330.0, "NGN": 1550.0, "GHS": 15.3, "XOF": 605.0,
    "XAF": 605.0, "ZAR": 18.4, "INR": 83.3, "PKR": 278.0, "BDT": 117.0,
    "PHP": 58.0, "USDC": 1.0, "USDT": 1.0, "PYUSD": 1.0,
}

# Real partner/vendor names per source system (used as enum-ish values).
PARTNERS = {
    "kyc": ["Onfido", "Jumio", "Persona"],
    "aml": ["ComplyAdvantage", "Refinitiv World-Check"],
    "crypto_compliance": ["Chainalysis", "Elliptic"],
    "payout_rail": ["Flutterwave", "Cellulant", "Onafriq", "Thunes",
                    "MFS Africa", "MoneyGram"],
    "funding": ["Stripe", "Plaid", "TrueLayer", "Marqeta"],
    "custody": ["Fireblocks", "Circle", "Copper"],
    "messaging": ["Twilio", "SendGrid", "Braze", "Iterable"],
    "analytics": ["Segment", "Amplitude", "AppsFlyer", "Mixpanel"],
    "support": ["Zendesk", "Intercom"],
    "erp": ["NetSuite", "QuickBooks"],
    "hr": ["Workday", "BambooHR"],
}

DEVICE_PLATFORMS = ["ios", "android", "web"]
APP_VERSIONS = ["3.4.1", "3.5.0", "3.6.2", "4.0.0", "4.1.3", "4.2.0", "4.3.1"]

# --------------------------------------------------------------------------
# Connection + schema helpers
# --------------------------------------------------------------------------
def connect():
    return psycopg2.connect(
        host=os.environ.get("NALA_PGHOST", "localhost"),
        port=os.environ.get("NALA_PGPORT", "5602"),
        user=os.environ.get("NALA_PGUSER", "nala"),
        password=os.environ.get("NALA_PGPASSWORD", "nala_dev_only"),
        dbname=os.environ.get("NALA_PGDATABASE", "nala_warehouse"),
    )


def ensure_schema(conn, schema: str):
    with conn.cursor() as cur:
        cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}";')
    conn.commit()


def run_sql(conn, sql: str):
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def apply_ddl_file(conn, path):
    """Execute a .sql DDL file (CREATE SCHEMA / CREATE TABLE ...)."""
    sql = Path(path).read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def truncate(conn, *tables):
    with conn.cursor() as cur:
        for t in tables:
            cur.execute(f"TRUNCATE {t} CASCADE;")
    conn.commit()


# --------------------------------------------------------------------------
# Bulk loader — CSV over COPY. Pass rows as an iterable of tuples/lists.
# None -> SQL NULL. Handles batching so multi-million-row loads stay bounded.
# --------------------------------------------------------------------------
def bulk_copy(conn, table: str, columns: list[str], rows, batch: int = 50_000):
    cols = ", ".join(f'"{c}"' for c in columns)
    copy_sql = (
        f'COPY {table} ({cols}) FROM STDIN '
        f"WITH (FORMAT csv, NULL '\\N')"
    )
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    total = 0
    n = 0
    with conn.cursor() as cur:
        for row in rows:
            writer.writerow(["\\N" if v is None else v for v in row])
            n += 1
            if n >= batch:
                buf.seek(0)
                cur.copy_expert(copy_sql, buf)
                total += n
                buf.seek(0); buf.truncate(0); n = 0
        if n:
            buf.seek(0)
            cur.copy_expert(copy_sql, buf)
            total += n
    conn.commit()
    return total


# --------------------------------------------------------------------------
# Determinism + messiness
# --------------------------------------------------------------------------
def rng(*parts) -> random.Random:
    """A reproducible RNG keyed by any tuple of parts (e.g. customer_id)."""
    return random.Random(hash((GLOBAL_SEED, *parts)) & 0xFFFFFFFF)


def faker_for(seed_part) -> Faker:
    f = Faker()
    Faker.seed(hash((GLOBAL_SEED, seed_part)) & 0xFFFFFFFF)
    return f


def maybe_null(value, p: float, r: random.Random):
    """Return None with probability p — for realistic sparse columns."""
    return None if r.random() < p else value


def dirty_email(email: str, r: random.Random) -> str:
    """Occasionally introduce casing / dot / typo drift across source systems."""
    if email is None:
        return None
    roll = r.random()
    if roll < 0.12:
        return email.upper()
    if roll < 0.20:
        local, _, dom = email.partition("@")
        return f"{local}.{dom}".replace(f".{dom}", f"@{dom}") if dom else email
    if roll < 0.24 and "@" in email:  # a leading/trailing space — classic dirty data
        return f" {email} "
    return email


def dirty_phone(e164: str, r: random.Random) -> str:
    """Same number, drifting format across systems (E.164 / spaces / 00 prefix)."""
    if e164 is None:
        return None
    roll = r.random()
    if roll < 0.25:
        return e164.replace("+", "00")
    if roll < 0.40:
        return e164.lstrip("+")
    if roll < 0.50:
        return f"{e164[:4]} {e164[4:7]} {e164[7:]}"
    return e164


# Timestamp format drift — different source systems store time differently.
def ts_iso(d: dt.datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M:%S")


def ts_isoz(d: dt.datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def ts_epoch_ms(d: dt.datetime) -> int:
    return int(d.replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def ts_epoch_s(d: dt.datetime) -> int:
    return int(d.replace(tzinfo=dt.timezone.utc).timestamp())


def rand_datetime(r: random.Random, start: dt.date = EPOCH_START,
                  end: dt.date = EPOCH_END) -> dt.datetime:
    """A datetime in [start, end), weighted later (the business grew over time)."""
    span = (end - start).days
    # Square the uniform draw so recent dates are more common.
    frac = 1.0 - (r.random() ** 2)
    day = int(frac * span)
    return dt.datetime.combine(start + dt.timedelta(days=day), dt.time()) + \
        dt.timedelta(seconds=r.randint(0, 86399))


# --------------------------------------------------------------------------
# Canonical customer master — built once per process, deterministically.
# Index by canonical_id in [0, N["customers"]). Source systems reference the
# representation that's natural for them (int id, "CUS_000123", or uuid).
# --------------------------------------------------------------------------
class Customer:
    __slots__ = ("cid", "uuid", "code", "first", "last", "email", "phone",
                 "dob", "country", "currency", "city", "postcode", "street",
                 "signup_at", "platform")

    def __init__(self, cid: int):
        r = rng("customer", cid)
        f = faker_for(("customer", cid))
        self.cid = cid
        self.uuid = _det_uuid(("customer", cid))
        self.code = f"CUS_{cid:08d}"
        self.first = f.first_name()
        self.last = f.last_name()
        cur = r.choice(SEND_CURRENCIES)
        self.currency = cur
        self.country = r.choice(SEND_COUNTRIES[cur])
        self.email = f"{self.first}.{self.last}{r.randint(1, 999)}@{r.choice(['gmail.com','yahoo.com','outlook.com','icloud.com','hotmail.com'])}".lower()
        cc = {"GB": "+44", "US": "+1"}.get(self.country, "+33")
        self.phone = f"{cc}{r.randint(7000000000, 7999999999)}"
        self.dob = f.date_of_birth(minimum_age=18, maximum_age=75).isoformat()
        self.city = f.city()
        self.postcode = f.postcode()
        self.street = f.street_address()
        self.signup_at = rand_datetime(r)
        self.platform = r.choice(DEVICE_PLATFORMS)


def _det_uuid(parts) -> str:
    r = rng("uuid", *parts if isinstance(parts, tuple) else (parts,))
    hx = "%032x" % r.getrandbits(128)
    return f"{hx[:8]}-{hx[8:12]}-{hx[12:16]}-{hx[16:20]}-{hx[20:]}"


det_uuid = _det_uuid


@functools.lru_cache(maxsize=1)
def customer_master() -> list[Customer]:
    """Full canonical customer population. Stable across processes via seeds."""
    return [Customer(i) for i in range(N["customers"])]


def random_customer(r: random.Random) -> Customer:
    return customer_master()[r.randrange(N["customers"])]


if __name__ == "__main__":
    # Smoke test
    c = connect()
    print("connected:", c.dsn)
    cm = customer_master()
    print("scale:", SCALE, "| customers:", len(cm))
    print("sample:", cm[0].code, cm[0].email, cm[0].country, cm[0].phone)
    print("same id same email (determinism):", Customer(0).email == cm[0].email)
    c.close()
