"""
Generate fake data for the Analytics Warehouse (Snowflake-style star schema).
Populates dimension and fact tables with realistic enterprise analytics data.
"""

import random
import uuid
from datetime import datetime, timedelta, date

from faker import Faker

from .config import (
    BATCH_SIZE, COUNTS, SEGMENTS, LOYALTY_TIERS, DEPARTMENTS,
    CATEGORIES, SUBCATEGORIES, BRANDS, EVENT_TYPES, DEVICE_TYPES,
    BROWSERS, US_STATES, REGIONS, CHANNELS,
)
from .db import copy_rows, ProgressTracker

fake = Faker()
Faker.seed(42)
random.seed(42)

START_DATE = date(2016, 1, 1)
END_DATE = date(2026, 3, 31)


# ── Dimension: Dates ────────────────────────────────────────────────────────

def generate_dim_dates(conn):
    """Generate date dimension spanning START_DATE to END_DATE."""
    columns = [
        "date_key", "full_date", "year", "quarter", "month", "month_name",
        "week_of_year", "day_of_month", "day_of_week", "day_name",
        "is_weekend", "is_holiday", "fiscal_year", "fiscal_quarter",
    ]
    holidays = {
        (1, 1), (7, 4), (12, 25), (12, 31), (11, 24), (11, 25),
        (1, 15), (2, 19), (5, 27), (9, 4), (10, 9), (11, 11),
    }
    rows = []
    current = START_DATE
    while current <= END_DATE:
        date_key = int(current.strftime("%Y%m%d"))
        q = (current.month - 1) // 3 + 1
        fiscal_year = current.year if current.month >= 2 else current.year - 1
        fiscal_q = ((current.month - 2) % 12) // 3 + 1

        rows.append((
            date_key,
            current.isoformat(),
            current.year,
            q,
            current.month,
            current.strftime("%B"),
            current.isocalendar()[1],
            current.day,
            current.isoweekday(),
            current.strftime("%A"),
            current.isoweekday() >= 6,
            (current.month, current.day) in holidays,
            fiscal_year,
            fiscal_q,
        ))
        current += timedelta(days=1)

    copy_rows(conn, "analytics.dim_date", columns, rows)
    print(f"  dim_date: {len(rows)} rows")
    return [r[0] for r in rows]  # return date_keys for fact tables


# ── Dimension: Channels ────────────────────────────────────────────────────

def generate_dim_channels(conn):
    columns = ["channel_name", "channel_type", "region", "country", "is_active"]
    rows = [(name, ctype, region, country, True) for name, ctype, region, country in CHANNELS]
    copy_rows(conn, "analytics.dim_channel", columns, rows)
    print(f"  dim_channel: {len(rows)} rows")
    return len(rows)


# ── Dimension: Customers ───────────────────────────────────────────────────

def generate_dim_customers(conn):
    total = COUNTS.dim_customers
    progress = ProgressTracker("dim_customer", total)
    columns = [
        "customer_id", "first_name", "last_name", "email", "segment",
        "region", "country", "state", "city", "loyalty_tier",
        "lifetime_value", "first_order_date", "last_order_date",
        "total_orders", "is_churned",
    ]
    batch = []
    for i in range(1, total + 1):
        ltv = round(random.lognormvariate(6.5, 1.5), 2)
        ltv = max(0, min(ltv, 500000))
        first_order = START_DATE + timedelta(days=random.randint(0, (END_DATE - START_DATE).days))
        last_order = first_order + timedelta(days=random.randint(0, (END_DATE - first_order).days))
        churned = (END_DATE - last_order).days > 180

        batch.append((
            i,
            fake.first_name(),
            fake.last_name(),
            f"cust{i}@{fake.free_email_domain()}",
            random.choice(SEGMENTS),
            random.choice(REGIONS),
            "US" if random.random() < 0.6 else random.choice(["CA", "GB", "DE", "JP", "AU", "FR", "BR"]),
            random.choice(US_STATES),
            fake.city()[:100],
            random.choice(LOYALTY_TIERS),
            ltv,
            first_order.isoformat(),
            last_order.isoformat(),
            random.randint(1, 200),
            churned,
        ))

        if len(batch) >= BATCH_SIZE:
            copy_rows(conn, "analytics.dim_customer", columns, batch)
            progress.advance(len(batch))
            batch = []

    if batch:
        copy_rows(conn, "analytics.dim_customer", columns, batch)
        progress.advance(len(batch))
    progress.done()


# ── Dimension: Products ────────────────────────────────────────────────────

def generate_dim_products(conn):
    total = COUNTS.dim_products
    progress = ProgressTracker("dim_product", total)
    columns = [
        "product_id", "sku", "name", "category", "subcategory", "brand",
        "unit_price", "unit_cost", "margin_pct", "is_active",
    ]
    batch = []
    for i in range(1, total + 1):
        cat = random.choice(CATEGORIES)
        subcats = SUBCATEGORIES.get(cat, ["General"])
        price = round(random.lognormvariate(3.5, 1.2), 2)
        price = max(0.99, min(price, 9999.99))
        cost = round(price * random.uniform(0.2, 0.7), 2)
        margin = round((price - cost) / price * 100, 2) if price > 0 else 0

        batch.append((
            i,
            f"SKU-{i:06d}",
            f"{fake.word().title()} {random.choice(subcats)}"[:255],
            cat,
            random.choice(subcats),
            random.choice(BRANDS),
            price,
            cost,
            margin,
            random.random() > 0.05,
        ))

        if len(batch) >= BATCH_SIZE:
            copy_rows(conn, "analytics.dim_product", columns, batch)
            progress.advance(len(batch))
            batch = []

    if batch:
        copy_rows(conn, "analytics.dim_product", columns, batch)
        progress.advance(len(batch))
    progress.done()


# ── Dimension: Employees ───────────────────────────────────────────────────

def generate_dim_employees(conn):
    total = COUNTS.dim_employees
    progress = ProgressTracker("dim_employee", total)
    columns = [
        "employee_id", "full_name", "department", "title", "region",
        "hire_date", "is_active",
    ]
    batch = []
    for i in range(1, total + 1):
        hire = START_DATE + timedelta(days=random.randint(0, (END_DATE - START_DATE).days - 90))
        batch.append((
            i,
            f"{fake.first_name()} {fake.last_name()}",
            random.choice(DEPARTMENTS),
            fake.job()[:150],
            random.choice(REGIONS),
            hire.isoformat(),
            random.random() > 0.08,
        ))

        if len(batch) >= BATCH_SIZE:
            copy_rows(conn, "analytics.dim_employee", columns, batch)
            progress.advance(len(batch))
            batch = []

    if batch:
        copy_rows(conn, "analytics.dim_employee", columns, batch)
        progress.advance(len(batch))
    progress.done()


# ── Fact: Sales ─────────────────────────────────────────────────────────────

def generate_fact_sales(conn, date_keys: list[int]):
    total = COUNTS.fact_sales
    max_cust = COUNTS.dim_customers
    max_prod = COUNTS.dim_products
    max_emp = COUNTS.dim_employees
    max_channel = len(CHANNELS)
    progress = ProgressTracker("fact_sales", total)
    columns = [
        "date_key", "customer_key", "product_key", "employee_key",
        "channel_key", "order_id", "quantity", "unit_price",
        "discount_amount", "revenue", "cost", "profit", "tax", "shipping",
    ]
    batch = []
    for i in range(1, total + 1):
        qty = random.choices([1, 2, 3, 4, 5, 10, 20], weights=[40, 25, 15, 8, 5, 4, 3])[0]
        price = round(random.lognormvariate(3.5, 1.0), 2)
        price = max(0.99, min(price, 5000.0))
        discount = round(price * qty * random.choice([0, 0, 0, 0.05, 0.1, 0.15, 0.2]), 2)
        revenue = round(qty * price - discount, 2)
        cost = round(revenue * random.uniform(0.3, 0.7), 2)
        profit = round(revenue - cost, 2)
        tax = round(revenue * random.uniform(0.05, 0.12), 2)
        shipping = round(random.uniform(0, 15), 2) if revenue < 100 else 0

        batch.append((
            random.choice(date_keys),
            random.randint(1, max_cust),
            random.randint(1, max_prod),
            random.randint(1, max_emp),
            random.randint(1, max_channel),
            random.randint(1, 10_000_000),
            qty,
            price,
            discount,
            revenue,
            cost,
            profit,
            tax,
            shipping,
        ))

        if len(batch) >= BATCH_SIZE:
            copy_rows(conn, "analytics.fact_sales", columns, batch)
            progress.advance(len(batch))
            batch = []

    if batch:
        copy_rows(conn, "analytics.fact_sales", columns, batch)
        progress.advance(len(batch))
    progress.done()


# ── Fact: Web Events ────────────────────────────────────────────────────────

def generate_fact_web_events(conn, date_keys: list[int]):
    total = COUNTS.fact_web_events
    max_cust = COUNTS.dim_customers
    progress = ProgressTracker("fact_web_events", total)
    columns = [
        "date_key", "customer_key", "session_id", "event_type", "page_url",
        "referrer", "device_type", "browser", "country", "duration_sec",
        "is_bounce", "is_conversion", "revenue",
    ]
    pages = [
        "/", "/products", "/products/category", "/product/detail",
        "/cart", "/checkout", "/checkout/payment", "/checkout/confirm",
        "/account", "/account/orders", "/search", "/about", "/contact",
        "/blog", "/blog/post", "/pricing", "/docs", "/support",
    ]
    referrers = [
        "https://google.com", "https://bing.com", None, None,
        "https://facebook.com", "https://twitter.com", "https://linkedin.com",
        "https://reddit.com", None, "https://youtube.com",
    ]
    batch = []
    for i in range(1, total + 1):
        event_type = random.choice(EVENT_TYPES)
        is_conversion = event_type == "checkout_complete"
        revenue = round(random.lognormvariate(4.0, 1.0), 2) if is_conversion else 0

        batch.append((
            random.choice(date_keys),
            random.randint(1, max_cust) if random.random() < 0.7 else None,
            uuid.uuid4().hex[:16],
            event_type,
            random.choice(pages),
            random.choice(referrers),
            random.choice(DEVICE_TYPES),
            random.choice(BROWSERS),
            random.choice(["US", "US", "US", "GB", "DE", "JP", "CA", "AU", "FR", "BR"]),
            random.randint(1, 600),
            random.random() < 0.35,
            is_conversion,
            revenue,
        ))

        if len(batch) >= BATCH_SIZE:
            copy_rows(conn, "analytics.fact_web_events", columns, batch)
            progress.advance(len(batch))
            batch = []

    if batch:
        copy_rows(conn, "analytics.fact_web_events", columns, batch)
        progress.advance(len(batch))
    progress.done()


# ── Fact: Inventory ─────────────────────────────────────────────────────────

def generate_fact_inventory(conn, date_keys: list[int]):
    total = COUNTS.fact_inventory
    max_prod = COUNTS.dim_products
    progress = ProgressTracker("fact_inventory", total)
    columns = [
        "date_key", "product_key", "warehouse_id", "quantity_on_hand",
        "quantity_reserved", "quantity_on_order", "days_of_supply",
        "is_below_reorder",
    ]
    batch = []
    for i in range(1, total + 1):
        on_hand = random.randint(0, 5000)
        reserved = random.randint(0, min(on_hand, 500))
        on_order = random.randint(0, 2000) if on_hand < 100 else 0
        dos = round(on_hand / max(1, random.randint(1, 50)), 1)

        batch.append((
            random.choice(date_keys),
            random.randint(1, max_prod),
            random.randint(1, 8),
            on_hand,
            reserved,
            on_order,
            dos,
            on_hand < random.randint(10, 100),
        ))

        if len(batch) >= BATCH_SIZE:
            copy_rows(conn, "analytics.fact_inventory", columns, batch)
            progress.advance(len(batch))
            batch = []

    if batch:
        copy_rows(conn, "analytics.fact_inventory", columns, batch)
        progress.advance(len(batch))
    progress.done()


# ── Raw: Customer Events ───────────────────────────────────────────────────

def generate_raw_events(conn, date_keys: list[int]):
    total = COUNTS.raw_customer_events
    max_cust = COUNTS.dim_customers
    progress = ProgressTracker("raw.customer_events", total)
    columns = [
        "event_timestamp", "event_type", "customer_id", "session_id",
        "page_url", "device_type", "browser", "os", "ip_address",
        "country_code", "city", "utm_source", "utm_medium", "utm_campaign",
    ]
    utm_sources = ["google", "facebook", "twitter", "email", "direct", None, None]
    utm_mediums = ["cpc", "organic", "social", "email", "referral", None]
    oses = ["Windows 11", "macOS 14", "iOS 17", "Android 14", "Linux", "ChromeOS"]
    batch = []
    for i in range(1, total + 1):
        # Generate a realistic timestamp
        dk = random.choice(date_keys)
        year = dk // 10000
        month = (dk % 10000) // 100
        day = dk % 100
        try:
            ts = datetime(year, month, day, random.randint(0, 23),
                          random.randint(0, 59), random.randint(0, 59))
        except ValueError:
            ts = datetime(year, month, 1, 12, 0, 0)

        batch.append((
            ts.isoformat(),
            random.choice(EVENT_TYPES),
            random.randint(1, max_cust) if random.random() < 0.65 else None,
            uuid.uuid4().hex[:16],
            f"/{fake.uri_path()}",
            random.choice(DEVICE_TYPES),
            random.choice(BROWSERS),
            random.choice(oses),
            f"{random.randint(10,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}",
            random.choice(["US", "US", "GB", "DE", "JP", "CA", "AU", "FR"]),
            fake.city()[:100],
            random.choice(utm_sources),
            random.choice(utm_mediums),
            f"campaign_{random.randint(1, 500)}" if random.random() < 0.3 else None,
        ))

        if len(batch) >= BATCH_SIZE:
            copy_rows(conn, "raw.customer_events", columns, batch)
            progress.advance(len(batch))
            batch = []

    if batch:
        copy_rows(conn, "raw.customer_events", columns, batch)
        progress.advance(len(batch))
    progress.done()


# ── Raw: Transactions ───────────────────────────────────────────────────────

def generate_raw_transactions(conn, date_keys: list[int]):
    total = COUNTS.raw_transactions
    max_cust = COUNTS.dim_customers
    max_prod = COUNTS.dim_products
    progress = ProgressTracker("raw.transactions", total)
    columns = [
        "txn_timestamp", "order_id", "customer_id", "product_id",
        "quantity", "revenue", "cost", "discount", "payment_method",
        "channel", "store_id",
    ]
    payment_methods = ["credit_card", "debit_card", "bank_transfer", "paypal", "apple_pay"]
    channels_list = ["web", "mobile", "retail", "partner", "wholesale"]
    batch = []
    for i in range(1, total + 1):
        dk = random.choice(date_keys)
        year = dk // 10000
        month = (dk % 10000) // 100
        day = dk % 100
        try:
            ts = datetime(year, month, day, random.randint(6, 23),
                          random.randint(0, 59), random.randint(0, 59))
        except ValueError:
            ts = datetime(year, month, 1, 12, 0, 0)

        qty = random.choices([1, 2, 3, 5, 10], weights=[50, 25, 12, 8, 5])[0]
        revenue = round(random.lognormvariate(3.5, 1.0) * qty, 2)
        revenue = max(0.99, min(revenue, 50000))
        cost = round(revenue * random.uniform(0.3, 0.65), 2)
        discount = round(revenue * random.choice([0, 0, 0, 0.05, 0.1, 0.15]), 2)

        batch.append((
            ts.isoformat(),
            random.randint(1, 10_000_000),
            random.randint(1, max_cust),
            random.randint(1, max_prod),
            qty,
            revenue,
            cost,
            discount,
            random.choice(payment_methods),
            random.choice(channels_list),
            random.randint(1, 50) if random.random() < 0.3 else None,
        ))

        if len(batch) >= BATCH_SIZE:
            copy_rows(conn, "raw.transactions", columns, batch)
            progress.advance(len(batch))
            batch = []

    if batch:
        copy_rows(conn, "raw.transactions", columns, batch)
        progress.advance(len(batch))
    progress.done()


# ── ML: Customer Features & Churn Predictions ──────────────────────────────

def generate_ml_tables(conn):
    # Customer features
    total = COUNTS.ml_customer_features
    progress = ProgressTracker("ml.customer_features", total)
    columns = [
        "customer_id", "recency_days", "frequency", "monetary_value",
        "avg_order_value", "order_count_30d", "order_count_90d",
        "page_views_30d", "sessions_30d", "support_tickets_90d",
        "churn_score", "ltv_predicted", "segment_cluster",
    ]
    batch = []
    for i in range(1, total + 1):
        monetary = round(random.lognormvariate(6.0, 1.5), 2)
        freq = random.randint(1, 200)
        aov = round(monetary / max(freq, 1), 2)
        churn = round(random.betavariate(2, 5), 4)

        batch.append((
            i,
            random.randint(0, 730),
            freq,
            monetary,
            aov,
            random.randint(0, 15),
            random.randint(0, 40),
            random.randint(0, 500),
            random.randint(0, 60),
            random.randint(0, 5),
            churn,
            round(monetary * random.uniform(1.5, 4.0), 2),
            random.randint(0, 7),
        ))

        if len(batch) >= BATCH_SIZE:
            copy_rows(conn, "ml.customer_features", columns, batch)
            progress.advance(len(batch))
            batch = []

    if batch:
        copy_rows(conn, "ml.customer_features", columns, batch)
        progress.advance(len(batch))
    progress.done()

    # Churn predictions
    total = COUNTS.ml_churn_predictions
    progress = ProgressTracker("ml.churn_predictions", total)
    columns = [
        "customer_id", "model_version", "churn_probability", "risk_tier", "top_factors",
    ]
    model_versions = ["v2.3.1", "v2.4.0", "v3.0.0-beta", "v3.0.0"]
    risk_tiers = ["low", "medium", "high", "critical"]
    factor_pool = [
        "low_engagement", "declining_orders", "support_escalations",
        "competitor_activity", "price_sensitivity", "payment_failures",
        "reduced_sessions", "negative_nps", "contract_expiring",
    ]
    batch = []
    for i in range(1, total + 1):
        prob = round(random.betavariate(2, 5), 4)
        tier = "critical" if prob > 0.7 else "high" if prob > 0.5 else "medium" if prob > 0.25 else "low"
        factors = random.sample(factor_pool, k=random.randint(1, 4))

        batch.append((
            i,
            random.choice(model_versions),
            prob,
            tier,
            "[" + ", ".join('"' + f + '"' for f in factors) + "]",
        ))

        if len(batch) >= BATCH_SIZE:
            copy_rows(conn, "ml.churn_predictions", columns, batch)
            progress.advance(len(batch))
            batch = []

    if batch:
        copy_rows(conn, "ml.churn_predictions", columns, batch)
        progress.advance(len(batch))
    progress.done()
