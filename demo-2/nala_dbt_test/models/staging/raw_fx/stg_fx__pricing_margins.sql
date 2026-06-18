with source as (
    select * from {{ source('raw_fx', 'pricing_margins') }}
)

select
    margin_id,
    send_currency,
    receive_currency,
    lower(customer_segment) as customer_segment,
    margin_bps,
    min_margin_bps,
    max_margin_bps,
    effective_from,
    effective_to,
    coalesce(is_deleted, false) as is_deleted,
    (effective_to is null and not coalesce(is_deleted, false)) as is_current,
    deleted_at,
    updated_at
from source
