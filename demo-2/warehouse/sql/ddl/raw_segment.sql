-- raw_segment — Segment Connections product-analytics event pipeline.
-- Source system: Segment (analytics.js / mobile SDK -> warehouse destination).
-- Vendor style: snake_case Segment spec columns (event, anonymous_id, user_id,
-- received_at, sent_at, original_timestamp, context_* flattened, properties jsonb).
-- Both anonymous_id and user_id are present; user_id is null for not-yet-identified
-- (anonymous) traffic — this is realistic and important for identity-resolution demos.
CREATE SCHEMA IF NOT EXISTS raw_segment;

-- tracks (FACT: ~N["events"] rows). One row per `track` call (a user action).
-- Segment warehouse destinations write a wide table with flattened context_*
-- columns plus a jsonb `properties` blob carrying the event-specific payload.
CREATE TABLE IF NOT EXISTS raw_segment.tracks (
    id                   text PRIMARY KEY,          -- Segment message id (uuid-like)
    event                text NOT NULL,             -- 'Transfer Started', 'KYC Submitted', ...
    event_text           text,                      -- human label, occasionally drifts from `event`
    anonymous_id         text NOT NULL,             -- device/browser anonymous id (always present)
    user_id              text,                      -- CUS_... code; NULL for anonymous traffic (PII link)
    properties           jsonb,                     -- event-specific payload (amounts, corridor, etc.)
    -- flattened context.* columns (Segment warehouse style)
    context_ip           inet,                      -- PII
    context_library_name text,                      -- analytics-ios / analytics-android / analytics.js
    context_library_version text,
    context_app_version  text,                      -- app build, e.g. '4.2.0'
    context_device_type  text,                      -- ios / android / web
    context_device_id    text,                      -- PII (device identifier)
    context_os_name      text,                      -- iOS / Android
    context_locale       text,                      -- en-GB, en-US, fr-FR
    context_timezone     text,                      -- Europe/London
    -- Segment timestamp set (notorious for drift; multiple near-equal times)
    timestamp            timestamptz,               -- canonical event time (tz)
    original_timestamp   text,                      -- ISO-Z string as emitted by the SDK
    sent_at              timestamptz,               -- when SDK flushed
    received_at          timestamptz NOT NULL,      -- when Segment received (load watermark)
    loaded_at            timestamptz                -- when warehouse destination wrote the row
);

-- identifies. One row per `identify` call — ties an anonymous_id to a user_id
-- and carries user traits (the moment anonymous traffic becomes a known customer).
CREATE TABLE IF NOT EXISTS raw_segment.identifies (
    id                   text PRIMARY KEY,
    anonymous_id         text NOT NULL,
    user_id              text NOT NULL,             -- CUS_... code (identify always has a user_id)
    traits               jsonb,                     -- {email, name, country, plan, ...} (PII inside)
    email                text,                      -- denormalized trait (PII, often dirty)
    phone                text,                      -- denormalized trait (PII, dirty format)
    context_ip           inet,                      -- PII
    context_app_version  text,
    context_device_type  text,
    timestamp            timestamptz,
    received_at          timestamptz NOT NULL,
    loaded_at            timestamptz
);

-- pages. Web `page` calls (the marketing site + web app).
CREATE TABLE IF NOT EXISTS raw_segment.pages (
    id                   text PRIMARY KEY,
    anonymous_id         text NOT NULL,
    user_id              text,                       -- often null on web
    name                 text,                       -- page name ('Home', 'Pricing', 'Send')
    category             text,
    properties           jsonb,                      -- {url, path, referrer, search, title}
    context_ip           inet,                       -- PII
    context_page_url     text,
    context_page_referrer text,
    context_user_agent   text,
    timestamp            timestamptz,
    received_at          timestamptz NOT NULL
);

-- screens. Mobile `screen` calls (iOS/Android in-app navigation).
CREATE TABLE IF NOT EXISTS raw_segment.screens (
    id                   text PRIMARY KEY,
    anonymous_id         text NOT NULL,
    user_id              text,
    name                 text,                       -- screen name ('SendMoney', 'KYC', 'Recipients')
    properties           jsonb,
    context_app_version  text,
    context_device_type  text,
    context_device_id    text,                       -- PII
    context_os_name      text,
    timestamp            timestamptz,
    received_at          timestamptz NOT NULL
);

-- groups. `group` calls — associates a user with a group (used for Rafiki B2B
-- merchant accounts on the analytics side). Sparse.
CREATE TABLE IF NOT EXISTS raw_segment.groups (
    id                   text PRIMARY KEY,
    anonymous_id         text,
    user_id              text,                       -- CUS_...
    group_id             text NOT NULL,              -- merchant / org id
    traits               jsonb,                      -- {name, plan, industry}
    timestamp            timestamptz,
    received_at          timestamptz NOT NULL
);
