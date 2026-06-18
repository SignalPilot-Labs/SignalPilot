-- M-PESA C2B payment confirmations. Daraja CamelCase -> snake_case.
-- Coalesce the two time encodings (TransTime string yyyyMMddHHmmss,
-- ingested_at epoch ms) into clean timestamptz columns.
with source as (
    select * from {{ source('raw_mpesa', 'c2b_payments') }}
)

select
    "TransID"                                            as mpesa_receipt,
    "TransactionType"                                    as transaction_type,
    "TransAmount"                                        as amount,
    coalesce("currency", 'KES')                          as currency,
    "BusinessShortCode"                                  as business_short_code,
    "BillRefNumber"                                      as bill_ref_number,
    "InvoiceNumber"                                      as invoice_number,
    "ThirdPartyTransID"                                  as third_party_trans_id,
    "OrgAccountBalance"                                  as org_account_balance,
    "MSISDN"                                             as msisdn,                 -- PII
    "FirstName"                                          as first_name,             -- PII
    "MiddleName"                                         as middle_name,            -- PII
    "LastName"                                           as last_name,              -- PII
    "nala_transfer_id"                                   as nala_transfer_id,
    "nala_customer_code"                                 as nala_customer_code,
    -- TransTime is the Daraja yyyyMMddHHmmss string
    to_timestamp("TransTime", 'YYYYMMDDHH24MISS')        as transacted_at,
    -- ingested_at is epoch milliseconds
    to_timestamp("ingested_at" / 1000.0)                 as ingested_at,
    "raw_payload"                                        as raw_payload
from source
