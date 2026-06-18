-- =====================================================================
-- Domain 10 — SendGrid (raw_sendgrid)
-- Transactional + marketing email. NALA sends receipts, OTP, KYC and
-- promo emails to customers and tracks engagement events.
--
-- Source system: Twilio SendGrid v3 Mail Send + Event Webhook.
-- Naming follows SendGrid's real style: "sg_message_id", event objects
-- with epoch-second "timestamp", category arrays, snake_case columns.
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS raw_sendgrid;

-- ---------------------------------------------------------------------
-- Messages — one row per email send. to_email references a customer
-- (dirtied). Categories are SendGrid template categories.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_sendgrid.messages (
    sg_message_id      text PRIMARY KEY,        -- SendGrid message id
    to_email           text,                    -- PII (dirty casing/space)
    from_email         text,                    -- noreply@nala.com etc
    subject            text,
    template_id        text,                    -- d-xxxxxxxx dynamic template
    category           text,                    -- otp / receipt / kyc / marketing
    asm_group_id       integer,                 -- unsubscribe group (sparse)
    msg_status         text,                    -- processed / delivered / bounce / dropped
    opens_count        integer,                 -- denormalized rollup
    clicks_count       integer,                 -- denormalized rollup
    customer_id        bigint,                  -- resolved canonical cid (sparse)
    ip_pool            text,                    -- sending IP pool name
    is_marketing       boolean,
    sent_at            text,                    -- ISO-Z string drift
    raw_payload        jsonb                    -- mail send request blob
);

-- ---------------------------------------------------------------------
-- Events — SendGrid Event Webhook rows (fanned out per message).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_sendgrid.events (
    event_id           text PRIMARY KEY,        -- sg_event_id
    sg_message_id      text,                    -- FK-ish to messages
    email              text,                    -- PII (recipient at event time)
    event              text,                    -- processed/delivered/open/click/bounce/spamreport/unsubscribe
    timestamp          bigint,                  -- epoch SECONDS (SendGrid native)
    smtp_id            text,                    -- <...> smtp message id (sparse)
    category           text,                    -- first category (sparse)
    url                text,                    -- for click events (sparse)
    useragent          text,                    -- for open/click (sparse, PII-ish)
    ip                 inet,                    -- PII (open/click ip, sparse)
    reason             text,                    -- bounce/drop reason (sparse)
    bounce_type        text,                    -- blocked / bounce (sparse)
    response           text,                    -- smtp response (sparse)
    customer_id        bigint                   -- resolved canonical cid (sparse)
);
