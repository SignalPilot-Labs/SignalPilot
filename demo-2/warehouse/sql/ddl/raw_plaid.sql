-- ===========================================================================
-- raw_plaid — Plaid API landing tables (Domain 6: Funding & Banking Rails)
-- Plaid links a NALA user's external bank account so we can pull funds (ACH)
-- and verify identity. Plaid API style:
--   * ids like item_.../acc_... (item_id, account_id are opaque base64-ish)
--   * ISO-8601 string timestamps and `date` strings
--   * balances + amounts in MAJOR units (decimal, account currency)
-- PII: bank account / routing numbers, names, emails, phones, addresses.
-- Messy: ISO string timestamps (not epoch), legacy status enums, sparse pii,
-- pending vs posted transactions, denormalized institution name.
-- NO cross-schema FK constraints.
-- ===========================================================================
CREATE SCHEMA IF NOT EXISTS raw_plaid;

-- ---------------------------------------------------------------------------
-- A linked financial institution connection for one NALA user.
CREATE TABLE IF NOT EXISTS raw_plaid.items (
    item_id         text PRIMARY KEY,            -- opaque
    institution_id  text,                        -- ins_...
    institution_name text,                        -- denormalized
    nala_customer_code text,                       -- CUS_00000123 cross-source key
    nala_customer_email text,                      -- PII (dirty) alt join key
    webhook         text,
    available_products text,                       -- comma list (legacy free text)
    billed_products text,
    status          text,                          -- good/login_required/pending_expiration/ITEM_LOGIN_REQUIRED(legacy)
    consent_expiration_time text,                   -- ISO-8601 Z string, sparse
    error_code      text,                          -- sparse
    created_at      text,                           -- ISO-8601 string (NOT epoch)
    updated_at      text                            -- ISO-8601 string
);

-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_plaid.accounts (
    account_id      text PRIMARY KEY,            -- opaque
    item_id         text,                        -- -> items.item_id
    name            text,                        -- 'Plaid Checking'
    official_name   text,                        -- sparse
    mask            text,                        -- last 4 of acct (PII)
    type            text,                        -- depository/credit/loan
    subtype         text,                        -- checking/savings/credit card
    available_balance numeric(18,2),             -- MAJOR units
    current_balance numeric(18,2),               -- MAJOR units
    iso_currency_code text,                       -- GBP/USD/EUR
    verification_status text,                     -- automatically_verified/pending_manual_verification/manually_verified
    created_at      text                           -- ISO-8601 string
);

-- ---------------------------------------------------------------------------
-- The /auth product — account + routing numbers used for ACH debit. Heavy PII.
CREATE TABLE IF NOT EXISTS raw_plaid.auth_numbers (
    id              bigserial PRIMARY KEY,
    account_id      text,                        -- -> accounts.account_id
    item_id         text,
    routing         text,                        -- ACH routing number (PII)
    account         text,                        -- full bank account number (PII)
    wire_routing    text,                        -- sparse (PII)
    account_type    text,                        -- ach/eft/international
    created_at      text                           -- ISO-8601 string
);

-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_plaid.transactions (
    transaction_id  text PRIMARY KEY,            -- opaque
    account_id      text,                        -- -> accounts.account_id
    item_id         text,
    amount          numeric(18,2),               -- MAJOR units; Plaid sign: positive = money OUT
    iso_currency_code text,
    date            text,                         -- 'YYYY-MM-DD' posted date string
    authorized_date text,                         -- 'YYYY-MM-DD' sparse
    name            text,                         -- merchant/description free text
    merchant_name   text,                         -- sparse, cleaned
    payment_channel text,                         -- online/in store/other
    pending         boolean,
    category        text,                         -- legacy comma list e.g. 'Transfer,Debit'
    personal_finance_category text,                -- new taxonomy primary
    pending_transaction_id text,                   -- links pending->posted (sparse)
    nala_transfer_id text,                          -- uuid funding a transfer (sparse, dirty)
    created_at      text                            -- ISO-8601 ingestion ts
);

-- ---------------------------------------------------------------------------
-- The /identity product — names/phones/emails/addresses on the linked account.
CREATE TABLE IF NOT EXISTS raw_plaid.identity_data (
    id              bigserial PRIMARY KEY,
    account_id      text,                        -- -> accounts.account_id
    item_id         text,
    nala_customer_code text,                       -- CUS_00000123
    full_name       text,                        -- PII
    primary_email   text,                        -- PII (dirty)
    primary_phone   text,                        -- PII (dirty)
    street          text,                        -- PII
    city            text,                        -- PII
    region          text,                        -- PII (state/county)
    postal_code     text,                        -- PII
    country         text,
    emails_json     jsonb,                        -- all emails (semi-structured PII)
    created_at      text                           -- ISO-8601 string
);
