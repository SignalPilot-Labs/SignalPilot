-- ============================================================================
-- Domain 4 — FX & Pricing : raw_openexchange
-- Mirror of the Open Exchange Rates API (openexchangerates.org) NALA ingests.
-- Vendor API style: USD-based rate maps, epoch-second timestamps, 'base'/'rates'
-- envelope. Naming WITHIN this vendor matches their real JSON field names.
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS raw_openexchange;

-- ----------------------------------------------------------------------------
-- currencies : lookup of ISO currency codes -> display name (the vendor's
-- /currencies.json endpoint). Includes crypto/stablecoin extensions.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_openexchange.currencies (
    code             text PRIMARY KEY,      -- 'KES'
    name             text,                  -- 'Kenyan Shilling'
    is_crypto        boolean,
    decimals         integer
);

-- ----------------------------------------------------------------------------
-- latest_rates : the vendor's /latest.json — one row per (fetch, currency).
-- 'rate' is units of `currency` per 1 USD (base = 'USD'). epoch-second 'timestamp'.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_openexchange.latest_rates (
    id               bigint PRIMARY KEY,
    base             text,                  -- always 'USD' on the free plan
    currency         text,                  -- quote currency code
    rate             numeric(24,10),        -- units of `currency` per 1 USD
    "timestamp"      bigint,                -- epoch SECONDS (vendor field name)
    fetched_at       timestamptz,
    disclaimer       text                   -- vendor boilerplate, often null
);

-- ----------------------------------------------------------------------------
-- historical_rates : the vendor's /historical/YYYY-MM-DD.json — daily close
-- per currency. One row per (rate_date, currency). Long, thin time series.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_openexchange.historical_rates (
    id               bigint PRIMARY KEY,
    rate_date        date,                  -- the historical day
    base             text,                  -- 'USD'
    currency         text,
    rate             numeric(24,10),        -- units of `currency` per 1 USD
    "timestamp"      bigint,                -- epoch SECONDS for that day's close
    ingested_at      timestamptz
);
