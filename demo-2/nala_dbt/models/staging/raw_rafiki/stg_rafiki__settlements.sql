with source as (
    select * from {{ source('raw_rafiki', 'settlements') }}
)

select
    settlement_id,
    merchant_id,
    settlement_date,
    currency               as settlement_currency,
    gross_collected_usd,
    gross_paid_out_usd,
    total_fees_usd,
    net_amount_usd,
    line_count,
    lower(status)          as status,
    statement_url,
    created_at             as created_at,
    settled_at             as settled_at
from source
