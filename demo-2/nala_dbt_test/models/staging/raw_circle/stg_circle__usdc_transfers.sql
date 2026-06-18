-- Circle USDC transfers, 1:1 with source. Casts the decimal-string amount to
-- numeric, parses the ISO-Z string timestamps to timestamptz, standardizes
-- status, and trims the dirty reference_id join key.
with source as (
    select * from {{ source('raw_circle', 'usdc_transfers') }}
)

select
    id                                            as transfer_id,
    nullif(trim(source_wallet_id), '')            as source_wallet_id,
    lower(source_type)                            as source_type,
    lower(dest_type)                              as dest_type,
    dest_address,
    dest_chain,
    cast(amount as numeric(20,6))                 as amount,
    upper(currency)                               as currency,
    tx_hash,
    lower(status)                                 as status,
    error_code,
    nullif(trim(reference_id), '')                as reference_id,
    cast(create_date as timestamptz)              as created_at,
    cast(update_date as timestamptz)              as updated_at
from source
