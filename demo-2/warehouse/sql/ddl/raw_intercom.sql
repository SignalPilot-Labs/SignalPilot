-- =====================================================================
-- raw_intercom — Intercom (in-app messaging / conversational support)
-- Source system: Intercom API v2.11. snake_case columns, ids are numeric
-- strings. Timestamps are UNIX epoch SECONDS (Intercom convention) — drift
-- vs Zendesk ISO strings. contacts referenced by email (dirty) -> NALA cust.
-- NO cross-schema FK constraints. PKs within a table only.
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS raw_intercom;

-- ---------------------------------------------------------------------
-- conversations — Intercom conversations (chat threads)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_intercom.conversations (
    id                  text PRIMARY KEY,            -- numeric string id
    contact_external_id text,                         -- NALA customer code 'CUS_...'
    contact_email       text,                         -- PII, dirty (maps to NALA customer)
    state               text,                         -- open / closed / snoozed
    open                boolean,
    read                boolean,
    priority            text,                         -- priority / not_priority
    source_type         text,                         -- conversation / email / push / chat
    source_subject      text,
    assignee_admin_id   text,                         -- agent id (nullable)
    team_assignee_id    text,                         -- nullable
    waiting_since       bigint,                       -- epoch ms (Intercom uses ms here), nullable
    snoozed_until       bigint,                       -- epoch s, nullable
    sla_breached        boolean,
    rating              integer,                      -- conversation_rating 1..5, sparse
    tags                jsonb,
    statistics          jsonb,                        -- {first_response_time, time_to_close, ...} blob
    created_at          bigint,                       -- epoch s
    updated_at          bigint                        -- epoch s
);

-- ---------------------------------------------------------------------
-- conversation_parts — individual messages/notes within a conversation
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_intercom.conversation_parts (
    id              text PRIMARY KEY,                 -- numeric string id
    conversation_id text,
    part_type       text,                             -- comment / note / assignment / close / open
    body            text,                             -- HTML/text body, nullable for system parts
    author_type     text,                             -- user / admin / bot
    author_id       text,
    notified_at     bigint,                           -- epoch s, nullable
    created_at      bigint                            -- epoch s
);
