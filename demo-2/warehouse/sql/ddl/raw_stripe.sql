-- ===========================================================================
-- raw_stripe — Stripe API landing tables (Domain 6: Funding & Banking Rails)
-- Authentic Stripe API style:
--   * ids like ch_/pi_/cus_/po_/re_/dp_/txn_/pm_/evt_
--   * `created` as epoch SECONDS (bigint)
--   * amounts in MINOR units (cents, integer)
--   * `metadata` jsonb on most objects
-- These objects represent how NALA app users FUND their transfers (card/debit).
-- Messy: legacy free-text statuses, sparse nulls, deprecated columns, a
-- soft-delete flag on customers, denormalized card brand on charges.
-- NO cross-schema FK constraints (realistic).
-- ===========================================================================
CREATE SCHEMA IF NOT EXISTS raw_stripe;

-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_stripe.customers (
    id              text PRIMARY KEY,            -- cus_...
    object          text,                        -- 'customer'
    created         bigint,                      -- epoch SECONDS
    email           text,                        -- PII (dirty)
    name            text,                        -- PII
    phone           text,                        -- PII (dirty)
    description      text,
    currency        text,                        -- default presentment ccy
    delinquent      boolean,
    livemode        boolean,
    nala_customer_code text,                      -- CUS_00000123 cross-source key
    default_source  text,                        -- legacy card id (deprecated)
    invoice_prefix  text,
    deleted         boolean,                     -- soft delete flag
    deleted_at      bigint,                      -- epoch s, sparse
    metadata        jsonb
);

-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_stripe.payment_methods (
    id              text PRIMARY KEY,            -- pm_...
    object          text,                        -- 'payment_method'
    created         bigint,                      -- epoch s
    customer        text,                        -- cus_...
    type            text,                        -- 'card' | 'us_bank_account' | 'link'
    card_brand      text,                        -- visa/mastercard/amex/discover (PII-ish)
    card_last4      text,                        -- PII
    card_bin        text,                        -- PII (issuer identification number)
    card_exp_month  integer,
    card_exp_year   integer,
    card_funding    text,                        -- credit/debit/prepaid
    card_country    text,
    card_fingerprint text,                        -- dedupe token (PII-ish)
    billing_email   text,                        -- PII (dirty), sparse
    livemode        boolean,
    metadata        jsonb
);

-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_stripe.payment_intents (
    id              text PRIMARY KEY,            -- pi_...
    object          text,                        -- 'payment_intent'
    created         bigint,                      -- epoch s
    amount          bigint,                      -- MINOR units (cents)
    amount_received bigint,                      -- MINOR units
    currency        text,                        -- lowercase per Stripe (gbp/usd/eur)
    status          text,                        -- succeeded/requires_payment_method/canceled/processing/legacy values
    customer        text,                        -- cus_...
    payment_method  text,                        -- pm_...
    latest_charge   text,                        -- ch_...
    capture_method  text,                        -- automatic/manual
    confirmation_method text,
    description      text,
    statement_descriptor text,
    nala_transfer_id text,                        -- uuid: transfer being funded (sparse, dirty)
    canceled_at     bigint,                      -- epoch s, sparse
    cancellation_reason text,
    metadata        jsonb
);

-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_stripe.charges (
    id              text PRIMARY KEY,            -- ch_...
    object          text,                        -- 'charge'
    created         bigint,                      -- epoch s
    amount          bigint,                      -- MINOR units (cents)
    amount_captured bigint,                      -- MINOR units
    amount_refunded bigint,                      -- MINOR units
    currency        text,
    status          text,                        -- succeeded/pending/failed + legacy 'paid'
    paid            boolean,
    captured        boolean,
    refunded        boolean,
    disputed        boolean,
    customer        text,                        -- cus_...
    payment_intent  text,                        -- pi_...
    payment_method  text,                        -- pm_...
    balance_transaction text,                     -- txn_...
    -- denormalized card snapshot (Stripe embeds payment_method_details)
    card_brand      text,                        -- PII-ish
    card_last4      text,                        -- PII
    card_funding    text,
    card_country    text,
    receipt_email   text,                        -- PII (dirty), sparse
    failure_code    text,                        -- sparse
    failure_message text,                        -- sparse
    outcome_type    text,                        -- authorized/issuer_declined/blocked
    risk_level      text,                        -- normal/elevated/highest
    livemode        boolean,
    metadata        jsonb
);

-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_stripe.refunds (
    id              text PRIMARY KEY,            -- re_...
    object          text,                        -- 'refund'
    created         bigint,                      -- epoch s
    amount          bigint,                      -- MINOR units
    currency        text,
    charge          text,                        -- ch_...
    payment_intent  text,                        -- pi_...
    balance_transaction text,                     -- txn_...
    reason          text,                        -- requested_by_customer/fraudulent/duplicate
    status          text,                        -- succeeded/pending/failed/canceled
    receipt_number  text,
    metadata        jsonb
);

-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_stripe.disputes (
    id              text PRIMARY KEY,            -- dp_...
    object          text,                        -- 'dispute'
    created         bigint,                      -- epoch s
    amount          bigint,                      -- MINOR units
    currency        text,
    charge          text,                        -- ch_...
    payment_intent  text,                        -- pi_...
    balance_transaction text,                     -- txn_...
    reason          text,                        -- fraudulent/product_not_received/duplicate/...
    status          text,                        -- warning_needs_response/needs_response/under_review/won/lost
    is_charge_refundable boolean,
    evidence_due_by bigint,                       -- epoch s, sparse
    metadata        jsonb
);

-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_stripe.payouts (
    id              text PRIMARY KEY,            -- po_...
    object          text,                        -- 'payout'
    created         bigint,                      -- epoch s
    arrival_date    bigint,                       -- epoch s
    amount          bigint,                       -- MINOR units
    currency        text,
    status          text,                         -- paid/pending/in_transit/canceled/failed
    type            text,                         -- bank_account/card
    method          text,                         -- standard/instant
    destination     text,                         -- ba_... (Stripe bank account id)
    bank_name       text,
    bank_last4      text,                          -- PII
    statement_descriptor text,
    failure_code    text,                          -- sparse
    automatic       boolean,
    metadata        jsonb
);

-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_stripe.balance_transactions (
    id              text PRIMARY KEY,            -- txn_...
    object          text,                        -- 'balance_transaction'
    created         bigint,                      -- epoch s
    available_on    bigint,                       -- epoch s
    amount          bigint,                       -- MINOR units (signed: + charge, - refund/fee/payout)
    net             bigint,                       -- MINOR units (amount - fee)
    fee             bigint,                       -- MINOR units
    currency        text,
    type            text,                         -- charge/refund/payout/adjustment/stripe_fee
    status          text,                         -- available/pending
    source          text,                         -- ch_/re_/po_... source object id
    reporting_category text,
    description      text
);

-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_stripe.events (
    id              text PRIMARY KEY,            -- evt_...
    object          text,                        -- 'event'
    created         bigint,                      -- epoch s
    type            text,                         -- charge.succeeded/payment_intent.created/...
    api_version     text,                         -- legacy api version drift
    livemode        boolean,
    request_id      text,                         -- req_... sparse
    object_id       text,                         -- id of the object in data.object
    data            jsonb                         -- raw event payload (semi-structured)
);
