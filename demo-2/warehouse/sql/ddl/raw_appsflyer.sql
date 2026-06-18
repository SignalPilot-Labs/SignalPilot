-- raw_appsflyer — AppsFlyer mobile-attribution (MMP) raw-data export.
-- Source system: AppsFlyer (Raw Data / Push API). Vendor style: AppsFlyer raw-data
-- CSV column names, lowercase-with-spaces normalized to snake_case here, plus the
-- characteristic media_source / campaign / af_* attribution fields and event_time
-- as a naive UTC ISO string ('event_time' text) — vendor format drift.
CREATE SCHEMA IF NOT EXISTS raw_appsflyer;

-- media_sources (lookup). Acquisition channels / ad networks NALA buys on.
CREATE TABLE IF NOT EXISTS raw_appsflyer.media_sources (
    media_source_id      integer PRIMARY KEY,
    media_source         text NOT NULL,            -- 'Facebook Ads','googleadwords_int','tiktokglobal_int','Organic'
    pretty_name          text,                     -- 'Facebook','Google Ads','TikTok','Organic'
    channel_type         text,                     -- paid_social / paid_search / organic / referral
    is_active            boolean DEFAULT true
);

-- installs. One row per first-open / install attributed by AppsFlyer.
CREATE TABLE IF NOT EXISTS raw_appsflyer.installs (
    appsflyer_id         text PRIMARY KEY,         -- AppsFlyer device id (PII-ish device key)
    customer_user_id     text,                     -- CUS_... once the user logs in; NULL pre-login (PII link)
    install_time         text NOT NULL,            -- 'YYYY-MM-DD HH:MM:SS' naive UTC (vendor format drift)
    attributed_touch_time text,                    -- ISO naive string; null for organic
    attributed_touch_type text,                    -- click / impression
    media_source         text,                     -- raw media source string (join to media_sources.media_source, dirty)
    campaign             text,                     -- ad campaign name (free-text, messy)
    campaign_id          text,
    af_adset             text,
    af_ad                text,
    af_channel           text,
    platform             text NOT NULL,            -- ios / android
    app_id               text,                     -- 'com.nala.app' (ios id9... / android pkg)
    app_version          text,
    device_model         text,                     -- 'iPhone15,3','Pixel 8'
    os_version           text,
    country_code         text,                     -- ISO-2
    language             text,
    idfa                 text,                     -- PII (ios advertising id), null if ATT-denied
    idfv                 text,                     -- PII (ios vendor id)
    advertising_id       text,                     -- PII (android GAID)
    ip                   inet,                     -- PII
    is_organic           boolean DEFAULT false,
    is_retargeting       boolean DEFAULT false,
    is_primary_attribution boolean DEFAULT true
);

-- in_app_events. Post-install events AppsFlyer tracks for ROI (rich-event payload).
CREATE TABLE IF NOT EXISTS raw_appsflyer.in_app_events (
    event_uuid           text PRIMARY KEY,
    appsflyer_id         text NOT NULL,            -- -> installs.appsflyer_id (dirty: some orphans)
    customer_user_id     text,                     -- CUS_... (PII link), often null
    event_name           text NOT NULL,           -- 'af_complete_registration','af_first_transfer','af_purchase'
    event_time           text NOT NULL,           -- naive UTC ISO string (vendor format drift)
    event_value          jsonb,                   -- AppsFlyer af_* event-value JSON ({af_revenue, af_currency,...})
    event_revenue        numeric(18,2),           -- parsed revenue convenience col (often null)
    event_revenue_currency text,
    media_source         text,                    -- attribution at event time
    campaign             text,
    platform             text NOT NULL,
    app_version          text,
    country_code         text,
    ip                   inet                     -- PII
);

-- attributions. Attribution decision records (which touch got credit; reattribution).
CREATE TABLE IF NOT EXISTS raw_appsflyer.attributions (
    attribution_id       text PRIMARY KEY,
    appsflyer_id         text NOT NULL,            -- -> installs.appsflyer_id
    customer_user_id     text,                     -- CUS_...
    media_source         text,
    campaign             text,
    campaign_id          text,
    attribution_type     text,                    -- install / reattribution / reengagement
    touch_type           text,                    -- click / impression
    touch_time           timestamptz,             -- tz timestamp here (different from installs!)
    attributed_at        timestamptz NOT NULL,
    contributor_1_media_source text,              -- multi-touch contributor (sparse)
    is_organic           boolean DEFAULT false
);
