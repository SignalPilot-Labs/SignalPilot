-- raw_app_store — Apple App Store Connect + Google Play Console exports.
-- Source systems: Apple App Store Connect (Analytics / Reviews API) and Google
-- Play Console (Reporting / Reviews). Two vendors with different naming under one
-- schema: Apple tables use Apple-ish camel-to-snake (e.g. units, product_page_views);
-- Google tables use Google Play report column names. Reviews carry reviewer text (PII-ish).
CREATE SCHEMA IF NOT EXISTS raw_app_store;

-- apple_downloads. Daily aggregated download/units metrics from App Store Connect.
-- Grain: one row per (date, country, app_version, source_type). Aggregated, no user id.
CREATE TABLE IF NOT EXISTS raw_app_store.apple_downloads (
    row_id               bigint PRIMARY KEY,
    report_date          date NOT NULL,
    app_version          text,
    country_code         text,                     -- ISO-2 storefront
    source_type          text,                     -- App Store Search / App Referrer / Web Referrer / Unavailable
    device               text,                     -- iPhone / iPad
    units                integer NOT NULL,         -- first-time downloads
    redownloads          integer DEFAULT 0,
    updates              integer DEFAULT 0,
    impressions          integer DEFAULT 0,
    product_page_views   integer DEFAULT 0,
    loaded_at            timestamptz
);

-- apple_reviews. One row per App Store customer review (free-text, rating, PII-ish nickname).
CREATE TABLE IF NOT EXISTS raw_app_store.apple_reviews (
    review_id            text PRIMARY KEY,         -- App Store Connect review id
    territory            text,                     -- storefront country (ISO-2)
    rating               integer NOT NULL,         -- 1..5
    title                text,
    body                 text,                     -- review free-text (may contain PII)
    reviewer_nickname    text,                     -- display nickname (PII-ish)
    app_version          text,
    is_edited            boolean DEFAULT false,
    review_date          timestamptz NOT NULL,     -- ISO-Z style tz timestamp
    developer_response   text,                     -- NALA reply text (often null)
    developer_response_date timestamptz,
    raw_payload          jsonb                     -- original review JSON
);

-- google_play_installs. Daily aggregated install stats from Play Console.
-- Grain: one row per (date, country, app_version). Note Google column naming.
CREATE TABLE IF NOT EXISTS raw_app_store.google_play_installs (
    row_id               bigint PRIMARY KEY,
    stat_date            date NOT NULL,            -- Google: 'Date'
    package_name         text,                     -- 'com.nala.app'
    app_version_code     integer,                  -- Google uses numeric version code
    country              text,                     -- Google: 'Country' (ISO-2)
    daily_device_installs integer NOT NULL,        -- Google: 'Daily Device Installs'
    daily_device_uninstalls integer DEFAULT 0,
    daily_user_installs  integer DEFAULT 0,
    active_device_installs integer DEFAULT 0,      -- Google: 'Active Device Installs'
    store_listing_visitors integer DEFAULT 0,
    loaded_at            timestamptz
);

-- google_play_reviews. One row per Play Store review (free-text, star rating, PII-ish).
CREATE TABLE IF NOT EXISTS raw_app_store.google_play_reviews (
    review_id            text PRIMARY KEY,         -- Play review id
    package_name         text,
    author_name          text,                     -- reviewer display name (PII-ish)
    star_rating          integer NOT NULL,         -- 1..5 (Google: 'Star Rating')
    review_title         text,
    review_text          text,                     -- free-text (may contain PII)
    reviewer_language    text,                     -- 'en','fr','sw'
    device               text,                     -- device model
    android_os_version   text,
    app_version_code     integer,
    app_version_name     text,
    submitted_at         timestamptz NOT NULL,     -- 'Review Submit Date and Time'
    last_modified_at     timestamptz,
    developer_reply_text text,
    developer_reply_at   timestamptz
);
