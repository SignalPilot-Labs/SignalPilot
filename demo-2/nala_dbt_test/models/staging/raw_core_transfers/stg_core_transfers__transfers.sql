-- Central transfers FACT, 1:1 with raw_core_transfers.transfers.
-- Standardizes the status enum (folds legacy PENDING_OLD -> PENDING).
with source as (
    select * from {{ source('raw_core_transfers', 'transfers') }}
)

select
    transfer_id,
    reference,
    customer_id,
    recipient_id,
    corridor_id,
    cancellation_reason_id,
    quote_id,
    send_country,
    send_currency,
    receive_country,
    receive_currency,
    send_amount,
    receive_amount,
    fee_amount,
    fee_currency,
    fx_rate,
    mid_market_rate,
    fx_margin_bps,
    -- standardize status: legacy PENDING_OLD -> PENDING
    case
        when upper(status) = 'PENDING_OLD' then 'PENDING'
        else upper(status)
    end                                                  as status,
    rail,
    payout_partner,
    funding_method,
    funding_partner,
    promo_code,
    coalesce(is_first_transfer, false)                   as is_first_transfer,
    source_ip,
    raw_payload,
    created_at,
    funded_at,
    completed_at,
    updated_at
from source
