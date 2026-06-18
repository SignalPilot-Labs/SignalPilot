with source as (
    select * from {{ source('raw_chainalysis', 'address_screenings') }}
)

select
    id                                          as screening_id,
    address                                     as wallet_address,
    upper(asset)                                as asset,
    lower(network)                              as network,
    nullif(trim(nala_customer_code), '')        as customer_code,
    upper(direction)                            as direction,
    -- normalize the Chainalysis rating to lowercase
    lower(risk)                                 as risk,
    risk_reason,
    cluster_name,
    cluster_category,
    coalesce(is_sanctioned, false)              as is_sanctioned,
    upper(status)                               as status,
    raw_response,
    -- both timestamps are ISO strings here -> clean timestamptz
    requested_at::timestamptz                   as requested_at,
    updated_at::timestamptz                     as updated_at
from source
