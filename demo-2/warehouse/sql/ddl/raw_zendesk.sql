-- =====================================================================
-- raw_zendesk — Zendesk Support (customer support tickets)
-- Source system: Zendesk Support API v2. snake_case columns, ids are bigint.
-- Timestamps are ISO-8601 with 'Z'. requester maps to a NALA customer via
-- email (dirty). users table holds support contacts (PII: email/phone/name).
-- NO cross-schema FK constraints. PKs within a table only.
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS raw_zendesk;

-- ---------------------------------------------------------------------
-- users — Zendesk users (end-users + agents). PII: name/email/phone.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_zendesk.users (
    id              bigint PRIMARY KEY,
    name            text,                            -- PII
    email           text,                            -- PII, dirty (maps to NALA customer)
    phone           text,                            -- PII, dirty E.164, sparse
    role            text,                            -- end-user / agent / admin
    external_id     text,                            -- NALA customer code 'CUS_...' for end-users
    organization_id bigint,                          -- nullable
    locale          text,                            -- en-GB / en-US / fr / sw
    time_zone       text,
    verified        boolean,
    suspended       boolean DEFAULT false,
    tags            jsonb,
    created_at      timestamptz,
    updated_at      timestamptz
);

-- ---------------------------------------------------------------------
-- tickets — support tickets (the primary support fact)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_zendesk.tickets (
    id              bigint PRIMARY KEY,
    requester_id    bigint,                          -- -> users.id (end-user)
    assignee_id     bigint,                          -- -> users.id (agent), nullable
    subject         text,
    status          text,                            -- new / open / pending / hold / solved / closed
    priority        text,                            -- low / normal / high / urgent (sparse)
    type            text,                            -- question / incident / problem / task (sparse)
    channel         text,                            -- email / chat / api / web / mobile
    tags            jsonb,
    group_name      text,                            -- support team queue
    requester_email text,                            -- PII, dirty — denormalized snapshot (maps to NALA customer)
    transfer_id     text,                            -- UUID of the transfer the ticket is about (sparse)
    satisfaction    text,                            -- offered / good / bad / unoffered (legacy free-text)
    is_public       boolean DEFAULT true,
    created_at      timestamptz,                     -- ISO-Z
    updated_at      timestamptz,
    solved_at       text,                            -- ISO-Z string, null until solved (legacy naming)
    metadata        jsonb
);

-- ---------------------------------------------------------------------
-- ticket_comments — public replies + private notes on a ticket
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_zendesk.ticket_comments (
    id          bigint PRIMARY KEY,
    ticket_id   bigint,
    author_id   bigint,                              -- -> users.id
    body        text,                                -- free text (may contain PII in real life)
    public      boolean,
    is_agent    boolean,
    created_at  timestamptz
);

-- ---------------------------------------------------------------------
-- satisfaction_ratings — CSAT survey responses on solved tickets
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_zendesk.satisfaction_ratings (
    id          bigint PRIMARY KEY,
    ticket_id   bigint,
    assignee_id bigint,
    requester_id bigint,
    score       text,                                -- good / bad / offered / unoffered
    comment     text,                                -- free-text feedback, sparse
    created_at  timestamptz,
    updated_at  timestamptz
);
