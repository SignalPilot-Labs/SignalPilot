-- ===========================================================================
-- raw_marqeta — Marqeta card-issuing landing tables (Domain 6).
-- NALA issues its own (virtual/physical) cards via Marqeta for the
-- multi-currency wallet / spend product. Marqeta API style:
--   * tokens are uuid-ish strings (`token`) on every object
--   * timestamps as ISO-8601 with timezone offset strings
--   * amounts in MAJOR units (decimal) with a currency_code
--   * NEVER full PAN — store last_four + pan token only.
-- PII: cardholder name/email/phone, card last_four, pan_token.
-- Messy: ISO-offset string timestamps, legacy state enums, sparse pii,
-- denormalized cardholder token on transactions, soft 'active' flag.
-- NO cross-schema FK constraints.
-- ===========================================================================
CREATE SCHEMA IF NOT EXISTS raw_marqeta;

-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_marqeta.cardholders (
    token           text PRIMARY KEY,            -- user token (uuid-ish)
    nala_customer_code text,                       -- CUS_00000123 cross-source key
    first_name      text,                        -- PII
    last_name       text,                        -- PII
    email           text,                        -- PII (dirty)
    phone           text,                        -- PII (dirty)
    birth_date      text,                        -- 'YYYY-MM-DD' (PII), sparse
    address1        text,                        -- PII
    city            text,                        -- PII
    state           text,                        -- PII
    postal_code     text,                        -- PII
    country         text,
    active          boolean,
    status          text,                        -- ACTIVE/SUSPENDED/UNVERIFIED/LIMITED
    uses_parent_account boolean,                  -- legacy/deprecated
    created_time    text,                         -- ISO-8601 with offset, e.g. 2025-03-04T11:02:00+00:00
    last_modified_time text
);

-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_marqeta.cards (
    token           text PRIMARY KEY,            -- card token
    user_token      text,                        -- -> cardholders.token
    card_product_token text,                      -- the issued product
    last_four       text,                        -- PII
    pan_token       text,                        -- tokenized PAN reference (PII) — NEVER full PAN
    expiration      text,                        -- 'MMYY'
    expiration_time text,                         -- ISO-8601 offset
    barcode         text,                         -- sparse
    pin_is_set      boolean,
    state           text,                         -- ACTIVE/SUSPENDED/TERMINATED/UNACTIVATED
    state_reason    text,                         -- sparse free text
    fulfillment_status text,                      -- ISSUED/ORDERED/SHIPPED/DIGITALLY_PRESENTED
    instrument_type text,                         -- VIRTUAL_PAN/PHYSICAL_MSR
    created_time    text                          -- ISO-8601 offset
);

-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_marqeta.card_transactions (
    token           text PRIMARY KEY,            -- transaction token
    type            text,                         -- authorization/authorization.clearing/refund/...
    state           text,                         -- PENDING/CLEARED/COMPLETION/DECLINED/ERROR
    user_token      text,                         -- -> cardholders.token (denormalized)
    card_token      text,                         -- -> cards.token
    amount          numeric(18,2),               -- MAJOR units
    currency_code   text,                         -- GBP/USD/EUR
    approval_code   text,                         -- sparse
    response_code   text,                         -- gateway response code
    response_memo   text,                         -- free text
    network         text,                         -- VISA/MASTERCARD/PULSE/MAESTRO
    acquirer_mid    text,                         -- merchant id
    merchant_name   text,                         -- PII-ish free text
    mcc             text,                         -- merchant category code
    merchant_country text,
    is_recurring    boolean,
    nala_transfer_id text,                          -- uuid this spend relates to (sparse, dirty)
    funding_source_token text,                      -- -> funding_sources.token
    user_transaction_time text,                     -- ISO-8601 offset
    settlement_date text                            -- 'YYYY-MM-DD' sparse
);

-- ---------------------------------------------------------------------------
-- Where a card draws funds from (the NALA program-funding account, or a
-- linked external bank — the GPA / program funding source).
CREATE TABLE IF NOT EXISTS raw_marqeta.funding_sources (
    token           text PRIMARY KEY,            -- funding source token
    user_token      text,                        -- -> cardholders.token (null = program-level)
    type            text,                        -- gpa/program/ach
    name            text,                        -- 'NALA GBP Program Funding'
    name_on_account text,                        -- PII, sparse
    account_suffix  text,                        -- last4 of linked acct (PII), sparse
    active          boolean,
    is_default_account boolean,
    currency_code   text,
    created_time    text                          -- ISO-8601 offset
);
