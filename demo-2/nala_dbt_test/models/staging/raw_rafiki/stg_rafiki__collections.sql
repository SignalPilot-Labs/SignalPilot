with source as (
    select * from {{ source('raw_rafiki', 'collections') }}
)

select
    collection_id,
    merchant_id,
    reference,
    upper(stablecoin)        as stablecoin,
    lower(chain)             as chain,
    amount_crypto,
    amount_usd,
    fee_usd,
    from_wallet,             -- PII: payer wallet
    to_wallet,
    tx_hash,
    confirmations,
    -- standardize status: legacy 'CONFIRMED_OLD' -> 'confirmed'
    case
        when lower(status) in ('confirmed', 'confirmed_old') then 'confirmed'
        else lower(status)
    end                      as status,
    rate_card_id,
    settlement_id,
    -- received_at is an ISO-Z string
    received_at::timestamptz as received_at,
    -- confirmed_at is epoch milliseconds
    to_timestamp(confirmed_at / 1000.0) as confirmed_at,
    metadata
from source
