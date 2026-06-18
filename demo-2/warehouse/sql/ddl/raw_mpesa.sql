-- =====================================================================
-- raw_mpesa — Safaricom M-PESA Daraja API landing tables
-- Source-system fidelity: authentic Daraja CamelCase field naming
-- (TransactionID, MSISDN, TransAmount, BusinessShortCode, ResultCode).
-- These represent the mobile-money payout (B2C) and collection (C2B/STK)
-- legs for NALA transfers into Kenya / Tanzania.
-- PII: MSISDN (customer mobile-money number). No cross-schema FKs.
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS raw_mpesa;

-- ---------------------------------------------------------------------
-- STK Push (Lipa na M-PESA Online) — collection initiation requests.
-- Daraja /mpesa/stkpush/v1/processrequest. Async: response carries
-- CheckoutRequestID; the final result lands via callbacks.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_mpesa.stk_push_requests (
    "MerchantRequestID"     text PRIMARY KEY,
    "CheckoutRequestID"     text,
    "BusinessShortCode"     text,
    "TransactionType"       text,            -- CustomerPayBillOnline / CustomerBuyGoodsOnline
    "Amount"                numeric(18,2),
    "PartyA"                text,            -- payer MSISDN (PII)
    "PartyB"                text,            -- shortcode
    "PhoneNumber"           text,            -- MSISDN (PII), drifting format
    "AccountReference"      text,            -- our transfer ref
    "TransactionDesc"       text,
    "ResponseCode"          text,            -- "0" = accepted for processing
    "ResponseDescription"   text,
    "CustomerMessage"       text,
    "ResultCode"            integer,         -- final result once callback lands; null until then
    "ResultDesc"            text,
    "MpesaReceiptNumber"    text,            -- populated on success
    "nala_transfer_id"      uuid,            -- soft ref to core transfers
    "nala_customer_code"    text,            -- soft ref CUS_########
    "TransactionDate"       text,            -- Daraja format yyyyMMddHHmmss (string!)
    "created_at"            timestamptz,     -- our ingest time
    "raw_payload"           jsonb            -- full vendor request/response blob
);

-- ---------------------------------------------------------------------
-- C2B payments — customer-to-business confirmations (Paybill / Till).
-- Daraja C2B confirmation/validation. Used for funding & collections.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_mpesa.c2b_payments (
    "TransID"               text PRIMARY KEY,    -- M-PESA receipt e.g. RKTQDM7W6S
    "TransactionType"       text,                -- "Pay Bill" / "Buy Goods"
    "TransTime"             text,                -- yyyyMMddHHmmss string
    "TransAmount"           numeric(18,2),
    "BusinessShortCode"     text,
    "BillRefNumber"         text,                -- our transfer/account ref
    "InvoiceNumber"         text,
    "OrgAccountBalance"     numeric(18,2),       -- shortcode balance after txn
    "ThirdPartyTransID"     text,
    "MSISDN"                text,                -- payer number (PII), sometimes hashed/masked by Daraja
    "FirstName"             text,                -- PII
    "MiddleName"            text,                -- PII
    "LastName"              text,                -- PII (often null)
    "nala_transfer_id"      uuid,
    "nala_customer_code"    text,
    "currency"              text DEFAULT 'KES',
    "ingested_at"           bigint,              -- epoch ms ingest time
    "raw_payload"           jsonb
);

-- ---------------------------------------------------------------------
-- B2C requests — business-to-customer disbursements (the payout leg).
-- Daraja /mpesa/b2c/v1/paymentrequest. This is how NALA credits a
-- recipient's M-PESA wallet in KE/TZ.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_mpesa.b2c_requests (
    "OriginatorConversationID" text PRIMARY KEY,
    "ConversationID"        text,
    "TransactionID"         text,                -- M-PESA receipt, populated on success
    "InitiatorName"         text,
    "CommandID"             text,                -- BusinessPayment / SalaryPayment / PromotionPayment
    "Amount"                numeric(18,2),
    "PartyA"                text,                -- our shortcode
    "PartyB"                text,                -- recipient MSISDN (PII)
    "Remarks"               text,
    "Occasion"              text,
    "QueueTimeOutURL"       text,
    "ResultURL"             text,
    "ResponseCode"          text,                -- "0" accepted
    "ResponseDescription"   text,
    "ResultCode"            integer,             -- final, from callback; null until resolved
    "ResultDesc"            text,
    "TransactionReceipt"    text,
    "TransactionAmount"     numeric(18,2),
    "B2CRecipientIsRegisteredCustomer" text,     -- "Y"/"N"
    "B2CChargesPaidAccountAvailableFunds" numeric(18,2),
    "ReceiverPartyPublicName" text,              -- masked name+MSISDN e.g. 2547****1234 - JOHN D. (PII)
    "B2CUtilityAccountAvailableFunds" numeric(18,2),
    "B2CWorkingAccountAvailableFunds" numeric(18,2),
    "TransactionCompletedDateTime" text,         -- "dd.MM.yyyy HH:mm:ss" (different format!)
    "nala_transfer_id"      uuid,
    "nala_customer_code"    text,
    "currency"              text DEFAULT 'KES',
    "created"               timestamptz,         -- our ingest time
    "raw_payload"           jsonb
);

-- ---------------------------------------------------------------------
-- Callbacks — raw async result notifications Daraja POSTs to our
-- ResultURL / CallBackURL (for STK, B2C, status, balance). Polymorphic.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_mpesa.callbacks (
    "callback_id"           bigint PRIMARY KEY,
    "callback_type"         text,                -- stk / b2c / status / balance
    "ConversationID"        text,
    "OriginatorConversationID" text,
    "CheckoutRequestID"     text,                -- for STK callbacks
    "MerchantRequestID"     text,
    "ResultType"            integer,
    "ResultCode"            integer,             -- 0 success, else failure
    "ResultDesc"            text,
    "TransactionID"         text,
    "received_at_ms"        bigint,              -- epoch ms
    "is_duplicate"          boolean DEFAULT false, -- Daraja sometimes double-posts
    "ResultParameters"      jsonb,               -- the {"ResultParameter":[{Key,Value}...]} blob
    "raw_payload"           jsonb
);

-- ---------------------------------------------------------------------
-- Transaction status queries — Daraja /mpesa/transactionstatus/v1/query.
-- Used to reconcile payouts whose callback never arrived.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_mpesa.transaction_status_queries (
    "OriginatorConversationID" text PRIMARY KEY,
    "ConversationID"        text,
    "TransactionID"         text,                -- the txn being queried
    "PartyA"                text,                -- shortcode
    "IdentifierType"        text,                -- "4" = shortcode
    "ResultCode"            integer,
    "ResultDesc"            text,
    "DebitPartyName"        text,                -- masked (PII)
    "CreditPartyName"       text,                -- masked (PII)
    "TransactionStatus"     text,                -- "Completed" / "Failed" / legacy "PENDING_OLD"
    "ReasonType"            text,
    "FinalisedTime"         text,                -- yyyyMMddHHmmss string
    "Amount"                numeric(18,2),
    "queried_at"            timestamptz,
    "raw_payload"           jsonb
);

-- ---------------------------------------------------------------------
-- Account balance queries — Daraja /mpesa/accountbalance/v1/query.
-- Periodic treasury polls of our M-PESA shortcode float.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_mpesa.account_balance_queries (
    "OriginatorConversationID" text PRIMARY KEY,
    "ConversationID"        text,
    "BusinessShortCode"     text,
    "ResultCode"            integer,
    "ResultDesc"            text,
    "WorkingAccountBalance" numeric(18,2),
    "UtilityAccountBalance" numeric(18,2),
    "ChargesPaidAccountBalance" numeric(18,2),
    "BalanceCurrency"       text,                -- "KES"
    "BOCompletedTime"       text,                -- yyyyMMddHHmmss string
    "queried_at"            timestamptz,
    "raw_payload"           jsonb
);

-- ---------------------------------------------------------------------
-- Statements — daily reconciliation statement lines pulled from the
-- M-PESA portal / Daraja. One row per ledger line on the shortcode.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_mpesa.statements (
    "statement_line_id"     bigint PRIMARY KEY,
    "BusinessShortCode"     text,
    "ReceiptNo"             text,                -- M-PESA receipt
    "CompletionTime"        text,                -- "yyyy-MM-dd HH:mm:ss" (yet another format)
    "InitiationTime"        text,
    "TransactionType"       text,                -- "Pay Bill" / "Business Payment to Customer" / ...
    "Paidin"                numeric(18,2),       -- credit (note Daraja's odd capitalisation)
    "Withdrawn"             numeric(18,2),       -- debit
    "Balance"               numeric(18,2),
    "BalanceConfirmed"      boolean,
    "ReasonType"            text,
    "OtherPartyInfo"        text,                -- masked counterparty (PII)
    "LinkedTransactionID"   text,
    "AccountNo"             text,
    "statement_date"        date,
    "currency"              text DEFAULT 'KES',
    "is_deleted"            boolean DEFAULT false,
    "raw_payload"           jsonb
);
