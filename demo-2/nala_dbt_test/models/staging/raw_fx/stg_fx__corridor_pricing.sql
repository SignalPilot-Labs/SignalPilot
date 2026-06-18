with source as (
    select * from {{ source('raw_fx', 'corridor_pricing') }}
)

select
    corridor_pricing_id,
    send_currency,
    send_country,
    receive_currency,
    receive_country,
    payout_method,
    fixed_fee_amount,
    fixed_fee_ccy,
    fx_margin_bps,
    promo_active,
    min_send_amount,
    max_send_amount,
    "isActive"            as is_active,   -- legacy camelCase -> snake_case
    effective_from,
    updated_at
from source
