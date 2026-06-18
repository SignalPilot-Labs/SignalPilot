-- =====================================================================
-- raw_flutterwave — Flutterwave payout-partner landing tables.
-- Flutterwave is one of NALA's pan-African payout rails (see PARTNERS
-- ["payout_rail"]). These are the bank / mobile-money payout legs across
-- multiple African receive markets.
-- Field naming follows Flutterwave's v3 Transfers API (snake_case JSON
-- with a "data" envelope) — deliberately DIFFERENT from M-PESA's
-- CamelCase, to mimic cross-vendor naming drift.
-- PII: account_number, beneficiary bank details, recipient phone (MSISDN).
-- No cross-schema FKs.
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS raw_flutterwave;

-- ---------------------------------------------------------------------
-- banks — lookup of supported destination banks (Flutterwave /banks/:country).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_flutterwave.banks (
    id                      integer PRIMARY KEY,    -- Flutterwave bank id
    code                    text,                   -- e.g. "044"
    name                    text,
    country                 text,                   -- ISO2 receive country
    currency                text,
    is_mobile_money         boolean DEFAULT false,
    created_at              timestamptz
);

-- ---------------------------------------------------------------------
-- beneficiaries — saved payout destinations (bank acct / mobile money).
-- Flutterwave /beneficiaries. Heavy PII (account number + holder name).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_flutterwave.beneficiaries (
    id                      bigint PRIMARY KEY,
    account_number          text,                   -- PII (bank acct or MSISDN for momo)
    account_bank            text,                   -- bank code
    bank_name               text,
    full_name               text,                   -- PII
    beneficiary_name        text,                   -- PII (sometimes differs / dirty dup)
    email                   text,                   -- PII (may be null/dirty)
    mobilenumber            text,                   -- PII MSISDN, drifting format
    currency                text,
    country                 text,
    nala_customer_code      text,                   -- soft ref CUS_########
    nala_recipient_uuid     uuid,
    is_deleted              boolean DEFAULT false,
    meta                    jsonb,
    created_at              text                    -- ISO-Z string
);

-- ---------------------------------------------------------------------
-- transfers — the payout fact. Flutterwave /transfers. One row per
-- attempted payout to a beneficiary (sized off N["transfers"]).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_flutterwave.transfers (
    id                      bigint PRIMARY KEY,     -- Flutterwave transfer id
    reference               text,                   -- our idempotency reference
    account_number          text,                   -- PII destination acct/MSISDN
    bank_code               text,
    bank_name               text,
    fullname                text,                   -- PII beneficiary name (FW spelling: fullname)
    amount                  numeric(18,2),
    fee                     numeric(18,2),
    currency                text,                   -- receive currency (KES/NGN/GHS/...)
    narration               text,
    status                  text,                   -- NEW / PENDING / SUCCESSFUL / FAILED (+legacy "QUEUED")
    complete_message         text,
    requires_approval       integer,                -- 0/1
    is_approved             integer,                -- 0/1
    bank_reference          text,                   -- destination bank/momo reference, null until settled
    meta                    jsonb,
    beneficiary_id          bigint,                 -- ref beneficiaries.id (same-schema, not enforced)
    nala_transfer_id        uuid,                   -- soft ref to core transfers
    nala_customer_code      text,
    recipient_phone         text,                   -- PII MSISDN
    debit_currency          text DEFAULT 'USD',
    created_at              text,                   -- ISO-Z string (FW returns this)
    date_created            timestamptz,            -- our ingest copy (redundant, slightly drifted)
    raw_payload             jsonb
);

-- ---------------------------------------------------------------------
-- transfer_retries — Flutterwave retries failed payouts; each attempt
-- logged here (one row per retry attempt of a transfer).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_flutterwave.transfer_retries (
    id                      bigint PRIMARY KEY,
    transfer_id             bigint,                 -- ref transfers.id (not enforced)
    attempt_number          integer,
    status                  text,                   -- SUCCESSFUL / FAILED / PENDING
    reference               text,
    response_code           text,
    response_message        text,
    retried_at              timestamptz,
    raw_payload             jsonb
);

-- ---------------------------------------------------------------------
-- balances — Flutterwave wallet/float balances per currency (treasury).
-- /balances. Periodic snapshots.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_flutterwave.balances (
    balance_id              bigint PRIMARY KEY,
    currency                text,
    available_balance       numeric(18,2),
    ledger_balance          numeric(18,2),
    snapshot_at             bigint,                 -- epoch s
    raw_payload             jsonb
);

-- ---------------------------------------------------------------------
-- webhooks — raw Flutterwave webhook events (transfer.completed, etc.).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_flutterwave.webhooks (
    webhook_id              bigint PRIMARY KEY,
    event                   text,                   -- "transfer.completed" / "charge.completed"
    event_type              text,                   -- "Transfer" / "Card"
    transfer_id             bigint,                 -- ref transfers.id when applicable
    reference               text,
    status                  text,
    verif_hash_valid        boolean,                -- did the verif-hash header validate
    received_at             text,                   -- ISO string, naive (no tz) — drift
    is_duplicate            boolean DEFAULT false,
    payload                 jsonb
);

-- ---------------------------------------------------------------------
-- settlements — Flutterwave settlement batches paid out to NALA's
-- collection account (aggregates many transfers).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_flutterwave.settlements (
    id                      bigint PRIMARY KEY,
    settlement_reference    text,
    currency                text,
    gross_amount            numeric(18,2),
    app_fee                 numeric(18,2),
    merchant_fee            numeric(18,2),
    chargeback_amount       numeric(18,2),
    net_amount              numeric(18,2),
    transfer_count          integer,
    status                  text,                   -- "completed" / "pending"
    due_date                date,
    settled_at              timestamptz,
    raw_payload             jsonb
);
