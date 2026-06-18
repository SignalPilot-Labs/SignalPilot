-- Sender accounts, 1:1 with raw_core_transfers.customers.
-- Cleans dirty email (trim + lowercase), standardizes account_status.
with source as (
    select * from {{ source('raw_core_transfers', 'customers') }}
)

select
    customer_id,
    customer_uuid,
    customer_code,
    first_name,
    last_name,
    -- email is dirty: casing + leading/trailing spaces
    nullif(lower(trim(email)), '')                       as email,
    phone,
    date_of_birth,
    country                                              as send_country,
    currency                                             as default_currency,
    national_id,
    national_id_hash,
    kyc_tier,
    lower(account_status)                                as account_status,
    signup_platform,
    signup_country,
    marketing_opt_in,
    coalesce(is_deleted, false)                          as is_deleted,
    raw_attributes,
    deleted_at,
    created_at,
    updated_at
from source
