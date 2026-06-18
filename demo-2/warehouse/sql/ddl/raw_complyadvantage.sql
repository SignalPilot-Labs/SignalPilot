-- ============================================================================
-- raw_complyadvantage — ComplyAdvantage AML / sanctions / PEP screening.
-- Mirrors ComplyAdvantage's API: a "search" screens a person against watchlists
-- and returns "hits"; a "monitor" keeps a search under ongoing surveillance and
-- raises "alerts" when matches change. Vendor API style: snake_case, integer
-- search ids, ISO timestamps, share_url tokens.
-- PII: searched person identity (name/dob/year) + matched watchlist entity data.
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS raw_complyadvantage;

-- One row per screening search. Each search screens one NALA customer.
CREATE TABLE IF NOT EXISTS raw_complyadvantage.searches (
    id                  bigint PRIMARY KEY,           -- ComplyAdvantage numeric search id
    ref                 text,                         -- client reference = NALA customer code (join key; sometimes blank)
    nala_customer_email text,                         -- dirtied email used to fire the search (alt join key, sparse)
    search_term         text,                         -- the name string searched (PII)
    client_ref          text,                         -- legacy duplicate of ref kept for back-compat
    searcher_id         text,                         -- internal analyst / service account id
    assignee_id         text,
    filters             jsonb,                        -- {types:[sanction,pep,adverse-media], birth_year, countries}
    match_status        text,                         -- no_match | potential_match | false_positive | true_positive | unknown
    risk_level          text,                         -- low | medium | high | unknown
    total_hits          integer,
    total_matches       integer,
    share_url           text,
    is_monitored        boolean,
    created_at          text,                         -- ISO-8601 string
    updated_at          text,
    tags                jsonb
);

-- One row per hit (a matched watchlist entity) inside a search. PII: matched-entity data.
CREATE TABLE IF NOT EXISTS raw_complyadvantage.search_hits (
    id                  bigserial PRIMARY KEY,        -- surrogate (vendor nests hits under search)
    search_id           bigint,                       -- -> searches.id
    doc_id              text,                         -- vendor entity document id
    entity_name         text,                         -- matched person/org name (PII of the matched entity)
    entity_type         text,                         -- person | organisation | vessel | aircraft
    match_types         jsonb,                        -- ["name_exact","aka_fuzzy",...]
    aka                 jsonb,                         -- also-known-as names blob
    sources             jsonb,                        -- ["OFAC SDN","UN Consolidated","UK HMT",...]
    types               jsonb,                        -- ["sanction","pep-class-1","adverse-media-financial-crime"]
    match_score         numeric(5,2),                 -- vendor score (0..100); sparse for legacy rows
    is_whitelisted      boolean,
    match_status        text,                         -- per-hit disposition: potential_match | false_positive | true_positive
    fields              jsonb,                        -- raw matched fields (dob, nationality, ...)
    created_at          text
);

-- One row per ongoing monitor registration on a search.
CREATE TABLE IF NOT EXISTS raw_complyadvantage.monitors (
    id                  bigint PRIMARY KEY,
    search_id           bigint,                       -- -> searches.id
    ref                 text,                         -- NALA customer code
    is_active           boolean,
    monitor_frequency   text,                         -- daily | weekly | monthly | legacy 'DAILY'
    last_run_at         text,                         -- ISO; null if never run
    created_at          text,
    updated_at          text
);

-- One row per alert raised by a monitor (a change in match state over time).
CREATE TABLE IF NOT EXISTS raw_complyadvantage.monitor_alerts (
    id                  bigint PRIMARY KEY,
    monitor_id          bigint,                       -- -> monitors.id
    search_id           bigint,                       -- denormalised -> searches.id
    alert_type          text,                         -- new_match | match_removed | risk_changed | data_updated
    previous_risk_level text,
    new_risk_level      text,
    status              text,                         -- open | acknowledged | closed | escalated; legacy 'OPEN'
    assigned_to         text,
    resolved_at_epoch_ms bigint,                      -- epoch MILLISECONDS (format drift); null while open
    payload             jsonb,                         -- full alert blob
    created_at          text                          -- ISO-8601 string
);
