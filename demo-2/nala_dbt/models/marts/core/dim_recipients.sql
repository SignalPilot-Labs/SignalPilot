-- dim_recipients: beneficiary dimension with PII flags.
-- Grain: one row per recipient_id.
with recipients as (
    select * from {{ ref('stg_core_transfers__recipients') }}
)

select
    recipient_id,
    recipient_uuid,
    customer_id,

    -- PII attributes
    first_name,
    last_name,
    coalesce(full_name, nullif(trim(coalesce(first_name,'') || ' ' || coalesce(last_name,'')), '')) as full_name,
    email,
    phone,
    date_of_birth,

    -- PII presence flags
    (email is not null)                                            as has_email,
    (phone is not null)                                            as has_phone,
    (date_of_birth is not null)                                    as has_date_of_birth,

    receive_country,
    receive_currency,
    relationship,
    is_active,
    is_deleted,
    created_at,
    updated_at
from recipients
