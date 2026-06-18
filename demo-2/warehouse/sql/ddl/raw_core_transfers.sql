-- =====================================================================
-- Domain 1 — Core Transfers (raw_core_transfers)
-- The heart of the NALA product: sender accounts, recipients, and the
-- central transfers FACT table plus its supporting dimensions/lookups.
--
-- Source system: NALA internal core ("monolith" + transfers service).
-- Naming within this domain mostly uses internal snake_case `created_at`,
-- but legacy tables (saved_recipients) and vendor-touched columns drift.
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS raw_core_transfers;

-- ---------------------------------------------------------------------
-- Lookups
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_core_transfers.corridors (
    corridor_id        bigint PRIMARY KEY,
    corridor_code      text,            -- e.g. GB_KE, US_NG
    send_country       text,
    send_currency      text,
    receive_country    text,
    receive_currency   text,
    default_rail       text,            -- M-PESA / Bank / MTN MoMo ...
    is_active          boolean,
    launched_on        date,
    created_at         timestamptz
);

CREATE TABLE IF NOT EXISTS raw_core_transfers.cancellation_reasons (
    reason_id          bigint PRIMARY KEY,
    reason_code        text,            -- COMPLIANCE_HOLD, USER_CANCELLED ...
    reason_label       text,
    category           text,            -- compliance / user / partner / system
    is_user_facing     boolean
);

CREATE TABLE IF NOT EXISTS raw_core_transfers.referral_codes (
    referral_code_id   bigint PRIMARY KEY,
    code               text,            -- the shareable code, e.g. BEN2024
    owner_cid          bigint,          -- canonical customer id of code owner
    reward_amount      numeric(18,2),
    reward_currency    text,
    max_redemptions    integer,
    times_redeemed     integer,
    is_active          boolean,
    created_at         timestamptz,
    expires_at         timestamptz
);

-- ---------------------------------------------------------------------
-- Customer (sender) accounts — PII heavy. References customer_master.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_core_transfers.customers (
    customer_id        bigint PRIMARY KEY,   -- canonical cid
    customer_uuid      uuid,
    customer_code      text,                 -- CUS_00000123
    first_name         text,
    last_name          text,
    email              text,                 -- dirty (casing/space drift)
    phone              text,                 -- dirty (format drift)
    date_of_birth      date,
    country            text,                 -- send-from country
    currency           text,                 -- default debit currency
    national_id        text,                 -- PII
    national_id_hash   text,                 -- partial-governance mimic
    kyc_tier           text,                 -- tier0/tier1/tier2/tier3
    account_status     text,                 -- active/suspended/closed (free text)
    signup_platform    text,                 -- ios/android/web
    signup_country     text,
    marketing_opt_in   boolean,
    is_deleted         boolean,
    deleted_at         timestamptz,
    created_at         timestamptz,
    updated_at         timestamptz,
    raw_attributes     jsonb                 -- denormalized snapshot blob
);

CREATE TABLE IF NOT EXISTS raw_core_transfers.customer_addresses (
    address_id         bigint PRIMARY KEY,
    customer_id        bigint,
    address_type       text,                 -- home / billing / proof_of_address
    line1              text,                 -- PII
    line2              text,
    city               text,
    postcode           text,
    country            text,
    is_primary         boolean,
    verified           boolean,
    created            text                  -- legacy: ISO string, not tz
);

CREATE TABLE IF NOT EXISTS raw_core_transfers.customer_devices (
    device_id          text PRIMARY KEY,     -- vendor device id string
    customer_id        bigint,
    platform           text,                 -- ios/android/web
    app_version        text,
    os_version         text,
    device_model       text,
    push_token         text,                 -- PII-ish
    ip_address         inet,                 -- PII
    last_seen_at       text,                 -- ISO-Z string drift
    is_trusted         boolean,
    first_seen_epoch_ms bigint               -- epoch ms drift
);

CREATE TABLE IF NOT EXISTS raw_core_transfers.customer_kyc_status (
    kyc_status_id      bigint PRIMARY KEY,
    customer_id        bigint,
    provider           text,                 -- Onfido / Jumio / Persona
    tier               text,
    status             text,                 -- approved / pending / rejected / PENDING_OLD
    risk_rating        text,                 -- low / medium / high
    submitted_at       text,                 -- ISO string
    decided_at         timestamptz,
    document_type      text,                 -- passport / national_id / drivers_license
    document_number    text,                 -- PII
    is_current         boolean
);

-- ---------------------------------------------------------------------
-- Recipients (beneficiaries) — PII. Belong to a sending customer.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_core_transfers.recipients (
    recipient_id       bigint PRIMARY KEY,
    recipient_uuid     uuid,
    customer_id        bigint,               -- owning sender
    first_name         text,                 -- PII
    last_name          text,                 -- PII
    full_name          text,                 -- denormalized PII
    receive_country    text,
    receive_currency   text,
    relationship       text,                 -- family / friend / self / business
    phone              text,                 -- PII (dirty)
    email              text,                 -- PII, sparse
    date_of_birth      date,                 -- PII, sparse
    is_active          boolean,
    is_deleted         boolean,
    created_at         timestamptz,
    updated_at         timestamptz
);

CREATE TABLE IF NOT EXISTS raw_core_transfers.recipient_payout_methods (
    payout_method_id   bigint PRIMARY KEY,
    recipient_id       bigint,
    method_type        text,                 -- mobile_money / bank / wallet
    rail               text,                 -- M-PESA / MTN MoMo / Bank ...
    provider           text,                 -- Safaricom / Equity Bank ...
    msisdn             text,                 -- PII (mobile money number)
    bank_name          text,
    account_number     text,                 -- PII
    account_name       text,                 -- PII
    iban               text,                 -- PII, sparse
    swift_bic          text,                 -- sparse
    is_default         boolean,
    is_verified        boolean,
    created_at         timestamptz
);

-- LEGACY near-duplicate of recipients — messy, deprecated, kept around.
CREATE TABLE IF NOT EXISTS raw_core_transfers.saved_recipients (
    id                 bigint PRIMARY KEY,   -- legacy pk name
    user_id            bigint,               -- legacy name for customer_id
    name               text,                 -- single free-text name field
    country            text,                 -- ISO2 OR full name (dirty)
    currency           text,
    mobile             text,                 -- legacy MSISDN, messy format
    acct_no            text,                 -- legacy account number
    payment_type       text,                 -- 'MPESA','BANK','momo' inconsistent
    created            bigint,               -- legacy: epoch ms
    updated            bigint,               -- legacy: epoch ms
    deleted            integer,              -- legacy soft-delete 0/1
    migrated_recipient_id bigint             -- link to recipients (often null)
);

-- ---------------------------------------------------------------------
-- TRANSFERS — the central FACT table (N["transfers"] rows)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_core_transfers.transfers (
    transfer_id        uuid PRIMARY KEY,     -- det_uuid(("transfer", i))
    reference          text,                 -- human ref NALA-XXXXXXXX
    customer_id        bigint,               -- sender (canonical cid)
    recipient_id       bigint,
    corridor_id        bigint,
    send_country       text,
    send_currency      text,
    receive_country    text,
    receive_currency   text,
    send_amount        numeric(18,2),        -- debited from sender
    receive_amount     numeric(18,2),        -- credited to recipient
    fee_amount         numeric(18,2),
    fee_currency       text,
    fx_rate            numeric(18,8),         -- send->receive applied rate
    mid_market_rate    numeric(18,8),
    fx_margin_bps      integer,               -- markup over mid in bps
    status             text,                  -- COMPLETED/PENDING/FAILED/CANCELLED/REFUNDED/PENDING_OLD
    rail               text,                  -- payout rail used
    payout_partner     text,                  -- Flutterwave / Thunes ...
    funding_method     text,                  -- card / bank_transfer / wallet / open_banking
    funding_partner    text,                  -- Stripe / Plaid / TrueLayer
    promo_code         text,                  -- applied promo (sparse)
    cancellation_reason_id bigint,            -- when cancelled (sparse)
    is_first_transfer  boolean,
    quote_id           uuid,                  -- link to quotes
    created_at         timestamptz,           -- initiated
    funded_at          timestamptz,
    completed_at       timestamptz,
    updated_at         timestamptz,
    source_ip          inet,                  -- PII
    raw_payload        jsonb                  -- vendor/internal blob
);

CREATE TABLE IF NOT EXISTS raw_core_transfers.transfer_legs (
    leg_id             bigint PRIMARY KEY,
    transfer_id        uuid,
    leg_type           text,                  -- funding / fx / payout
    sequence_no        integer,
    from_currency      text,
    to_currency        text,
    amount             numeric(18,2),
    partner            text,
    partner_reference  text,
    status             text,
    started_at         timestamptz,
    finished_at        timestamptz
);

CREATE TABLE IF NOT EXISTS raw_core_transfers.transfer_status_history (
    status_event_id    bigint PRIMARY KEY,
    transfer_id        uuid,
    from_status        text,
    to_status          text,
    changed_at         text,                  -- ISO-Z string drift
    changed_by         text,                  -- system / agent_email / partner_webhook
    note               text
);

CREATE TABLE IF NOT EXISTS raw_core_transfers.transfer_fees (
    fee_id             bigint PRIMARY KEY,
    transfer_id        uuid,
    fee_type           text,                  -- transfer / fx_margin / partner / promo_discount
    amount             numeric(18,2),         -- negative for discounts
    currency           text,
    is_waived          boolean,
    description        text,
    created_at         timestamptz
);

-- ---------------------------------------------------------------------
-- Quotes / FX quotes
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_core_transfers.quotes (
    quote_id           uuid PRIMARY KEY,
    customer_id        bigint,
    send_currency      text,
    receive_currency   text,
    send_amount        numeric(18,2),
    receive_amount     numeric(18,2),
    fee_amount         numeric(18,2),
    fx_rate            numeric(18,8),
    rail               text,
    converted          boolean,               -- did it become a transfer?
    transfer_id        uuid,                  -- set if converted (sparse)
    created_at         timestamptz,
    expires_at         timestamptz
);

CREATE TABLE IF NOT EXISTS raw_core_transfers.fx_quotes (
    fx_quote_id        uuid PRIMARY KEY,
    quote_id           uuid,
    base_currency      text,
    quote_currency     text,
    mid_market_rate    numeric(18,8),
    customer_rate      numeric(18,8),
    margin_bps         integer,
    rate_source        text,                  -- internal / OpenExchange
    locked             boolean,
    created            bigint,                -- epoch ms drift
    valid_until        bigint                 -- epoch ms drift
);

-- ---------------------------------------------------------------------
-- Payout attempts (a transfer may retry the payout rail)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_core_transfers.payout_attempts (
    attempt_id         bigint PRIMARY KEY,
    transfer_id        uuid,
    attempt_no         integer,
    partner            text,                  -- Flutterwave / Cellulant ...
    rail               text,
    partner_reference  text,
    msisdn             text,                  -- PII (target where applicable)
    account_number     text,                  -- PII (target where applicable)
    status             text,                  -- SUCCESS / FAILED / PENDING
    response_code      text,                  -- partner-specific code
    response_message   text,
    requested_at       text,                  -- ISO-Z string drift
    completed_at       timestamptz,
    raw_response       jsonb
);

-- ---------------------------------------------------------------------
-- Growth: promos & referrals
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_core_transfers.promo_redemptions (
    redemption_id      bigint PRIMARY KEY,
    customer_id        bigint,
    transfer_id        uuid,                  -- transfer the promo applied to (sparse)
    promo_code         text,
    promo_type         text,                  -- first_transfer / fee_waiver / fx_boost
    discount_amount    numeric(18,2),
    discount_currency  text,
    redeemed_at        timestamptz
);

CREATE TABLE IF NOT EXISTS raw_core_transfers.referrals (
    referral_id        bigint PRIMARY KEY,
    referral_code_id   bigint,
    referrer_cid       bigint,                -- customer who referred
    referee_cid        bigint,                -- new customer who joined
    status             text,                  -- pending / qualified / rewarded / expired
    reward_amount      numeric(18,2),
    reward_currency    text,
    qualifying_transfer_id uuid,              -- sparse
    referred_at        timestamptz,
    rewarded_at        timestamptz
);
