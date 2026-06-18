-- =====================================================================
-- raw_google_ads — Google Ads API export (acquisition spend)
-- Source system: Google Ads API v17 (resource-style). snake_case columns,
-- ids are bigint resource ids. Money stored in MICROS (1e6 = 1 currency unit)
-- per the real API. ad_performance_daily is aggregate daily — NO customer PII.
-- NO cross-schema FK constraints. PKs within a table only.
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS raw_google_ads;

-- ---------------------------------------------------------------------
-- campaigns — Google Ads campaigns
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_google_ads.campaigns (
    campaign_id            bigint PRIMARY KEY,       -- resource id
    customer_id            bigint,                   -- Google Ads ACCOUNT id (NOT a NALA customer)
    name                   text NOT NULL,
    status                 text,                     -- ENABLED / PAUSED / REMOVED
    advertising_channel_type text,                   -- SEARCH / DISPLAY / VIDEO / PERFORMANCE_MAX
    bidding_strategy_type  text,                     -- TARGET_CPA / MAXIMIZE_CONVERSIONS / ...
    campaign_budget_micros bigint,                   -- daily budget in micros
    start_date             date,
    end_date               date,                     -- nullable (ongoing)
    labels                 jsonb,
    created_at             timestamptz
);

-- ---------------------------------------------------------------------
-- ad_groups — ad groups within a campaign
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_google_ads.ad_groups (
    ad_group_id   bigint PRIMARY KEY,
    campaign_id   bigint,
    name          text,
    status        text,                              -- ENABLED / PAUSED / REMOVED
    type          text,                              -- SEARCH_STANDARD / DISPLAY_STANDARD / ...
    cpc_bid_micros bigint,
    created_at    timestamptz
);

-- ---------------------------------------------------------------------
-- ad_performance_daily — FACT: spend/impressions/clicks/conversions per
-- ad_group per day. Aggregate, no PII. metrics.* names flattened.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_google_ads.ad_performance_daily (
    id                    bigint PRIMARY KEY,
    date                  date NOT NULL,             -- 'segments.date'
    campaign_id           bigint,
    ad_group_id           bigint,
    device                text,                      -- MOBILE / DESKTOP / TABLET
    impressions           bigint,
    clicks                bigint,
    cost_micros           bigint,                    -- spend in micros (currency = account ccy)
    conversions           numeric(12,2),             -- fractional (attribution)
    conversions_value     numeric(18,2),             -- attributed value in account ccy
    currency_code         text,                      -- GBP / USD / EUR (account currency)
    ctr                   numeric(8,5),              -- legacy precomputed, sometimes null/stale
    loaded_at             timestamptz                -- ETL load time
);
