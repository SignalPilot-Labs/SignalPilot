with source as (
    select * from {{ source('raw_rafiki', 'balance_transactions') }}
)

select
    balance_txn_id,
    merchant_id,
    currency,
    lower(type)        as txn_type,
    amount             as amount,            -- signed: + credit, - debit
    running_balance,
    source_id,
    description,
    -- created_at is epoch milliseconds (ledger service)
    to_timestamp(created_at / 1000.0) as created_at,
    metadata
from source
