-- Flutterwave payout transfers. Coalesce the drifting time columns
-- (created_at ISO-Z string vs date_created timestamptz) into one clean
-- created_at, and standardize the status enum (legacy QUEUED -> pending).
with source as (
    select * from {{ source('raw_flutterwave', 'transfers') }}
)

select
    id                                                   as transfer_id,
    reference,
    account_number,                                      -- PII (bank acct or MSISDN)
    bank_code,
    bank_name,
    fullname                                             as beneficiary_name,   -- PII
    amount,
    fee,
    currency,
    debit_currency,
    narration,
    case
        when upper(status) = 'SUCCESSFUL' then 'success'
        when upper(status) = 'FAILED' then 'failed'
        when upper(status) in ('PENDING', 'NEW', 'QUEUED') then 'pending'
        else lower(status)
    end                                                  as transfer_status,
    status                                               as transfer_status_raw,
    complete_message,
    (requires_approval = 1)                              as requires_approval,
    (is_approved = 1)                                    as is_approved,
    bank_reference,
    beneficiary_id,
    nala_transfer_id,
    nala_customer_code,
    recipient_phone,                                     -- PII
    -- created_at is ISO-Z; coalesce onto the ingest copy if missing
    coalesce(created_at::timestamptz, date_created)      as created_at,
    raw_payload
from source
