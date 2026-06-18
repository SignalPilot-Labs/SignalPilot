-- ============================================================================
-- raw_chainalysis — Chainalysis crypto wallet risk screening.
-- NALA / Rafiki settle in stablecoins, so payout/deposit wallet addresses are
-- screened for exposure to sanctioned, darknet, scam and other risk categories.
-- Mirrors Chainalysis Address Screening / KYT API: an address_screening returns
-- a risk rating; alerts fire on high-risk; exposure breaks down counterparty
-- categories by direction.
-- Vendor API style: camelCase blobs in jsonb, ISO-8601 'updatedAt', USD amounts.
-- PII: crypto wallet addresses (pseudonymous but treated as PII).
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS raw_chainalysis;

-- One row per address screening request. address = the screened wallet (PII).
CREATE TABLE IF NOT EXISTS raw_chainalysis.address_screenings (
    id                  text PRIMARY KEY,             -- "scr_<uuid>"
    address             text,                         -- crypto wallet address (PII)
    asset               text,                         -- USDC | USDT | PYUSD | ETH | TRX | BTC
    network             text,                         -- ethereum | tron | bitcoin | polygon | base
    nala_customer_code  text,                         -- CUS_00000123 (join key; sparse — many addresses are counterparties)
    direction           text,                         -- DEPOSIT | WITHDRAWAL (relative to NALA)
    risk                text,                         -- Low | Medium | High | Severe (Chainalysis rating)
    risk_reason         text,                         -- free text reason
    cluster_name        text,                         -- attributed entity/cluster (e.g. "Binance","Lazarus Group")
    cluster_category    text,                         -- exchange | sanctioned entity | darknet market | scam | mixing | p2p
    is_sanctioned       boolean,
    status              text,                         -- COMPLETE | PENDING | ERROR
    requested_at        text,                         -- ISO-8601 string
    updated_at          text,                         -- vendor 'updatedAt'
    raw_response        jsonb                         -- full vendor payload
);

-- One row per alert raised off a high-risk screening.
CREATE TABLE IF NOT EXISTS raw_chainalysis.screening_alerts (
    id                  text PRIMARY KEY,             -- "alrt_<uuid>"
    screening_id        text,                         -- -> address_screenings.id
    address             text,                         -- denormalised wallet (PII)
    alert_level         text,                         -- High | Severe
    category            text,                         -- sanctions | darknet | scam | stolen funds | terrorist financing
    service             text,                         -- attributed service name
    exposure_type       text,                         -- DIRECT | INDIRECT
    exposure_usd        numeric(20,2),                -- USD value of exposure that triggered the alert
    alert_amount_usd    numeric(20,2),
    triggered_at_epoch_ms bigint,                     -- epoch MILLISECONDS (format drift)
    status              text,                         -- OPEN | IN_REVIEW | DISMISSED | CONFIRMED
    disposition         text,                         -- analyst disposition free text; sparse
    created_at          text
);

-- One row per (screening, counterparty-category, direction) exposure breakdown line.
CREATE TABLE IF NOT EXISTS raw_chainalysis.exposure (
    id                  bigserial PRIMARY KEY,        -- surrogate
    screening_id        text,                         -- -> address_screenings.id
    address             text,                         -- denormalised wallet (PII)
    direction           text,                         -- SENT | RECEIVED
    category            text,                         -- exchange | mining | gambling | sanctioned entity | darknet market | scam | defi | ...
    exposure_type       text,                         -- DIRECT | INDIRECT
    value_usd           numeric(20,2),                -- USD value exposed to this category
    percentage          numeric(7,4),                 -- share of total exposure (0..1); sparse
    cluster_name        text,
    created_at          text
);
