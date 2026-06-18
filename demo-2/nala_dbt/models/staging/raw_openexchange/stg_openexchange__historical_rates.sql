with source as (
    select * from {{ source('raw_openexchange', 'historical_rates') }}
)

select
    id as historical_rate_id,
    rate_date,
    base            as base_currency,
    currency        as quote_currency,
    rate            as usd_rate,          -- units of quote_currency per 1 USD
    -- "timestamp" is epoch seconds of that day's close
    to_timestamp("timestamp") as close_at,
    ingested_at
from source
