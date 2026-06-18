-- ============================================================================
-- raw_onfido — Onfido identity-verification (KYC) vendor data.
-- Mirrors Onfido's real API object model: applicants -> checks -> reports,
-- plus documents and the specialised report types (facial_similarity, watchlist).
-- Vendor API style: snake_case fields, ISO-8601 *_at timestamps as text, UUID-ish
-- string ids prefixed by object type ("applicant_...", "chk_...", "rep_...").
-- PII: HEAVY — names, dob, address, document numbers. Governed design: document
-- numbers stored as last4 + sha256 hash, never the full number.
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS raw_onfido;

-- One row per Onfido applicant. Maps 1:1 to a NALA customer (see external_id).
CREATE TABLE IF NOT EXISTS raw_onfido.applicants (
    id                  text PRIMARY KEY,            -- "applicant_<uuid>"
    external_id         text,                        -- NALA customer code CUS_00000123 (the join key; sometimes null)
    nala_customer_uuid  text,                        -- canonical customer uuid (added in a later API version; sparse)
    first_name          text,
    last_name           text,
    email               text,                        -- dirtied: casing/space drift vs core
    dob                 date,                         -- date of birth (PII)
    -- address (PII), split out the Onfido way
    address_line1       text,
    address_town        text,
    address_postcode    text,
    address_country     text,                         -- ISO-2
    phone_number        text,                         -- dirtied E.164 (PII)
    id_numbers          jsonb,                        -- vendor blob: [{type, value_last4}]
    created_at          text,                         -- ISO-8601 string, e.g. 2024-03-01T10:11:12.000Z
    href                text,                         -- vendor self-link
    sandbox             boolean,                      -- test applicant flag
    is_deleted          boolean DEFAULT false,        -- soft delete
    deleted_at          text
);

-- One row per check (a check groups one or more reports). Onfido "check" object.
CREATE TABLE IF NOT EXISTS raw_onfido.checks (
    id                  text PRIMARY KEY,             -- "chk_<uuid>"
    applicant_id        text,                         -- -> applicants.id (not FK-enforced)
    status              text,                         -- in_progress | complete | withdrawn | paused | reopened
    result              text,                         -- clear | consider | NULL (still running); legacy 'PASS'/'FAIL' for old rows
    tags                jsonb,                        -- vendor array of free-text tags
    report_ids          jsonb,                        -- array of report ids contained in this check
    redirect_uri        text,
    applicant_provides_data boolean,
    created_at          text,                         -- ISO-8601 string
    completed_at_epoch  bigint,                       -- epoch SECONDS (drift: completion stored as epoch, not ISO)
    href                text,
    webhook_ids         jsonb
);

-- One row per report (the unit Onfido actually adjudicates).
CREATE TABLE IF NOT EXISTS raw_onfido.reports (
    id                  text PRIMARY KEY,             -- "rep_<uuid>"
    check_id            text,                         -- -> checks.id
    applicant_id        text,                         -- denormalised back-ref
    name                text,                         -- document | facial_similarity_photo | watchlist_standard | identity_enhanced ...
    status              text,                         -- awaiting_data | awaiting_approval | complete | withdrawn | cancelled
    result              text,                         -- clear | consider | unidentified | NULL
    sub_result          text,                         -- (document reports) clear | rejected | suspected | caution
    breakdown           jsonb,                        -- vendor nested breakdown blob
    properties          jsonb,                        -- extracted properties blob (e.g. parsed doc fields)
    documents           jsonb,                        -- array of document ids referenced
    created_at          text,
    completed_at        text,                         -- ISO; NULL while running
    href                text
);

-- One row per uploaded identity document. PII: document numbers governed (last4+hash).
CREATE TABLE IF NOT EXISTS raw_onfido.documents (
    id                      text PRIMARY KEY,         -- "doc_<uuid>"
    applicant_id            text,                     -- -> applicants.id
    type                    text,                     -- passport | driving_licence | national_identity_card | residence_permit
    side                    text,                     -- front | back | NULL
    issuing_country         text,                     -- ISO-3 the Onfido way (e.g. GBR, KEN)
    document_number_last4   text,                     -- governed: only last 4 retained (PII-min)
    document_number_hash    text,                     -- sha256 of full number (governed)
    first_name              text,                     -- as printed on the doc (PII)
    last_name               text,
    dob                     date,                     -- as printed on the doc (PII)
    expiry_date             date,
    file_name               text,
    file_type               text,
    file_size               integer,
    download_href           text,
    created_at              text
);

-- One row per facial-similarity (selfie vs document) report.
CREATE TABLE IF NOT EXISTS raw_onfido.facial_similarity_reports (
    id                  text PRIMARY KEY,             -- "rep_<uuid>"
    check_id            text,
    applicant_id        text,
    variant             text,                         -- standard | video | motion
    result              text,                         -- clear | consider
    sub_result          text,                         -- clear | rejected | suspected | caution
    score               numeric(5,4),                 -- 0..1 face match score (sparse)
    face_comparison     jsonb,                         -- breakdown blob
    image_integrity     jsonb,
    visual_authenticity jsonb,
    created_at          text,
    completed_at        text
);

-- One row per watchlist (PEP/sanctions/adverse-media) screening report run inside Onfido.
CREATE TABLE IF NOT EXISTS raw_onfido.watchlist_reports (
    id                  text PRIMARY KEY,             -- "rep_<uuid>"
    check_id            text,
    applicant_id        text,
    variant             text,                         -- standard | enhanced | peps_only | sanctions_only
    result              text,                         -- clear | consider
    n_matches           integer,                      -- number of records matched
    records             jsonb,                        -- array of match record blobs (name, sources, match_types)
    sources_searched    jsonb,                        -- array of list names searched
    shared_with_third_parties boolean,
    created_at          text,
    completed_at        text
);
