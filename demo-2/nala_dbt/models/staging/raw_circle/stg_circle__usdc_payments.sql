-- Circle fiat funding payments, 1:1 with source. Parses ISO-Z string timestamps,
-- standardizes status, and keeps governed card PII (last4 + BIN only).
with source as (
    select * from {{ source('raw_circle', 'usdc_payments') }}
)

select
    id                                            as payment_id,
    lower(type)                                   as payment_type,
    nullif(trim(merchant_wallet_id), '')          as merchant_wallet_id,
    nullif(trim(customer_ref), '')                as customer_code,
    amount,
    upper(currency)                               as currency,
    lower(source_type)                            as source_type,
    card_last4,
    card_bin,
    upper(card_network)                           as card_network,
    lower(status)                                 as status,
    risk_score,
    fees                                          as fee_amount,
    description,
    cast(create_date as timestamptz)              as created_at,
    cast(update_date as timestamptz)              as updated_at
from source
