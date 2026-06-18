-- =====================================================================
-- Domain 10 — Twilio (raw_twilio)
-- Programmable SMS + Lookup. NALA sends OTP / notification SMS to
-- customers and runs phone-number lookups for verification.
--
-- Source system: Twilio Programmable Messaging + Lookup v2 API.
-- Naming follows Twilio's real API style: SID columns ("MessageSid",
-- "AccountSid"), CamelCase status enums, epoch-ish timestamps as RFC2822
-- strings ("date_sent"), amounts as signed string "price" in USD.
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS raw_twilio;

-- ---------------------------------------------------------------------
-- Messages — one row per outbound (and a few inbound) SMS.
-- Recipient phone references a customer_master phone (dirtied).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_twilio.messages (
    message_sid        text PRIMARY KEY,        -- SM... Twilio message SID
    account_sid        text,                    -- AC... Twilio account SID
    messaging_service_sid text,                 -- MG... (sparse)
    to_number          text,                    -- PII (dirty E.164 drift)
    from_number        text,                    -- NALA sender / shortcode
    body               text,                    -- message text (OTP redacted-ish)
    num_segments       integer,
    num_media          integer,
    direction          text,                    -- outbound-api / inbound
    message_type       text,                    -- otp / notification / marketing
    status             text,                    -- queued/sent/delivered/undelivered/failed
    error_code         integer,                 -- Twilio error code (sparse)
    error_message      text,                    -- sparse
    price              text,                    -- signed string e.g. "-0.0075" (USD)
    price_unit         text,                    -- "USD"
    customer_id        bigint,                  -- resolved canonical cid (sparse)
    date_created       text,                    -- RFC2822 string drift
    date_sent          text,                    -- RFC2822 string (sparse if queued)
    date_updated       text,                    -- RFC2822 string
    api_version        text,                    -- legacy "2010-04-01"
    raw_payload        jsonb                    -- vendor webhook blob
);

-- ---------------------------------------------------------------------
-- Phone lookups — Lookup v2 carrier / line-type intelligence calls.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_twilio.phone_lookups (
    lookup_sid         text PRIMARY KEY,        -- internal lookup id
    phone_number       text,                    -- PII (E.164, queried number)
    national_format    text,                    -- PII (national formatting)
    country_code       text,                    -- ISO2
    calling_country_code text,                  -- +44 etc
    valid              boolean,
    validation_errors  text,                    -- comma list (sparse)
    line_type          text,                    -- mobile / landline / voip / nonFixedVoip
    carrier_name       text,                    -- Safaricom / Vodafone UK ...
    carrier_mcc        text,                    -- mobile country code (sparse)
    carrier_mnc        text,                    -- mobile network code (sparse)
    sim_swap_risk      text,                    -- low / medium / high (sparse)
    customer_id        bigint,                  -- resolved canonical cid (sparse)
    created_epoch_ms   bigint,                  -- epoch ms drift
    raw_response       jsonb
);
