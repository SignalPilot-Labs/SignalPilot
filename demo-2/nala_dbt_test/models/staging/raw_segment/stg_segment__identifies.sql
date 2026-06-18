-- stg_segment__identifies: cleaned identify calls, 1:1 with source.
-- Standardizes the dirty email (trim + lowercase) for identity resolution.
with source as (
    select * from {{ source('raw_segment', 'identifies') }}
)

select
    id                                         as identify_id,
    anonymous_id,
    nullif(trim(user_id), '')                  as customer_code,
    traits,
    lower(trim(email))                         as email,
    phone                                      as phone,
    context_ip                                 as ip_address,
    context_app_version                        as app_version,
    lower(context_device_type)                 as platform,
    coalesce(timestamp, received_at)           as identified_at,
    received_at,
    loaded_at
from source
