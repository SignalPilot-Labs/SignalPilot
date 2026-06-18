-- Flutterwave settlement batches. Standardize status and surface the fee
-- breakdown. settled_at is NULL while pending.
with source as (
    select * from {{ source('raw_flutterwave', 'settlements') }}
)

select
    id                                                   as settlement_id,
    settlement_reference,
    currency,
    gross_amount,
    app_fee,
    merchant_fee,
    chargeback_amount,
    net_amount,
    transfer_count,
    lower(status)                                        as settlement_status,
    due_date,
    settled_at,
    raw_payload
from source
