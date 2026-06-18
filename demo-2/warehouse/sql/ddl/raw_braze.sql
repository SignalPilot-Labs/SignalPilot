-- =====================================================================
-- raw_braze — Braze customer-engagement / messaging platform
-- Source system: Braze REST + Currents export. Vendor API style: snake_case,
-- ids are 24-hex "api_id" strings, timestamps mostly ISO-8601 with tz ('Z').
-- messages_sent is a Currents-style event stream (one row per send).
-- NO cross-schema FK constraints (realistic). PKs within a table only.
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS raw_braze;

-- ---------------------------------------------------------------------
-- campaigns — single-step messaging campaigns
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_braze.campaigns (
    campaign_id      text PRIMARY KEY,            -- 24-hex api_id
    name             text NOT NULL,
    channel          text,                        -- email / push / in_app_message / sms / webhook
    messaging_type   text,                        -- promotional / transactional
    tags             jsonb,                       -- array of tag strings
    status           text,                        -- active / draft / archived / STOPPED (legacy)
    is_archived      boolean DEFAULT false,
    first_sent       text,                        -- ISO-Z string (Braze "first_sent")
    last_sent        text,                        -- ISO-Z string
    created_at       timestamptz,                 -- tz
    updated_at       timestamptz,
    metadata         jsonb                        -- vendor payload blob
);

-- ---------------------------------------------------------------------
-- canvases — multi-step orchestration journeys (Braze "Canvas")
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_braze.canvases (
    canvas_id        text PRIMARY KEY,            -- 24-hex api_id
    name             text NOT NULL,
    tags             jsonb,
    num_steps        integer,
    status           text,                        -- active / draft / archived
    is_archived      boolean DEFAULT false,
    enabled          boolean,
    first_entry      text,                        -- ISO-Z string
    last_entry       text,                        -- ISO-Z string
    created_at       timestamptz,
    updated_at       timestamptz
);

-- ---------------------------------------------------------------------
-- segments — audience definitions
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_braze.segments (
    segment_id       text PRIMARY KEY,            -- 24-hex api_id
    name             text NOT NULL,
    description      text,
    analytics_tracking_enabled boolean,
    tags             jsonb,
    estimated_size   bigint,                      -- last computed member count
    created_at       timestamptz,
    updated_at       timestamptz
);

-- ---------------------------------------------------------------------
-- messages_sent — Currents-style send event stream (one row per message)
-- This is the fact table. references a NALA customer via external_user_id
-- (the canonical customer code 'CUS_XXXXXXXX') + dirty email.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_braze.messages_sent (
    id                 bigint PRIMARY KEY,
    dispatch_id        text,                       -- 24-hex, groups a send
    campaign_id        text,                       -- nullable when from a canvas
    canvas_id          text,                       -- nullable when from a campaign
    external_user_id   text,                       -- NALA customer code 'CUS_00000123'
    user_id            text,                       -- Braze internal id (24-hex)
    email              text,                       -- PII, dirty (push/sms rows null)
    channel            text,                       -- email / push / sms / in_app_message
    message_variation  text,                       -- A / B / control
    event_type         text,                       -- sent / delivered / open / click / bounce / unsubscribe
    sent_at            text,                        -- ISO-Z string (Currents 'time')
    "time"             bigint,                      -- epoch s duplicate (Currents raw)
    is_amp             boolean,
    metadata           jsonb
);

-- ---------------------------------------------------------------------
-- custom_events — tracked product/business events forwarded to Braze
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_braze.custom_events (
    id               bigint PRIMARY KEY,
    external_user_id text,                          -- NALA customer code
    name             text,                          -- 'transfer_completed' / 'kyc_passed' / ...
    properties       jsonb,                         -- semi-structured payload
    app_id           text,
    "time"           bigint,                        -- epoch ms (drift vs messages_sent epoch s)
    received_at      text                           -- ISO string, no tz (legacy)
);
