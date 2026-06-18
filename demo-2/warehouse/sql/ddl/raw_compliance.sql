-- ============================================================================
-- raw_compliance — NALA INTERNAL compliance operations system.
-- The internal source of record for the compliance/MLRO team: suspicious
-- activity reports (SARs) filed to regulators, the case-management queue that
-- tracks investigations, periodic customer risk scores, and the sanctions list
-- lookup the team maintains.
-- Internal naming style: snake_case, created_at timestamptz (this is OUR system,
-- so timestamps are clean tz-aware), bigint surrogate ids, free-text status with
-- a couple of legacy values.
-- PII: HEAVY — national_id governed as national_id + national_id_hash, subject
-- names, narrative free text.
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS raw_compliance;

-- One row per Suspicious Activity Report filed (or drafted) to a regulator/FIU.
CREATE TABLE IF NOT EXISTS raw_compliance.sars (
    sar_id              bigint PRIMARY KEY,
    sar_ref             text,                         -- human ref e.g. SAR-2025-000123
    customer_code       text,                         -- CUS_00000123 (join key)
    customer_uuid       uuid,                         -- canonical customer uuid (alt join key)
    subject_name        text,                         -- subject of the report (PII)
    subject_national_id text,                         -- governed: kept for filing, treated as PII
    subject_national_id_hash text,                    -- sha256 of national id (governed lookup key)
    transfer_id         uuid,                         -- the transfer that triggered it (-> raw_core_transfers.transfers.transfer_id); sparse
    activity_type       text,                         -- structuring | rapid_movement | sanctions_hit | third_party | fraud | mule_account
    status              text,                         -- draft | filed | acknowledged | closed_no_action; legacy 'SUBMITTED'
    priority            text,                         -- low | medium | high | critical
    regulator           text,                         -- FCA | FINTRAC | FinCEN | CBN | BoU
    filing_reference    text,                         -- regulator's reference once acknowledged; null until filed
    narrative           text,                         -- free-text investigator narrative (PII)
    amount_usd          numeric(20,2),                -- aggregate suspicious amount
    filed_by            text,                         -- MLRO / analyst id
    filed_at            timestamptz,                  -- null while draft
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz
);

-- One row per compliance case (an investigation; may or may not become a SAR).
CREATE TABLE IF NOT EXISTS raw_compliance.case_management (
    case_id             bigint PRIMARY KEY,
    case_ref            text,                         -- CASE-2025-000123
    customer_code       text,                         -- CUS_00000123 (join key)
    case_type           text,                         -- kyc_review | aml_alert | sanctions_review | fraud | edd | transaction_monitoring
    source              text,                         -- which system raised it: onfido | complyadvantage | chainalysis | rules_engine | manual
    source_ref          text,                         -- id in the source system (e.g. ComplyAdvantage search id, Onfido check id)
    status              text,                         -- open | in_progress | pending_info | escalated | closed; legacy 'NEW'
    priority            text,                         -- low | medium | high | critical
    assigned_to         text,                         -- analyst id; null if unassigned
    queue               text,                         -- l1_triage | l2_investigation | mlro
    risk_rating         text,                         -- low | medium | high
    resolution          text,                         -- cleared | sar_filed | account_closed | false_positive | escalated; null while open
    sla_due_at          timestamptz,
    opened_at           timestamptz NOT NULL,
    closed_at           timestamptz,                  -- null while open
    sla_breached        boolean,
    notes               jsonb,                         -- array of timestamped note blobs
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- One row per customer risk score snapshot (re-scored periodically + on events).
CREATE TABLE IF NOT EXISTS raw_compliance.risk_scores (
    id                  bigint PRIMARY KEY,
    customer_code       text,                         -- CUS_00000123 (join key)
    customer_uuid       uuid,
    score               integer,                      -- 0..100 composite risk score
    risk_band           text,                         -- low | medium | high | prohibited
    model_version       text,                         -- e.g. crs-v2.3
    factors             jsonb,                         -- {geography, pep, adverse_media, velocity, ...} contribution blob
    pep_flag            boolean,
    sanctions_flag      boolean,
    adverse_media_flag  boolean,
    high_risk_country   boolean,
    is_current          boolean,                      -- latest score for the customer? (SCD-ish; messy — sometimes >1 current)
    scored_at           timestamptz NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- Lookup: the consolidated sanctions list the team screens against.
CREATE TABLE IF NOT EXISTS raw_compliance.sanctions_list (
    entry_id            bigint PRIMARY KEY,
    list_name           text,                         -- OFAC SDN | UN Consolidated | UK HMT | EU Consolidated
    entity_name         text,                         -- sanctioned entity (PII of the listed entity)
    entity_type         text,                         -- individual | entity | vessel | aircraft
    aliases             jsonb,                         -- array of aka names
    program             text,                         -- sanctions program code
    nationality         text,                         -- ISO-2; sparse
    dob                 date,                          -- for individuals; sparse
    listed_on           date,
    is_active           boolean,
    source_url          text,
    created_at          timestamptz NOT NULL DEFAULT now()
);
