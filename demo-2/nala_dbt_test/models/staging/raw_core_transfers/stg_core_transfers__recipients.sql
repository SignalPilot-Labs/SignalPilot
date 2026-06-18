-- Beneficiaries, 1:1 with raw_core_transfers.recipients.
with source as (
    select * from {{ source('raw_core_transfers', 'recipients') }}
)

select
    recipient_id,
    recipient_uuid,
    customer_id,
    first_name,
    last_name,
    full_name,
    receive_country,
    receive_currency,
    relationship,
    phone,
    nullif(lower(trim(email)), '')              as email,
    date_of_birth,
    coalesce(is_active, false)                  as is_active,
    coalesce(is_deleted, false)                 as is_deleted,
    created_at,
    updated_at
from source
