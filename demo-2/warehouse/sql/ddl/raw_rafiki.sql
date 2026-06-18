-- =====================================================================
-- raw_rafiki — Rafiki B2B payments / stablecoin settlement API
-- Source system: Rafiki internal platform DB (Postgres-backed microservices).
-- Vendor API style: camelCase-ish columns in some service tables, snake_case
-- in others (services built by different teams over time). Timestamp formats
-- drift between services. Some legacy/deprecated columns retained.
-- NO cross-schema FK constraints (realistic). PKs within a table only.
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS raw_rafiki;

-- ---------------------------------------------------------------------
-- merchants — onboarded B2B businesses using Rafiki
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_rafiki.merchants (
    merchant_id        text PRIMARY KEY,             -- 'mrc_<hex>'
    legal_name         text NOT NULL,
    display_name       text,
    website            text,
    country            text,                          -- HQ country (send-from style)
    default_settlement_currency text,                 -- local payout ccy
    accepts_stablecoins text,                          -- legacy CSV string e.g. 'USDC,USDT'
    industry           text,
    status             text,                          -- active / suspended / churned / PENDING_KYB (legacy)
    tier               text,                          -- standard / scale / enterprise
    mrr_usd            numeric(18,2),
    account_manager    text,
    is_test            boolean DEFAULT false,
    is_deleted         boolean DEFAULT false,
    deleted_at         timestamptz,
    metadata           jsonb,                          -- vendor payload blob
    created_at         timestamptz,                    -- ISO tz
    updated            text                            -- ISO string (no tz), legacy naming
);

-- ---------------------------------------------------------------------
-- merchant_users — people with login access to a merchant account (PII)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_rafiki.merchant_users (
    user_id        text PRIMARY KEY,                  -- 'usr_<hex>'
    merchant_id    text,
    full_name      text,
    email          text,                              -- PII, dirty
    phone          text,                              -- PII, dirty E.164
    role           text,                              -- owner / admin / developer / finance / viewer
    canonical_cid  bigint,                            -- some merchant users are also app customers (cross-source join)
    last_login_at  bigint,                            -- epoch ms (auth service style)
    is_active      boolean DEFAULT true,
    invited_by     text,
    created        text,                              -- ISO-Z string
    mfa_enabled    boolean
);

-- ---------------------------------------------------------------------
-- merchant_api_keys — API credentials (key prefix + hash, PII-ish)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_rafiki.merchant_api_keys (
    api_key_id   text PRIMARY KEY,                    -- 'ak_<hex>'
    merchant_id  text,
    key_prefix   text,                                -- 'rk_live_a1b2' (shown to user)
    key_hash     text,                                -- sha256-style hex of full key
    mode         text,                                -- live / test
    scopes       jsonb,                               -- array of scope strings
    label        text,
    created_by   text,                                -- user_id
    last_used_at timestamptz,
    revoked      boolean DEFAULT false,
    revoked_at   timestamptz,
    created_at   timestamptz
);

-- ---------------------------------------------------------------------
-- merchant_kyb — Know-Your-Business verification (compliance)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_rafiki.merchant_kyb (
    kyb_id            text PRIMARY KEY,
    merchant_id       text,
    legal_entity_name text,
    registration_number text,                          -- PII-ish company reg no
    tax_id            text,                            -- PII-ish
    incorporation_country text,
    incorporation_date date,
    beneficial_owner_name text,                        -- PII
    beneficial_owner_dob  text,                        -- PII (ISO date string)
    risk_rating       text,                            -- low / medium / high
    kyb_status        text,                            -- approved / pending / rejected / review
    provider          text,                            -- Onfido / Persona / internal
    verified_at       text,                            -- ISO-Z string (nullable until verified)
    documents         jsonb,                           -- list of doc refs
    created_at        timestamptz
);

-- ---------------------------------------------------------------------
-- rate_cards — pricing per merchant (lookup-ish, SCD-lite via effective dates)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_rafiki.rate_cards (
    rate_card_id    text PRIMARY KEY,
    merchant_id     text,
    name            text,
    collection_fee_bps   integer,                      -- basis points on collections
    payout_fee_bps       integer,
    fx_margin_bps        integer,
    flat_fee_usd         numeric(18,4),
    min_payout_usd       numeric(18,2),
    effective_from  date,
    effective_to    date,                              -- null = current
    is_current      boolean DEFAULT true,
    created_at      timestamptz
);

-- ---------------------------------------------------------------------
-- collections — inbound stablecoin received from merchants' payers
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_rafiki.collections (
    collection_id     text PRIMARY KEY,               -- 'col_<hex>'
    merchant_id       text,
    reference         text,                            -- merchant-supplied idempotency ref
    stablecoin        text,                            -- USDC / USDT / PYUSD
    chain             text,                            -- ethereum / polygon / tron / solana / base
    amount_crypto     numeric(38,6),                   -- amount in stablecoin units
    amount_usd        numeric(18,2),
    fee_usd           numeric(18,2),
    from_wallet       text,                            -- PII: payer crypto wallet address
    to_wallet         text,                            -- Rafiki deposit wallet
    tx_hash           text,                            -- on-chain tx hash
    confirmations     integer,
    status            text,                            -- confirmed / pending / failed / CONFIRMED_OLD (legacy)
    rate_card_id      text,
    settlement_id     text,                            -- nullable until swept into a settlement
    received_at       text,                            -- ISO-Z string (varies)
    confirmed_at      bigint,                          -- epoch ms (chain-listener service)
    metadata          jsonb
);

-- ---------------------------------------------------------------------
-- payouts — outbound B2B payouts in local currency to recipients
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_rafiki.payouts (
    payout_id        text PRIMARY KEY,                -- 'pyt_<hex>'
    merchant_id      text,
    idempotency_key  text,
    recipient_name   text,                             -- PII
    recipient_account text,                            -- PII: MSISDN / bank acct / IBAN
    recipient_type   text,                             -- mobile_money / bank
    rail             text,                             -- M-PESA / MTN MoMo / Bank / ...
    destination_country text,
    currency         text,                             -- local receive ccy
    amount_local     numeric(18,2),
    amount_usd       numeric(18,2),
    fx_rate          numeric(18,8),
    fee_usd          numeric(18,2),
    fx_lock_id       text,                             -- nullable
    status           text,                             -- paid / processing / failed / reversed / PENDING_OLD
    failure_reason   text,
    partner          text,                             -- payout rail partner (Flutterwave, Thunes...)
    settlement_id    text,                             -- nullable
    canonical_cid    bigint,                           -- some payouts go to app customers (cross-source)
    created          bigint,                           -- epoch ms (payout service)
    completed_at     text,                             -- ISO string (no tz), nullable
    metadata         jsonb
);

-- ---------------------------------------------------------------------
-- settlements — batch netting of collections vs payouts per merchant/day
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_rafiki.settlements (
    settlement_id     text PRIMARY KEY,               -- 'set_<hex>'
    merchant_id       text,
    settlement_date   date,
    currency          text,                            -- settlement ccy
    gross_collected_usd numeric(18,2),
    gross_paid_out_usd  numeric(18,2),
    total_fees_usd      numeric(18,2),
    net_amount_usd      numeric(18,2),
    line_count        integer,
    status            text,                            -- settled / pending / on_hold
    statement_url     text,
    created_at        timestamptz,
    settled_at        timestamptz
);

-- ---------------------------------------------------------------------
-- settlement_lines — individual entries rolling up into a settlement
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_rafiki.settlement_lines (
    settlement_line_id text PRIMARY KEY,
    settlement_id      text,
    merchant_id        text,
    line_type          text,                           -- collection / payout / fee / adjustment
    source_id          text,                           -- collection_id or payout_id
    description        text,
    amount_usd         numeric(18,2),
    direction          text,                           -- credit / debit
    created_at         timestamptz
);

-- ---------------------------------------------------------------------
-- invoices — billing for Rafiki platform fees to merchants
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_rafiki.invoices (
    invoice_id     text PRIMARY KEY,                  -- 'inv_<hex>'
    merchant_id    text,
    invoice_number text,                               -- 'RAF-2025-000123'
    period_start   date,
    period_end     date,
    currency       text,
    subtotal_usd   numeric(18,2),
    tax_usd        numeric(18,2),
    total_usd      numeric(18,2),
    amount_paid_usd numeric(18,2),
    status         text,                               -- draft / open / paid / void / past_due
    due_date       date,
    issued_at      timestamptz,
    paid_at        timestamptz,
    pdf_url        text,
    metadata       jsonb
);

-- ---------------------------------------------------------------------
-- invoice_line_items — detail rows on an invoice
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_rafiki.invoice_line_items (
    line_item_id  text PRIMARY KEY,
    invoice_id    text,
    merchant_id   text,
    item_type     text,                                -- collection_fees / payout_fees / fx_margin / platform_fee / minimum
    description   text,
    quantity      integer,
    unit_amount_usd numeric(18,4),
    amount_usd    numeric(18,2),
    created_at    timestamptz
);

-- ---------------------------------------------------------------------
-- balances — current per-merchant per-currency balance snapshot
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_rafiki.balances (
    balance_id      text PRIMARY KEY,
    merchant_id     text,
    currency        text,                              -- USD / USDC / KES / ...
    available_amount numeric(18,2),
    pending_amount   numeric(18,2),
    reserved_amount  numeric(18,2),
    as_of           timestamptz,                       -- snapshot time
    updated_at      timestamptz
);

-- ---------------------------------------------------------------------
-- balance_transactions — ledger of movements affecting a balance (FACT-ish)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_rafiki.balance_transactions (
    balance_txn_id text PRIMARY KEY,                  -- 'btxn_<hex>'
    merchant_id    text,
    currency       text,
    type           text,                               -- collection / payout / fee / fx / adjustment / payout_reversal
    amount         numeric(18,2),                       -- signed; + credit, - debit
    running_balance numeric(18,2),
    source_id      text,                               -- collection_id / payout_id / invoice_id
    description    text,
    created_at     bigint,                              -- epoch ms (ledger service)
    metadata       jsonb
);

-- ---------------------------------------------------------------------
-- fx_locks — locked FX quotes used to price payouts
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_rafiki.fx_locks (
    fx_lock_id    text PRIMARY KEY,                   -- 'fxl_<hex>'
    merchant_id   text,
    base_currency text,                                -- usually USD/USDC
    quote_currency text,                               -- local payout ccy
    rate          numeric(18,8),
    margin_bps    integer,
    amount_base   numeric(18,2),
    expires_at    timestamptz,
    consumed      boolean DEFAULT false,
    consumed_by   text,                                -- payout_id
    created_at    timestamptz
);

-- ---------------------------------------------------------------------
-- webhooks — merchant-configured webhook endpoints
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_rafiki.webhooks (
    webhook_id   text PRIMARY KEY,                    -- 'wh_<hex>'
    merchant_id  text,
    url          text,
    events       jsonb,                                -- subscribed event types
    secret_hash  text,                                 -- signing secret hash (PII-ish)
    is_active    boolean DEFAULT true,
    api_version  text,
    created_at   timestamptz,
    disabled_at  timestamptz
);

-- ---------------------------------------------------------------------
-- webhook_deliveries — individual delivery attempts (FACT-ish)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_rafiki.webhook_deliveries (
    delivery_id    text PRIMARY KEY,                  -- 'whd_<hex>'
    webhook_id     text,
    merchant_id    text,
    event_type     text,                               -- collection.confirmed / payout.paid / settlement.created ...
    event_id       text,
    response_status integer,                            -- HTTP status (nullable on timeout)
    attempt        integer,
    success        boolean,
    duration_ms    integer,
    delivered_at   bigint,                              -- epoch ms
    next_retry_at  bigint                               -- epoch ms, nullable
);
