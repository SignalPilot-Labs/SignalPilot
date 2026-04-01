-- SignalPilot Enterprise OLTP Schema
-- Mimics a realistic production PostgreSQL database

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Customers ──────────────────────────────────────────────────────────────
CREATE TABLE customers (
    id              BIGSERIAL PRIMARY KEY,
    customer_uuid   UUID DEFAULT uuid_generate_v4() NOT NULL UNIQUE,
    first_name      VARCHAR(100) NOT NULL,
    last_name       VARCHAR(100) NOT NULL,
    email           VARCHAR(255) NOT NULL UNIQUE,
    phone           VARCHAR(30),
    date_of_birth   DATE,
    ssn_encrypted   BYTEA,                  -- encrypted PII
    address_line1   VARCHAR(255),
    address_line2   VARCHAR(255),
    city            VARCHAR(100),
    state           VARCHAR(50),
    zip_code        VARCHAR(20),
    country         VARCHAR(3) DEFAULT 'US',
    segment         VARCHAR(30) DEFAULT 'standard',
    loyalty_tier    VARCHAR(20) DEFAULT 'bronze',
    credit_limit    NUMERIC(12, 2) DEFAULT 0,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_customers_email ON customers (email);
CREATE INDEX idx_customers_name ON customers (last_name, first_name);
CREATE INDEX idx_customers_segment ON customers (segment);
CREATE INDEX idx_customers_created ON customers (created_at);

-- ── Employees ──────────────────────────────────────────────────────────────
CREATE TABLE employees (
    id              BIGSERIAL PRIMARY KEY,
    employee_uuid   UUID DEFAULT uuid_generate_v4() NOT NULL UNIQUE,
    first_name      VARCHAR(100) NOT NULL,
    last_name       VARCHAR(100) NOT NULL,
    email           VARCHAR(255) NOT NULL UNIQUE,
    phone           VARCHAR(30),
    department      VARCHAR(100),
    title           VARCHAR(150),
    salary          NUMERIC(12, 2),
    commission_pct  NUMERIC(5, 2) DEFAULT 0,
    hire_date       DATE NOT NULL,
    termination_date DATE,
    manager_id      BIGINT REFERENCES employees(id),
    ssn_hash        VARCHAR(128),           -- hashed SSN
    bank_account    VARCHAR(255),           -- sensitive!
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_employees_dept ON employees (department);
CREATE INDEX idx_employees_manager ON employees (manager_id);

-- ── Products ───────────────────────────────────────────────────────────────
CREATE TABLE products (
    id              BIGSERIAL PRIMARY KEY,
    sku             VARCHAR(50) NOT NULL UNIQUE,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    category        VARCHAR(100),
    subcategory     VARCHAR(100),
    brand           VARCHAR(100),
    unit_price      NUMERIC(10, 2) NOT NULL,
    unit_cost       NUMERIC(10, 2) NOT NULL,
    weight_kg       NUMERIC(8, 3),
    stock_quantity  INTEGER DEFAULT 0,
    reorder_point   INTEGER DEFAULT 10,
    supplier_id     INTEGER,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_products_category ON products (category);
CREATE INDEX idx_products_sku ON products (sku);

-- ── Orders ─────────────────────────────────────────────────────────────────
CREATE TABLE orders (
    id              BIGSERIAL PRIMARY KEY,
    order_uuid      UUID DEFAULT uuid_generate_v4() NOT NULL UNIQUE,
    customer_id     BIGINT NOT NULL REFERENCES customers(id),
    employee_id     BIGINT REFERENCES employees(id),
    order_date      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    required_date   DATE,
    shipped_date    DATE,
    status          VARCHAR(30) DEFAULT 'pending',
    subtotal        NUMERIC(12, 2) DEFAULT 0,
    tax_amount      NUMERIC(10, 2) DEFAULT 0,
    shipping_cost   NUMERIC(10, 2) DEFAULT 0,
    total_amount    NUMERIC(12, 2) DEFAULT 0,
    shipping_address TEXT,
    tracking_number VARCHAR(100),
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_orders_customer ON orders (customer_id);
CREATE INDEX idx_orders_date ON orders (order_date);
CREATE INDEX idx_orders_status ON orders (status);
CREATE INDEX idx_orders_employee ON orders (employee_id);

-- ── Order Items ────────────────────────────────────────────────────────────
CREATE TABLE order_items (
    id              BIGSERIAL PRIMARY KEY,
    order_id        BIGINT NOT NULL REFERENCES orders(id),
    product_id      BIGINT NOT NULL REFERENCES products(id),
    quantity        INTEGER NOT NULL DEFAULT 1,
    unit_price      NUMERIC(10, 2) NOT NULL,
    discount_pct    NUMERIC(5, 2) DEFAULT 0,
    line_total      NUMERIC(12, 2) NOT NULL
);

CREATE INDEX idx_order_items_order ON order_items (order_id);
CREATE INDEX idx_order_items_product ON order_items (product_id);

-- ── Payments ───────────────────────────────────────────────────────────────
CREATE TABLE payments (
    id              BIGSERIAL PRIMARY KEY,
    payment_uuid    UUID DEFAULT uuid_generate_v4() NOT NULL UNIQUE,
    order_id        BIGINT NOT NULL REFERENCES orders(id),
    customer_id     BIGINT NOT NULL REFERENCES customers(id),
    payment_method  VARCHAR(50) NOT NULL,
    card_type       VARCHAR(30),
    card_last_four  VARCHAR(4),
    card_token      VARCHAR(255),           -- tokenized card
    amount          NUMERIC(12, 2) NOT NULL,
    currency        VARCHAR(3) DEFAULT 'USD',
    status          VARCHAR(30) DEFAULT 'pending',
    processor_txn_id VARCHAR(255),
    processed_at    TIMESTAMPTZ,
    refunded_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_payments_order ON payments (order_id);
CREATE INDEX idx_payments_customer ON payments (customer_id);
CREATE INDEX idx_payments_status ON payments (status);

-- ── Support Tickets ────────────────────────────────────────────────────────
CREATE TABLE support_tickets (
    id              BIGSERIAL PRIMARY KEY,
    ticket_uuid     UUID DEFAULT uuid_generate_v4() NOT NULL UNIQUE,
    customer_id     BIGINT NOT NULL REFERENCES customers(id),
    assigned_to     BIGINT REFERENCES employees(id),
    subject         VARCHAR(500) NOT NULL,
    description     TEXT,
    category        VARCHAR(100),
    priority        VARCHAR(20) DEFAULT 'medium',
    status          VARCHAR(30) DEFAULT 'open',
    resolution      TEXT,
    sla_due_at      TIMESTAMPTZ,
    first_response_at TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ,
    satisfaction_score INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_tickets_customer ON support_tickets (customer_id);
CREATE INDEX idx_tickets_status ON support_tickets (status);
CREATE INDEX idx_tickets_priority ON support_tickets (priority);
CREATE INDEX idx_tickets_assigned ON support_tickets (assigned_to);

-- ── API Keys (sensitive table) ─────────────────────────────────────────────
CREATE TABLE api_keys (
    id              BIGSERIAL PRIMARY KEY,
    key_hash        VARCHAR(128) NOT NULL UNIQUE,
    key_prefix      VARCHAR(10) NOT NULL,
    name            VARCHAR(100),
    scopes          TEXT[] DEFAULT '{}',
    rate_limit      INTEGER DEFAULT 1000,
    owner_id        BIGINT REFERENCES employees(id),
    is_active       BOOLEAN DEFAULT TRUE,
    last_used_at    TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── Audit Log (system table) ───────────────────────────────────────────────
CREATE TABLE system_audit_log (
    id              BIGSERIAL PRIMARY KEY,
    event_type      VARCHAR(50) NOT NULL,
    actor_id        BIGINT,
    actor_type      VARCHAR(20),
    resource_type   VARCHAR(50),
    resource_id     VARCHAR(100),
    action          VARCHAR(50),
    details         JSONB,
    ip_address      INET,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_audit_event ON system_audit_log (event_type);
CREATE INDEX idx_audit_actor ON system_audit_log (actor_id);
CREATE INDEX idx_audit_created ON system_audit_log (created_at);

-- ── Internal Credentials (intentionally sensitive for pentest) ─────────────
CREATE TABLE internal_credentials (
    id              BIGSERIAL PRIMARY KEY,
    service_name    VARCHAR(100) NOT NULL,
    endpoint_url    VARCHAR(500),
    username        VARCHAR(100),
    password_enc    VARCHAR(255),           -- "encrypted" passwords
    api_key         VARCHAR(255),
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
