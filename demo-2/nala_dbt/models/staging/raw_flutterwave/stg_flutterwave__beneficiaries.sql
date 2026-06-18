-- Flutterwave saved payout destinations. Clean the ISO-Z created_at string,
-- normalize the dirty email/phone, and expose the name-resolution mismatch
-- between full_name and the dirty beneficiary_name near-dup.
with source as (
    select * from {{ source('raw_flutterwave', 'beneficiaries') }}
)

select
    id                                                   as beneficiary_id,
    account_number,                                      -- PII
    account_bank                                         as bank_code,
    bank_name,
    full_name,                                           -- PII (clean name)
    beneficiary_name,                                    -- PII (dirty near-dup)
    -- normalize email: trim, lowercase (source has casing/space drift)
    nullif(lower(trim(email)), '')                       as email,                  -- PII
    mobilenumber                                         as msisdn,                 -- PII
    currency,
    country,
    nala_customer_code,
    nala_recipient_uuid,
    is_deleted,
    meta,
    created_at::timestamptz                              as created_at
from source
