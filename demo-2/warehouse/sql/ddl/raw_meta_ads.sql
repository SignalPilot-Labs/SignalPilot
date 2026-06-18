-- =====================================================================
-- raw_meta_ads — Meta (Facebook/Instagram) Marketing API export
-- Source system: Meta Marketing API v20. snake_case columns, ids are numeric
-- strings (kept as text per the API). Money stored as DECIMAL strings in
-- account currency (NOT micros — differs from Google deliberately). Timestamps
-- are ISO-8601 with explicit tz offset. ad_insights_daily aggregate, no PII.
-- NO cross-schema FK constraints. PKs within a table only.
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS raw_meta_ads;

-- ---------------------------------------------------------------------
-- campaigns — Meta ad campaigns
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_meta_ads.campaigns (
    id               text PRIMARY KEY,             -- numeric string id
    account_id       text,                         -- 'act_<digits>' (NOT a NALA customer)
    name             text NOT NULL,
    objective        text,                         -- OUTCOME_TRAFFIC / OUTCOME_LEADS / OUTCOME_APP_PROMOTION
    status           text,                         -- ACTIVE / PAUSED / ARCHIVED / DELETED
    effective_status text,                         -- may differ from status (legacy/derived)
    daily_budget     text,                         -- DECIMAL string, MINOR units (cents)
    buying_type      text,                         -- AUCTION / RESERVED
    created_time     text,                         -- ISO with tz offset '+0000'
    updated_time     text,
    metadata         jsonb
);

-- ---------------------------------------------------------------------
-- ad_sets — ad sets (targeting + budget) within a campaign
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_meta_ads.ad_sets (
    id                  text PRIMARY KEY,
    campaign_id         text,
    name                text,
    status              text,                       -- ACTIVE / PAUSED / ARCHIVED
    optimization_goal   text,                       -- LINK_CLICKS / OFFSITE_CONVERSIONS / APP_INSTALLS
    billing_event       text,                       -- IMPRESSIONS / LINK_CLICKS
    bid_amount          text,                       -- DECIMAL string minor units, nullable
    daily_budget        text,                       -- DECIMAL string minor units
    targeting           jsonb,                      -- targeting spec blob
    created_time        text                        -- ISO with tz offset
);

-- ---------------------------------------------------------------------
-- ad_insights_daily — FACT: spend/impressions/clicks/actions per ad_set
-- per day. Aggregate, no PII. Money in account currency (major units).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_meta_ads.ad_insights_daily (
    id                  bigint PRIMARY KEY,
    date_start          date NOT NULL,              -- Meta 'date_start'
    date_stop           date,                       -- equals date_start for daily breakdown
    account_id          text,
    campaign_id         text,
    adset_id            text,                       -- note: Meta uses 'adset' not 'ad_set' here
    publisher_platform  text,                       -- facebook / instagram / audience_network
    impressions         bigint,
    clicks              bigint,
    spend               numeric(18,2),              -- account currency major units
    reach               bigint,
    actions             jsonb,                      -- array of {action_type, value} (conversions live here)
    account_currency    text,                       -- GBP / USD / EUR
    loaded_at           timestamptz
);
