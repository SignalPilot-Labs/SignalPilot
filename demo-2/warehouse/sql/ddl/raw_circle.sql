-- raw_circle — Circle API style (snake-ish JSON: id is a uuid, amounts as
-- {amount, currency} where amount is a decimal STRING, createDate ISO-Z text).
-- NALA uses Circle for USDC wallets, transfers, and card/ACH payments.
CREATE SCHEMA IF NOT EXISTS raw_circle;

-- USDC wallets held with Circle (custodial + on-chain blockchain wallets).
CREATE TABLE IF NOT EXISTS raw_circle.usdc_wallets (
    wallet_id         text PRIMARY KEY,       -- circle walletId (numeric-as-string)
    type              text NOT NULL,          -- merchant / end_user_wallet
    description       text,
    customer_ref      text,                   -- CUS_... dirty join key, often null
    balance_usdc      numeric(20,6),          -- current USDC balance
    chain             text,                   -- ETH / MATIC / SOL / ALGO
    address           text,                   -- on-chain deposit address (PII), null for hosted
    address_tag       text,
    create_date       text NOT NULL,          -- ISO-Z string
    update_date       text,
    raw_payload       jsonb
);

-- USDC on-chain / inter-wallet transfers.
CREATE TABLE IF NOT EXISTS raw_circle.usdc_transfers (
    id                text PRIMARY KEY,       -- circle transfer uuid
    source_wallet_id  text,                   -- -> usdc_wallets.wallet_id (null if external blockchain source)
    source_type       text NOT NULL,          -- wallet / blockchain
    dest_type         text NOT NULL,          -- wallet / blockchain
    dest_address      text,                   -- on-chain destination address (PII)
    dest_chain        text,                   -- ETH / MATIC / SOL
    amount            text NOT NULL,          -- decimal string, USDC
    currency          text NOT NULL DEFAULT 'USD',
    tx_hash           text,                   -- on-chain hash (PII-ish), null while pending
    status            text NOT NULL,          -- complete / pending / failed
    error_code        text,                   -- set when failed
    reference_id      text,                   -- internal: transfer uuid / settlement id
    create_date       text NOT NULL,          -- ISO-Z string
    update_date       text,
    raw_payload       jsonb
);

-- Card / ACH payments collected via Circle (fiat -> USDC funding).
CREATE TABLE IF NOT EXISTS raw_circle.usdc_payments (
    id                text PRIMARY KEY,       -- circle payment uuid
    type              text NOT NULL,          -- payment / refund
    merchant_wallet_id text,                  -- -> usdc_wallets.wallet_id
    customer_ref      text,                   -- CUS_... dirty join key
    amount            numeric(20,2) NOT NULL, -- payments expose amount as number here
    currency          text NOT NULL,          -- USD / EUR / GBP
    source_type       text,                   -- card / ach / wire / blockchain
    card_last4        text,                   -- PII (last 4 only)
    card_bin          text,                   -- PII (first 6, BIN)
    card_network      text,                   -- VISA / MASTERCARD
    status            text NOT NULL,          -- paid / pending / confirmed / failed / refunded
    risk_score        integer,                -- Circle fraud score 0-100, sometimes null
    fees              numeric(20,2),
    description       text,
    create_date       text NOT NULL,          -- ISO-Z string
    update_date       text,
    raw_payload       jsonb
);

-- Chargebacks / disputes raised against card payments.
CREATE TABLE IF NOT EXISTS raw_circle.chargebacks (
    id                text PRIMARY KEY,       -- circle chargeback uuid
    payment_id        text NOT NULL,          -- -> usdc_payments.id
    merchant_wallet_id text,
    amount            numeric(20,2) NOT NULL,
    currency          text NOT NULL,
    category          text NOT NULL,          -- Fraudulent / Authorization / Processing Error / Consumer Dispute
    status            text NOT NULL,          -- pending / under_review / won / lost
    reason_code       text,                   -- card network reason code, e.g. 10.4, 13.1
    create_date       text NOT NULL,          -- ISO-Z string
    resolved_date     text,
    raw_payload       jsonb
);
