-- Price quotes, 1:1 with raw_core_transfers.quotes.
-- `converted` flags whether the quote became a transfer (transfer_id then set).
with source as (
    select * from {{ source('raw_core_transfers', 'quotes') }}
)

select
    quote_id,
    customer_id,
    transfer_id,
    send_currency,
    receive_currency,
    send_amount,
    receive_amount,
    fee_amount,
    fx_rate,
    rail,
    coalesce(converted, false)          as is_converted,
    created_at,
    expires_at
from source
