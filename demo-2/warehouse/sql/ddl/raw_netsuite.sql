-- =====================================================================
-- Domain 10 — NetSuite (raw_netsuite)
-- NALA's ERP / general ledger. Chart of accounts, GL transactions,
-- vendors and vendor bills (AP), across multiple legal subsidiaries
-- (UK, US, Kenya, Tanzania, Senegal ...).
--
-- Source system: Oracle NetSuite (SuiteAnalytics / SuiteTalk export).
-- Naming follows NetSuite's real style: internal integer ids, "tranid",
-- "trandate", "acctnumber", subsidiary/department as internalId lookups,
-- amounts in subsidiary base currency, free-text status enums.
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS raw_netsuite;

-- ---------------------------------------------------------------------
-- Lookups: subsidiaries & departments
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_netsuite.subsidiaries (
    subsidiary_id      bigint PRIMARY KEY,      -- NetSuite internalId
    name               text,                    -- "NALA UK Ltd"
    legal_name         text,
    country            text,                    -- ISO2
    base_currency      text,                    -- GBP / USD / KES / TZS / XOF
    is_elimination     boolean,                 -- consolidation elim subsidiary
    parent_id          bigint,                  -- parent subsidiary (sparse)
    fiscal_calendar    text,
    is_inactive        boolean
);

CREATE TABLE IF NOT EXISTS raw_netsuite.departments (
    department_id      bigint PRIMARY KEY,      -- NetSuite internalId
    name               text,                    -- Engineering / Compliance / Ops ...
    parent_id          bigint,                  -- sparse
    subsidiary_id      bigint,                  -- owning subsidiary (sparse)
    is_inactive        boolean
);

-- ---------------------------------------------------------------------
-- Chart of accounts
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_netsuite.gl_accounts (
    account_id         bigint PRIMARY KEY,      -- NetSuite internalId
    acctnumber         text,                    -- "1000", "4000" account number
    account_name       text,                    -- "Cash - Operating" etc
    account_type       text,                    -- Bank/AcctRec/AcctPay/Income/Expense/Equity
    account_category   text,                    -- asset/liability/equity/income/expense
    parent_id          bigint,                  -- sparse
    currency           text,                    -- account currency (sparse)
    is_summary         boolean,
    is_inactive        boolean,
    created_at         timestamptz
);

-- ---------------------------------------------------------------------
-- GL transactions — FACT (sized off N["transfers"]). One row per
-- transaction line posted to the ledger.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_netsuite.gl_transactions (
    transaction_line_id text PRIMARY KEY,       -- "<tranid>-<line>"
    transaction_id     bigint,                  -- NetSuite transaction internalId
    tranid             text,                    -- document number e.g. JE1023
    transaction_type   text,                    -- Journal/VendBill/Payment/Invoice/Deposit
    line_number        integer,
    account_id         bigint,                  -- -> gl_accounts.account_id
    subsidiary_id      bigint,                  -- -> subsidiaries.subsidiary_id
    department_id      bigint,                  -- -> departments.department_id (sparse)
    trandate           date,                    -- transaction (posting) date
    period_name        text,                    -- "Jun 2026" accounting period
    memo               text,                    -- free text (sparse)
    debit              numeric(18,2),           -- one of debit/credit set (in currency)
    credit             numeric(18,2),
    amount             numeric(18,2),           -- signed line amount (base currency)
    currency           text,                    -- transaction currency
    exchange_rate      numeric(18,8),           -- to subsidiary base currency
    posting            boolean,                 -- posted vs non-posting
    status             text,                    -- Open / Paid In Full / Pending Approval
    created_epoch_ms   bigint                   -- epoch ms drift
);

-- ---------------------------------------------------------------------
-- Vendors (AP master)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_netsuite.vendors (
    vendor_id          bigint PRIMARY KEY,      -- NetSuite internalId
    entityid           text,                    -- "V1023 Twilio Inc"
    company_name       text,                    -- "Twilio Inc"
    category           text,                    -- Infrastructure/Compliance/Marketing/Banking
    email              text,                    -- AP contact email (PII-ish)
    phone              text,                    -- (PII-ish, sparse)
    subsidiary_id      bigint,                  -- primary subsidiary
    currency           text,                    -- default bill currency
    tax_id             text,                    -- VAT/EIN (PII-ish, sparse)
    terms              text,                    -- Net 30 / Net 15
    is_1099_eligible   boolean,
    is_inactive        boolean,
    created_at         timestamptz
);

-- ---------------------------------------------------------------------
-- Vendor bills (AP transactions) — references vendors.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_netsuite.vendor_bills (
    bill_id            bigint PRIMARY KEY,      -- NetSuite internalId
    tranid             text,                    -- bill document number
    vendor_id          bigint,                  -- -> vendors.vendor_id
    subsidiary_id      bigint,                  -- -> subsidiaries.subsidiary_id
    department_id      bigint,                  -- -> departments (sparse)
    trandate           date,                    -- bill date
    duedate            date,                    -- due date
    period_name        text,
    currency           text,
    exchange_rate      numeric(18,8),
    amount             numeric(18,2),           -- gross bill amount (currency)
    tax_amount         numeric(18,2),
    amount_base        numeric(18,2),           -- in subsidiary base currency
    amount_paid        numeric(18,2),
    amount_remaining   numeric(18,2),
    status             text,                    -- Open / Paid In Full / Pending Approval / Cancelled
    approval_status    text,                    -- Approved / Pending / Rejected
    memo               text,
    created_at         timestamptz,
    updated_at         timestamptz
);
