-- Fireblocks custody movements, 1:1 with source. Casts decimal-string amounts
-- to numeric, converts epoch-ms timestamps to timestamptz, lowercases the
-- camelCase columns, and standardizes status to lowercase.
with source as (
    select * from {{ source('raw_fireblocks', 'vault_transactions') }}
)

select
    id                                            as vault_txn_id,
    "assetId"                                     as asset_id,
    "sourceId"                                    as source_vault_id,
    "destinationId"                               as destination_vault_id,
    "sourceAddress"                               as source_address,
    "destAddress"                                 as dest_address,
    cast(amount as numeric(20,6))                 as amount,
    "amountUSD"                                   as amount_usd,
    cast("netAmount" as numeric(20,6))            as net_amount,
    cast(fee as numeric(20,6))                    as fee,
    "feeCurrency"                                 as fee_currency,
    "txHash"                                      as tx_hash,
    lower("operation")                            as operation,
    lower(status)                                 as status,
    "subStatus"                                   as sub_status,
    to_timestamp("createdAt" / 1000.0)            as created_at,
    to_timestamp("lastUpdated" / 1000.0)          as last_updated_at,
    nullif(trim("customerRefId"), '')             as customer_code,
    nullif(trim("referenceId"), '')               as reference_id
from source
