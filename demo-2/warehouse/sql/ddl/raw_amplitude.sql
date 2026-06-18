-- raw_amplitude — Amplitude product-analytics export.
-- Source system: Amplitude (Export API / warehouse sync). Vendor style: snake_case
-- Amplitude field names (event_type, event_time stored as epoch ms, event_properties
-- and user_properties jsonb, amplitude_id + user_id). NALA dual-instruments some
-- events through both Segment and Amplitude — expect overlap with raw_segment.
CREATE SCHEMA IF NOT EXISTS raw_amplitude;

-- events (FACT). One row per Amplitude event. event_time is epoch MILLISECONDS
-- (bigint) — classic Amplitude export shape and a deliberate format-drift trap.
CREATE TABLE IF NOT EXISTS raw_amplitude.events (
    uuid                 text PRIMARY KEY,          -- Amplitude event uuid
    event_id             bigint,                    -- per-user monotonic event id
    amplitude_id         bigint NOT NULL,           -- Amplitude's internal user id
    user_id              text,                      -- CUS_... code; NULL for anonymous (PII link)
    device_id            text,                      -- PII (maps to Segment anonymous_id)
    session_id           bigint,                    -- epoch ms of session start, -1 if none
    event_type           text NOT NULL,            -- 'Transfer Completed', 'Session Start', ...
    event_time           bigint NOT NULL,          -- EPOCH MS (vendor format drift)
    client_event_time    bigint,                    -- EPOCH MS as reported by client
    server_upload_time   bigint,                    -- EPOCH MS server received (load watermark)
    event_properties     jsonb,                     -- event payload
    user_properties      jsonb,                     -- snapshot of user props at event time
    app_version          text,                      -- '4.2.0'
    platform             text,                      -- iOS / Android / Web
    os_name              text,
    country              text,
    region               text,
    city                 text,
    ip_address           inet,                      -- PII
    idfa                 text,                      -- PII (iOS advertising id), null on android/web
    adid                 text,                      -- PII (android advertising id / GAID)
    is_attribution_event boolean DEFAULT false
);

-- user_properties. Latest known property snapshot per Amplitude user (denormalized
-- profile). One row per amplitude_id. Mutable in real life; we load a snapshot.
CREATE TABLE IF NOT EXISTS raw_amplitude.user_properties (
    amplitude_id         bigint PRIMARY KEY,
    user_id              text,                      -- CUS_... code (nullable for anon-only users)
    device_id            text,                      -- PII
    first_seen_at        timestamptz,
    last_seen_at         timestamptz,
    properties           jsonb,                     -- {plan, country, kyc_status, lifetime_transfers, ...}
    country              text,
    city                 text,
    platform             text,
    paying               boolean,                   -- has completed >=1 transfer
    cohort               text                       -- legacy single-cohort label (deprecated)
);

-- cohorts (lookup-ish). Behavioral cohorts defined in the Amplitude UI.
CREATE TABLE IF NOT EXISTS raw_amplitude.cohorts (
    cohort_id            text PRIMARY KEY,          -- amplitude cohort id
    name                 text NOT NULL,             -- 'Activated Senders', 'Churn Risk - KE', ...
    description          text,
    cohort_type          text,                      -- static / dynamic
    size                 integer,                   -- member count at definition time
    owner                text,                      -- analyst email (PII-ish)
    created_at           timestamptz NOT NULL,
    last_computed_at     timestamptz,
    archived             boolean DEFAULT false
);
