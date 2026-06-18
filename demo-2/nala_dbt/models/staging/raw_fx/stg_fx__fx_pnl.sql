with source as (
    select * from {{ source('raw_fx', 'fx_pnl') }}
)

select
    pnl_id,
    pnl_date,
    base_currency,
    quote_currency,
    base_currency || '/' || quote_currency as pair,
    volume_usd,
    realized_pnl_usd,
    unrealized_pnl_usd,
    realized_pnl_usd + unrealized_pnl_usd as total_pnl_usd,
    avg_margin_bps,
    notional_local,
    notional_ccy,
    created_at
from source
