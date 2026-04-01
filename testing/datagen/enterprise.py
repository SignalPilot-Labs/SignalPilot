"""
Generate fake data for the Enterprise OLTP database.
Each function generates one table's data via COPY bulk loading.
"""

import hashlib
import random
import uuid
from datetime import datetime, timedelta, date

from faker import Faker

from .config import (
    BATCH_SIZE, COUNTS, SEGMENTS, LOYALTY_TIERS, DEPARTMENTS,
    CATEGORIES, SUBCATEGORIES, BRANDS, ORDER_STATUSES, PAYMENT_METHODS,
    CARD_TYPES, TICKET_CATEGORIES, TICKET_PRIORITIES, TICKET_STATUSES,
    US_STATES,
)
from .db import copy_rows, ProgressTracker

fake = Faker()
Faker.seed(42)
random.seed(42)

# Date range for generated data
START_DATE = datetime(2018, 1, 1)
END_DATE = datetime(2026, 3, 31)
DATE_RANGE_DAYS = (END_DATE - START_DATE).days


def _random_ts(start=START_DATE, end=END_DATE) -> str:
    """Random timestamp between start and end."""
    delta = end - start
    offset = random.randint(0, int(delta.total_seconds()))
    dt = start + timedelta(seconds=offset)
    return dt.isoformat()


def _random_date(start=START_DATE, end=END_DATE) -> str:
    offset = random.randint(0, (end.date() - start.date()).days)
    return (start.date() + timedelta(days=offset)).isoformat()


# ── Employees ───────────────────────────────────────────────────────────────

def generate_employees(conn):
    """Generate employee records. Must run before orders/tickets."""
    total = COUNTS.employees
    progress = ProgressTracker("employees", total)
    columns = [
        "employee_uuid", "first_name", "last_name", "email", "phone",
        "department", "title", "salary", "commission_pct", "hire_date",
        "termination_date", "manager_id", "ssn_hash", "bank_account", "is_active",
    ]
    batch = []
    for i in range(1, total + 1):
        dept = random.choice(DEPARTMENTS)
        hire = _random_date(START_DATE, END_DATE - timedelta(days=90))
        termed = None
        active = True
        if random.random() < 0.08:
            termed = _random_date(datetime.fromisoformat(hire) + timedelta(days=90), END_DATE)
            active = False
        salary = round(random.gauss(95000, 35000), 2)
        salary = max(35000, min(salary, 450000))
        manager = random.randint(1, max(1, i - 1)) if i > 1 else None
        ssn_hash = hashlib.sha256(f"SSN-{i}-{fake.ssn()}".encode()).hexdigest()

        batch.append((
            str(uuid.uuid4()),
            fake.first_name(),
            fake.last_name(),
            f"emp{i}@company.com",
            fake.phone_number()[:30],
            dept,
            fake.job()[:150],
            salary,
            round(random.uniform(0, 15), 2) if dept == "Sales" else 0,
            hire,
            termed,
            manager,
            ssn_hash,
            f"ACCT-{fake.bban()}"[:255],
            active,
        ))

        if len(batch) >= BATCH_SIZE:
            copy_rows(conn, "employees", columns, batch)
            progress.advance(len(batch))
            batch = []

    if batch:
        copy_rows(conn, "employees", columns, batch)
        progress.advance(len(batch))
    progress.done()


# ── Products ────────────────────────────────────────────────────────────────

def generate_products(conn):
    total = COUNTS.products
    progress = ProgressTracker("products", total)
    columns = [
        "sku", "name", "description", "category", "subcategory", "brand",
        "unit_price", "unit_cost", "weight_kg", "stock_quantity",
        "reorder_point", "supplier_id", "is_active",
    ]
    batch = []
    for i in range(1, total + 1):
        cat = random.choice(CATEGORIES)
        subcats = SUBCATEGORIES.get(cat, ["General"])
        price = round(random.lognormvariate(3.5, 1.2), 2)
        price = max(0.99, min(price, 9999.99))
        cost = round(price * random.uniform(0.2, 0.7), 2)

        batch.append((
            f"SKU-{i:06d}",
            f"{fake.word().title()} {random.choice(subcats)} {fake.word().title()}"[:255],
            fake.sentence(nb_words=12),
            cat,
            random.choice(subcats),
            random.choice(BRANDS),
            price,
            cost,
            round(random.uniform(0.1, 50.0), 3),
            random.randint(0, 5000),
            random.randint(5, 100),
            random.randint(1, 200),
            random.random() > 0.05,
        ))

        if len(batch) >= BATCH_SIZE:
            copy_rows(conn, "products", columns, batch)
            progress.advance(len(batch))
            batch = []

    if batch:
        copy_rows(conn, "products", columns, batch)
        progress.advance(len(batch))
    progress.done()


# ── Customers ───────────────────────────────────────────────────────────────

def generate_customers(conn):
    total = COUNTS.customers
    progress = ProgressTracker("customers", total)
    columns = [
        "customer_uuid", "first_name", "last_name", "email", "phone",
        "date_of_birth", "address_line1", "address_line2", "city", "state",
        "zip_code", "country", "segment", "loyalty_tier", "credit_limit",
        "is_active", "created_at", "updated_at",
    ]
    batch = []
    for i in range(1, total + 1):
        created = _random_ts()
        batch.append((
            str(uuid.uuid4()),
            fake.first_name(),
            fake.last_name(),
            f"customer{i}@{fake.free_email_domain()}",
            fake.phone_number()[:30],
            fake.date_of_birth(minimum_age=18, maximum_age=85).isoformat(),
            fake.street_address()[:255],
            fake.secondary_address()[:255] if random.random() < 0.3 else None,
            fake.city()[:100],
            random.choice(US_STATES),
            fake.zipcode(),
            "US" if random.random() < 0.7 else random.choice(["CA", "GB", "DE", "JP", "AU"]),
            random.choice(SEGMENTS),
            random.choice(LOYALTY_TIERS),
            round(random.uniform(500, 100000), 2),
            random.random() > 0.05,
            created,
            created,
        ))

        if len(batch) >= BATCH_SIZE:
            copy_rows(conn, "customers", columns, batch)
            progress.advance(len(batch))
            batch = []

    if batch:
        copy_rows(conn, "customers", columns, batch)
        progress.advance(len(batch))
    progress.done()


# ── Orders ──────────────────────────────────────────────────────────────────

def generate_orders(conn):
    total = COUNTS.orders
    max_cust = COUNTS.customers
    max_emp = COUNTS.employees
    progress = ProgressTracker("orders", total)
    columns = [
        "order_uuid", "customer_id", "employee_id", "order_date",
        "required_date", "shipped_date", "status", "subtotal", "tax_amount",
        "shipping_cost", "total_amount", "shipping_address", "tracking_number",
    ]
    batch = []
    for i in range(1, total + 1):
        status = random.choice(ORDER_STATUSES)
        order_date = _random_ts()
        order_dt = datetime.fromisoformat(order_date)
        required = (order_dt + timedelta(days=random.randint(3, 14))).date().isoformat()
        shipped = None
        if status in ("shipped", "delivered"):
            shipped = (order_dt + timedelta(days=random.randint(1, 7))).date().isoformat()

        subtotal = round(random.lognormvariate(4.0, 1.0), 2)
        subtotal = max(5.0, min(subtotal, 50000.0))
        tax = round(subtotal * random.uniform(0.05, 0.12), 2)
        shipping = round(random.uniform(0, 25), 2) if subtotal < 100 else 0
        total = round(subtotal + tax + shipping, 2)

        batch.append((
            str(uuid.uuid4()),
            random.randint(1, max_cust),
            random.randint(1, max_emp),
            order_date,
            required,
            shipped,
            status,
            subtotal,
            tax,
            shipping,
            total,
            f"{fake.street_address()}, {fake.city()}, {random.choice(US_STATES)}"[:500],
            f"TRK{uuid.uuid4().hex[:12].upper()}" if shipped else None,
        ))

        if len(batch) >= BATCH_SIZE:
            copy_rows(conn, "orders", columns, batch)
            progress.advance(len(batch))
            batch = []

    if batch:
        copy_rows(conn, "orders", columns, batch)
        progress.advance(len(batch))
    progress.done()


# ── Order Items ─────────────────────────────────────────────────────────────

def generate_order_items(conn):
    total = COUNTS.order_items
    max_orders = COUNTS.orders
    max_products = COUNTS.products
    progress = ProgressTracker("order_items", total)
    columns = ["order_id", "product_id", "quantity", "unit_price", "discount_pct", "line_total"]
    batch = []
    for i in range(1, total + 1):
        qty = random.choices([1, 2, 3, 4, 5, 10], weights=[50, 25, 12, 6, 4, 3])[0]
        price = round(random.lognormvariate(3.0, 1.0), 2)
        price = max(0.99, min(price, 5000.0))
        discount = round(random.choice([0, 0, 0, 5, 10, 15, 20, 25]), 2)
        line = round(qty * price * (1 - discount / 100), 2)

        batch.append((
            random.randint(1, max_orders),
            random.randint(1, max_products),
            qty,
            price,
            discount,
            line,
        ))

        if len(batch) >= BATCH_SIZE:
            copy_rows(conn, "order_items", columns, batch)
            progress.advance(len(batch))
            batch = []

    if batch:
        copy_rows(conn, "order_items", columns, batch)
        progress.advance(len(batch))
    progress.done()


# ── Payments ────────────────────────────────────────────────────────────────

def generate_payments(conn):
    total = COUNTS.payments
    max_orders = COUNTS.orders
    max_cust = COUNTS.customers
    progress = ProgressTracker("payments", total)
    columns = [
        "payment_uuid", "order_id", "customer_id", "payment_method",
        "card_type", "card_last_four", "card_token", "amount", "currency",
        "status", "processor_txn_id", "processed_at",
    ]
    batch = []
    for i in range(1, total + 1):
        method = random.choice(PAYMENT_METHODS)
        card_type = random.choice(CARD_TYPES) if "card" in method else None
        card_last = f"{random.randint(1000,9999)}" if card_type else None
        card_token = f"tok_{uuid.uuid4().hex[:24]}" if card_type else None
        amount = round(random.lognormvariate(4.0, 1.0), 2)
        amount = max(1.0, min(amount, 50000.0))
        status = random.choices(
            ["completed", "completed", "completed", "pending", "failed", "refunded"],
            weights=[60, 20, 10, 5, 3, 2],
        )[0]

        batch.append((
            str(uuid.uuid4()),
            random.randint(1, max_orders),
            random.randint(1, max_cust),
            method,
            card_type,
            card_last,
            card_token,
            amount,
            "USD",
            status,
            f"txn_{uuid.uuid4().hex[:20]}",
            _random_ts(),
        ))

        if len(batch) >= BATCH_SIZE:
            copy_rows(conn, "payments", columns, batch)
            progress.advance(len(batch))
            batch = []

    if batch:
        copy_rows(conn, "payments", columns, batch)
        progress.advance(len(batch))
    progress.done()


# ── Support Tickets ─────────────────────────────────────────────────────────

def generate_support_tickets(conn):
    total = COUNTS.support_tickets
    max_cust = COUNTS.customers
    max_emp = COUNTS.employees
    progress = ProgressTracker("support_tickets", total)
    columns = [
        "ticket_uuid", "customer_id", "assigned_to", "subject", "description",
        "category", "priority", "status", "resolution", "sla_due_at",
        "first_response_at", "resolved_at", "satisfaction_score", "created_at",
    ]
    batch = []
    for i in range(1, total + 1):
        created = _random_ts()
        created_dt = datetime.fromisoformat(created)
        status = random.choice(TICKET_STATUSES)
        resolved_at = None
        resolution = None
        first_resp = None
        satisfaction = None

        if status in ("resolved", "closed"):
            resolved_at = (created_dt + timedelta(hours=random.randint(1, 168))).isoformat()
            resolution = fake.sentence(nb_words=8)
            satisfaction = random.randint(1, 5)
        if status != "open":
            first_resp = (created_dt + timedelta(minutes=random.randint(5, 480))).isoformat()

        batch.append((
            str(uuid.uuid4()),
            random.randint(1, max_cust),
            random.randint(1, max_emp),
            fake.sentence(nb_words=6)[:500],
            fake.paragraph(nb_sentences=3),
            random.choice(TICKET_CATEGORIES),
            random.choice(TICKET_PRIORITIES),
            status,
            resolution,
            (created_dt + timedelta(hours=random.choice([4, 8, 24, 48]))).isoformat(),
            first_resp,
            resolved_at,
            satisfaction,
            created,
        ))

        if len(batch) >= BATCH_SIZE:
            copy_rows(conn, "support_tickets", columns, batch)
            progress.advance(len(batch))
            batch = []

    if batch:
        copy_rows(conn, "support_tickets", columns, batch)
        progress.advance(len(batch))
    progress.done()


# ── API Keys & Internal Credentials (sensitive tables for pentest) ──────────

def generate_sensitive_tables(conn):
    """Generate API keys and internal credentials — intentionally sensitive."""
    # API Keys
    columns = [
        "key_hash", "key_prefix", "name", "scopes", "rate_limit",
        "owner_id", "is_active", "expires_at",
    ]
    rows = []
    for i in range(1, COUNTS.api_keys + 1):
        raw_key = f"sk_live_{uuid.uuid4().hex}"
        rows.append((
            hashlib.sha256(raw_key.encode()).hexdigest(),
            raw_key[:10],
            f"{fake.company()[:60]} API Key",
            "{read,write}" if random.random() < 0.3 else "{read}",
            random.choice([100, 500, 1000, 5000, 10000]),
            random.randint(1, COUNTS.employees),
            random.random() > 0.1,
            _random_ts(datetime(2026, 1, 1), datetime(2027, 12, 31)),
        ))
    copy_rows(conn, "api_keys", columns, rows)
    print(f"  api_keys: {len(rows)} rows")

    # Internal credentials (honeypot for pentest)
    columns = [
        "service_name", "endpoint_url", "username", "password_enc", "api_key", "notes",
    ]
    services = [
        ("AWS Production", "https://console.aws.amazon.com", "admin@company.com",
         "AES256:dGhpcyBpcyBub3QgcmVhbA==", "AKIA" + fake.lexify("????????????????"), "Main AWS account"),
        ("Stripe Live", "https://api.stripe.com", "acct_live",
         "AES256:c3RyaXBlIGZha2Uga2V5", "sk_live_" + fake.lexify("????????????????????????"), "Payment processing"),
        ("Snowflake Prod", "https://xy12345.snowflakecomputing.com", "ETL_SERVICE",
         "AES256:c25vd2ZsYWtlIHBhc3M=", None, "Warehouse ETL account"),
        ("Slack Bot", "https://slack.com/api", "signalpilot-bot",
         "AES256:c2xhY2sgdG9rZW4=", "xoxb-" + fake.numerify("###########-###########"), "Alerting bot"),
        ("GitHub Actions", "https://api.github.com", "deploy-bot",
         None, "ghp_" + fake.lexify("????????????????????????????????????"), "CI/CD token"),
        ("Datadog", "https://api.datadoghq.com", "monitoring",
         None, fake.hexify("^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^"), "APM & logging"),
        ("SendGrid", "https://api.sendgrid.com", "noreply@company.com",
         "AES256:c2VuZGdyaWQgcGFzcw==", "SG." + fake.lexify("????????????????????"), "Transactional email"),
        ("PagerDuty", "https://api.pagerduty.com", "oncall-integration",
         None, fake.lexify("????????????????????????"), "Incident routing key"),
    ]
    rows = []
    for svc in services:
        rows.append(svc)
    # Add more random ones
    for i in range(COUNTS.internal_creds - len(services)):
        rows.append((
            f"{fake.company()[:60]} Service",
            f"https://{fake.domain_name()}/api",
            fake.user_name(),
            f"AES256:{fake.lexify('????????????????????????')}",
            fake.hexify("^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^") if random.random() < 0.5 else None,
            fake.sentence(nb_words=5),
        ))
    copy_rows(conn, "internal_credentials", columns, rows)
    print(f"  internal_credentials: {len(rows)} rows")


# ── Audit Log ───────────────────────────────────────────────────────────────

def generate_audit_log(conn):
    total = COUNTS.audit_log
    progress = ProgressTracker("audit_log", total)
    columns = [
        "event_type", "actor_id", "actor_type", "resource_type",
        "resource_id", "action", "details", "ip_address", "user_agent",
        "created_at",
    ]
    event_types = ["login", "logout", "query", "export", "settings_change", "permission_change",
                   "api_call", "data_access", "admin_action", "failed_login"]
    actions = ["create", "read", "update", "delete", "execute", "export", "download"]
    batch = []
    for i in range(1, total + 1):
        batch.append((
            random.choice(event_types),
            random.randint(1, COUNTS.employees),
            random.choice(["employee", "api_key", "system"]),
            random.choice(["order", "customer", "product", "payment", "report", "settings"]),
            str(random.randint(1, 1000000)),
            random.choice(actions),
            f'{{"detail": "{fake.sentence(nb_words=4)}"}}',
            f"{random.randint(10,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}",
            fake.user_agent()[:500] if random.random() < 0.8 else None,
            _random_ts(),
        ))

        if len(batch) >= BATCH_SIZE:
            copy_rows(conn, "system_audit_log", columns, batch)
            progress.advance(len(batch))
            batch = []

    if batch:
        copy_rows(conn, "system_audit_log", columns, batch)
        progress.advance(len(batch))
    progress.done()
