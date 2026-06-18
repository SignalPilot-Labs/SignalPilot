-- raw_ledger — NALA internal double-entry general ledger + treasury wallets.
-- Source system: internal core ledger service (Postgres-backed). Names are
-- internal snake_case with a few legacy/deprecated columns kept around.
CREATE SCHEMA IF NOT EXISTS raw_ledger;

-- Lookup: chart-of-accounts account types (asset/liability/equity/revenue/expense).
CREATE TABLE IF NOT EXISTS raw_ledger.account_types (
    account_type_id   integer PRIMARY KEY,
    code              text NOT NULL,          -- ASSET / LIABILITY / EQUITY / REVENUE / EXPENSE
    name              text NOT NULL,
    normal_balance    text NOT NULL,          -- DEBIT / CREDIT
    description        text
);

-- Chart of accounts. Some accounts belong to a customer wallet (customer_code).
CREATE TABLE IF NOT EXISTS raw_ledger.accounts (
    account_id        bigint PRIMARY KEY,
    account_code      text NOT NULL,          -- e.g. 1000-CASH-USD, 2000-CUST-LIAB
    account_name      text NOT NULL,
    account_type_id   integer,                -- -> account_types.account_type_id
    currency          text NOT NULL,
    parent_account_id bigint,                 -- self-reference, nullable
    customer_code     text,                   -- CUS_00000123 when this is a customer wallet account
    is_contra         boolean DEFAULT false,
    is_active         boolean DEFAULT true,
    is_deleted        boolean DEFAULT false,  -- soft delete
    deleted_at        timestamptz,
    created_at        timestamptz NOT NULL,
    updated_at        timestamptz,
    metadata          jsonb
);

-- Journal entries (header). One per posted accounting event. Double-entry: the
-- sum of debit lines equals the sum of credit lines for each entry.
CREATE TABLE IF NOT EXISTS raw_ledger.journal_entries (
    entry_id          bigint PRIMARY KEY,
    entry_uuid        text NOT NULL,
    entry_date        date NOT NULL,
    posted_at         timestamptz NOT NULL,   -- internal ISO timestamptz
    currency          text NOT NULL,
    source_system     text,                   -- transfers / rafiki / treasury / fees / manual
    reference_type    text,                   -- transfer / settlement / fee / fx / adjustment
    reference_id      text,                   -- a transfer uuid, settlement id, etc (dirty join key)
    description       text,
    status            text NOT NULL,          -- POSTED / DRAFT / REVERSED (+ legacy 'posted')
    is_reversal       boolean DEFAULT false,
    reverses_entry_id bigint,
    created_by        text,
    metadata          jsonb,
    legacy_batch_id   text                    -- deprecated, mostly null
);

-- Journal lines (FACT, N["ledger_lines"]). Each line debits or credits one account.
CREATE TABLE IF NOT EXISTS raw_ledger.journal_lines (
    line_id           bigint PRIMARY KEY,
    entry_id          bigint NOT NULL,        -- -> journal_entries.entry_id
    line_no           integer NOT NULL,       -- 1..n within the entry
    account_id        bigint NOT NULL,        -- -> accounts.account_id
    direction         text NOT NULL,          -- DEBIT / CREDIT
    amount            numeric(20,4) NOT NULL, -- always positive; direction carries sign
    currency          text NOT NULL,
    debit             numeric(20,4),          -- denormalized convenience cols (one is null)
    credit            numeric(20,4),
    memo              text,
    posted_at         timestamptz NOT NULL
);

-- Treasury / customer wallets (internal balance wallets, fiat + stablecoin).
CREATE TABLE IF NOT EXISTS raw_ledger.wallets (
    wallet_id         bigint PRIMARY KEY,
    wallet_uuid       text NOT NULL,
    customer_code     text,                   -- CUS_... when a customer wallet; null for treasury
    wallet_type       text NOT NULL,          -- CUSTOMER / TREASURY / FEE / SUSPENSE
    currency          text NOT NULL,          -- fiat or stablecoin
    ledger_account_id bigint,                 -- -> accounts.account_id
    address           text,                   -- crypto address for stablecoin wallets (PII), null for fiat
    chain             text,                   -- ethereum / polygon / solana / null for fiat
    status            text NOT NULL,          -- ACTIVE / FROZEN / CLOSED
    opened_at         timestamptz NOT NULL,
    closed_at         timestamptz,
    metadata          jsonb
);

-- Wallet transactions (credits/debits hitting a wallet balance).
CREATE TABLE IF NOT EXISTS raw_ledger.wallet_transactions (
    wallet_txn_id     bigint PRIMARY KEY,
    wallet_id         bigint NOT NULL,        -- -> wallets.wallet_id
    entry_id          bigint,                 -- -> journal_entries.entry_id (nullable, some legacy txns unlinked)
    txn_type          text NOT NULL,          -- CREDIT / DEBIT
    amount            numeric(20,4) NOT NULL,
    currency          text NOT NULL,
    balance_after     numeric(20,4),          -- running balance, sometimes null on old rows
    reference_id      text,                   -- transfer uuid / settlement id
    description       text,
    occurred_at       timestamptz NOT NULL,
    created           timestamptz             -- legacy duplicate of occurred_at, often null
);

-- Daily-ish balance snapshots per account (denormalized for reporting).
CREATE TABLE IF NOT EXISTS raw_ledger.balance_snapshots (
    snapshot_id       bigint PRIMARY KEY,
    account_id        bigint NOT NULL,        -- -> accounts.account_id
    snapshot_date     date NOT NULL,
    currency          text NOT NULL,
    debit_total       numeric(20,4) NOT NULL,
    credit_total      numeric(20,4) NOT NULL,
    balance           numeric(20,4) NOT NULL, -- signed per normal balance
    created_at        timestamptz NOT NULL
);

-- Reconciliation runs (ledger vs external custodian/bank balances).
CREATE TABLE IF NOT EXISTS raw_ledger.reconciliation_runs (
    run_id            bigint PRIMARY KEY,
    run_uuid          text NOT NULL,
    recon_type        text NOT NULL,          -- FIREBLOCKS / CIRCLE / BANK / INTERNAL
    as_of_date        date NOT NULL,
    started_at        timestamptz NOT NULL,
    completed_at      timestamptz,
    status            text NOT NULL,          -- COMPLETED / RUNNING / FAILED
    total_breaks      integer DEFAULT 0,
    total_break_amount numeric(20,4) DEFAULT 0,
    run_by            text,
    metadata          jsonb
);

-- Reconciliation breaks (discrepancies found in a run).
CREATE TABLE IF NOT EXISTS raw_ledger.reconciliation_breaks (
    break_id          bigint PRIMARY KEY,
    run_id            bigint NOT NULL,        -- -> reconciliation_runs.run_id
    account_id        bigint,                 -- -> accounts.account_id (nullable)
    currency          text NOT NULL,
    ledger_balance    numeric(20,4),
    external_balance  numeric(20,4),
    break_amount      numeric(20,4) NOT NULL, -- ledger - external
    break_type        text NOT NULL,          -- TIMING / MISSING_TXN / FX / UNKNOWN
    status            text NOT NULL,          -- OPEN / INVESTIGATING / RESOLVED
    resolved_at       timestamptz,
    notes             text
);
