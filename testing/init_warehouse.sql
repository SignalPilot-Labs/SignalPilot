-- SignalPilot Analytics Warehouse Schema
-- Mimics a Snowflake-style star/snowflake schema on PostgreSQL
-- Uses schema namespacing similar to Snowflake's DATABASE.SCHEMA.TABLE pattern

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── Schemas (like Snowflake databases/schemas) ─────────────────────────────
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS ml;

-- ══════════════════════════════════════════════════════════════════════════════
-- RAW SCHEMA — ingested data (landing zone)
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE raw.customer_events (
    event_id        UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    event_timestamp TIMESTAMPTZ NOT NULL,
    event_type      VARCHAR(50) NOT NULL,
    customer_id     BIGINT,
    session_id      VARCHAR(64),
    page_url        VARCHAR(2000),
    referrer_url    VARCHAR(2000),
    device_type     VARCHAR(30),
    browser         VARCHAR(50),
    os              VARCHAR(50),
    ip_address      INET,
    country_code    VARCHAR(3),
    city            VARCHAR(100),
    utm_source      VARCHAR(100),
    utm_medium      VARCHAR(100),
    utm_campaign    VARCHAR(200),
    properties      JSONB DEFAULT '{}',
    loaded_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_raw_events_ts ON raw.customer_events (event_timestamp);
CREATE INDEX idx_raw_events_customer ON raw.customer_events (customer_id);
CREATE INDEX idx_raw_events_type ON raw.customer_events (event_type);

CREATE TABLE raw.transactions (
    txn_id          UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    txn_timestamp   TIMESTAMPTZ NOT NULL,
    order_id        BIGINT,
    customer_id     BIGINT,
    product_id      BIGINT,
    quantity        INTEGER,
    revenue         NUMERIC(12, 2),
    cost            NUMERIC(12, 2),
    discount        NUMERIC(12, 2) DEFAULT 0,
    payment_method  VARCHAR(50),
    channel         VARCHAR(30),
    store_id        INTEGER,
    loaded_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_raw_txn_ts ON raw.transactions (txn_timestamp);

-- ══════════════════════════════════════════════════════════════════════════════
-- ANALYTICS SCHEMA — dimensional model
-- ══════════════════════════════════════════════════════════════════════════════

-- ── Dimension: Dates ───────────────────────────────────────────────────────
CREATE TABLE analytics.dim_date (
    date_key        INTEGER PRIMARY KEY,     -- YYYYMMDD
    full_date       DATE NOT NULL UNIQUE,
    year            SMALLINT NOT NULL,
    quarter         SMALLINT NOT NULL,
    month           SMALLINT NOT NULL,
    month_name      VARCHAR(15) NOT NULL,
    week_of_year    SMALLINT NOT NULL,
    day_of_month    SMALLINT NOT NULL,
    day_of_week     SMALLINT NOT NULL,
    day_name        VARCHAR(10) NOT NULL,
    is_weekend      BOOLEAN NOT NULL,
    is_holiday      BOOLEAN DEFAULT FALSE,
    fiscal_year     SMALLINT,
    fiscal_quarter  SMALLINT
);

-- ── Dimension: Customers ───────────────────────────────────────────────────
CREATE TABLE analytics.dim_customer (
    customer_key    BIGSERIAL PRIMARY KEY,
    customer_id     BIGINT NOT NULL,
    first_name      VARCHAR(100),
    last_name       VARCHAR(100),
    email           VARCHAR(255),
    segment         VARCHAR(50),
    region          VARCHAR(50),
    country         VARCHAR(3),
    state           VARCHAR(50),
    city            VARCHAR(100),
    loyalty_tier    VARCHAR(20),
    lifetime_value  NUMERIC(14, 2) DEFAULT 0,
    first_order_date DATE,
    last_order_date DATE,
    total_orders    INTEGER DEFAULT 0,
    is_churned      BOOLEAN DEFAULT FALSE,
    valid_from      TIMESTAMPTZ DEFAULT NOW(),
    valid_to        TIMESTAMPTZ DEFAULT '9999-12-31',
    is_current      BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_dim_customer_id ON analytics.dim_customer (customer_id);
CREATE INDEX idx_dim_customer_segment ON analytics.dim_customer (segment);

-- ── Dimension: Products ────────────────────────────────────────────────────
CREATE TABLE analytics.dim_product (
    product_key     BIGSERIAL PRIMARY KEY,
    product_id      BIGINT NOT NULL,
    sku             VARCHAR(50),
    name            VARCHAR(255),
    category        VARCHAR(100),
    subcategory     VARCHAR(100),
    brand           VARCHAR(100),
    unit_price      NUMERIC(10, 2),
    unit_cost       NUMERIC(10, 2),
    margin_pct      NUMERIC(5, 2),
    is_active       BOOLEAN DEFAULT TRUE,
    valid_from      TIMESTAMPTZ DEFAULT NOW(),
    valid_to        TIMESTAMPTZ DEFAULT '9999-12-31',
    is_current      BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_dim_product_id ON analytics.dim_product (product_id);
CREATE INDEX idx_dim_product_category ON analytics.dim_product (category);

-- ── Dimension: Employees ───────────────────────────────────────────────────
CREATE TABLE analytics.dim_employee (
    employee_key    BIGSERIAL PRIMARY KEY,
    employee_id     BIGINT NOT NULL,
    full_name       VARCHAR(200),
    department      VARCHAR(100),
    title           VARCHAR(150),
    region          VARCHAR(50),
    hire_date       DATE,
    is_active       BOOLEAN DEFAULT TRUE
);

-- ── Dimension: Stores/Channels ─────────────────────────────────────────────
CREATE TABLE analytics.dim_channel (
    channel_key     SERIAL PRIMARY KEY,
    channel_name    VARCHAR(50) NOT NULL,
    channel_type    VARCHAR(30),
    region          VARCHAR(50),
    country         VARCHAR(3),
    is_active       BOOLEAN DEFAULT TRUE
);

-- ── Fact: Sales ────────────────────────────────────────────────────────────
CREATE TABLE analytics.fact_sales (
    sale_id         BIGSERIAL PRIMARY KEY,
    date_key        INTEGER NOT NULL REFERENCES analytics.dim_date(date_key),
    customer_key    BIGINT NOT NULL,
    product_key     BIGINT NOT NULL,
    employee_key    BIGINT,
    channel_key     INTEGER,
    order_id        BIGINT,
    quantity        INTEGER NOT NULL,
    unit_price      NUMERIC(10, 2) NOT NULL,
    discount_amount NUMERIC(10, 2) DEFAULT 0,
    revenue         NUMERIC(12, 2) NOT NULL,
    cost            NUMERIC(12, 2) NOT NULL,
    profit          NUMERIC(12, 2) NOT NULL,
    tax             NUMERIC(10, 2) DEFAULT 0,
    shipping        NUMERIC(10, 2) DEFAULT 0
);

CREATE INDEX idx_fact_sales_date ON analytics.fact_sales (date_key);
CREATE INDEX idx_fact_sales_customer ON analytics.fact_sales (customer_key);
CREATE INDEX idx_fact_sales_product ON analytics.fact_sales (product_key);

-- ── Fact: Web Analytics ────────────────────────────────────────────────────
CREATE TABLE analytics.fact_web_events (
    event_id        BIGSERIAL PRIMARY KEY,
    date_key        INTEGER NOT NULL REFERENCES analytics.dim_date(date_key),
    customer_key    BIGINT,
    session_id      VARCHAR(64),
    event_type      VARCHAR(50) NOT NULL,
    page_url        VARCHAR(2000),
    referrer        VARCHAR(2000),
    device_type     VARCHAR(30),
    browser         VARCHAR(50),
    country         VARCHAR(3),
    duration_sec    INTEGER,
    is_bounce       BOOLEAN DEFAULT FALSE,
    is_conversion   BOOLEAN DEFAULT FALSE,
    revenue         NUMERIC(12, 2) DEFAULT 0
);

CREATE INDEX idx_fact_web_date ON analytics.fact_web_events (date_key);
CREATE INDEX idx_fact_web_customer ON analytics.fact_web_events (customer_key);
CREATE INDEX idx_fact_web_type ON analytics.fact_web_events (event_type);

-- ── Fact: Inventory Snapshots ──────────────────────────────────────────────
CREATE TABLE analytics.fact_inventory (
    snapshot_id     BIGSERIAL PRIMARY KEY,
    date_key        INTEGER NOT NULL REFERENCES analytics.dim_date(date_key),
    product_key     BIGINT NOT NULL,
    warehouse_id    INTEGER,
    quantity_on_hand INTEGER NOT NULL,
    quantity_reserved INTEGER DEFAULT 0,
    quantity_on_order INTEGER DEFAULT 0,
    days_of_supply  NUMERIC(8, 1),
    is_below_reorder BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_fact_inv_date ON analytics.fact_inventory (date_key);
CREATE INDEX idx_fact_inv_product ON analytics.fact_inventory (product_key);

-- ══════════════════════════════════════════════════════════════════════════════
-- ML SCHEMA — model features & predictions
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE ml.customer_features (
    customer_id     BIGINT PRIMARY KEY,
    recency_days    INTEGER,
    frequency       INTEGER,
    monetary_value  NUMERIC(14, 2),
    avg_order_value NUMERIC(10, 2),
    order_count_30d INTEGER,
    order_count_90d INTEGER,
    page_views_30d  INTEGER,
    sessions_30d    INTEGER,
    support_tickets_90d INTEGER,
    churn_score     NUMERIC(5, 4),
    ltv_predicted   NUMERIC(14, 2),
    segment_cluster INTEGER,
    computed_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE ml.churn_predictions (
    prediction_id   BIGSERIAL PRIMARY KEY,
    customer_id     BIGINT NOT NULL,
    model_version   VARCHAR(50),
    churn_probability NUMERIC(5, 4),
    risk_tier       VARCHAR(20),
    top_factors     JSONB,
    predicted_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_churn_customer ON ml.churn_predictions (customer_id);
