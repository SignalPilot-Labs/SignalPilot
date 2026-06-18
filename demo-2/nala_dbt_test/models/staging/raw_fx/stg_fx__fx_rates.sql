with source as (
    select * from {{ source('raw_fx', 'fx_rates') }}
)

select
    rate_id,
    base_currency,
    quote_currency,
    pair,
    mid_rate,
    bid_rate,
    ask_rate,
    spread_bps,
    provider_id,
    is_stale,
    -- three encodings of the same instant; coalesce into one clean tz-aware ts
    coalesce(
        ingested_at,
        to_timestamp(ts_epoch_ms / 1000.0)
    ) as observed_at
from source
