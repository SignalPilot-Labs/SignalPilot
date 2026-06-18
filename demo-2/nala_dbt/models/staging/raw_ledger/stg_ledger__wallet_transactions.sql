-- Wallet movement log, 1:1 with source. Coalesces the messy occurred_at /
-- legacy `created` timestamps into one clean occurred_at and standardizes type.
with source as (
    select * from {{ source('raw_ledger', 'wallet_transactions') }}
)

select
    wallet_txn_id,
    wallet_id,
    entry_id,
    upper(txn_type)                               as txn_type,
    amount,
    case when upper(txn_type) = 'CREDIT'
         then amount else -amount end             as signed_amount,
    upper(currency)                               as currency,
    balance_after,
    nullif(trim(reference_id), '')                as reference_id,
    description,
    coalesce(occurred_at, created)                as occurred_at
from source
