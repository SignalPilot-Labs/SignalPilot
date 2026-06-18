-- Fee breakdown per transfer, 1:1 with raw_core_transfers.transfer_fees.
with source as (
    select * from {{ source('raw_core_transfers', 'transfer_fees') }}
)

select
    fee_id,
    transfer_id,
    lower(fee_type)                     as fee_type,
    amount                              as fee_amount,
    currency                            as fee_currency,
    coalesce(is_waived, false)          as is_waived,
    description,
    created_at
from source
