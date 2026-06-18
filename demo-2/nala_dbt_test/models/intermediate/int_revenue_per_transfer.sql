-- int_revenue_per_transfer: NALA earns two ways per transfer (per company profile):
--   1. transfer fee revenue (the non-waived fees charged on the transfer)
--   2. FX margin revenue (markup over mid-market rate, ~0.5-1.5%)
-- FX margin revenue is derived from the transfer's own fx_margin_bps applied to
-- the send_amount (this is the priced margin; it equals the fx_margin fee line).
-- Grain: one row per transfer_id.
with t as (
    select * from {{ ref('int_transfers_enriched') }}
)

select
    transfer_id,
    customer_id,
    corridor_id,
    send_country,
    send_currency,
    receive_country,
    receive_currency,
    currency_pair,
    send_amount,
    fx_margin_bps,
    status_clean,
    is_completed,
    created_at,
    completed_at,

    -- fee revenue (transfer + fx_margin fee lines, net of waivers/promo)
    transfer_fee_amount                                             as fee_revenue,
    fx_margin_fee_amount                                            as fx_margin_fee_revenue,

    -- modelled fx margin revenue = send_amount * margin bps (send currency)
    round(send_amount * fx_margin_bps / 10000.0, 4)                 as fx_margin_revenue_modelled,

    promo_discount_amount,

    -- total revenue per transfer = fee lines + modelled fx margin, less promo
    round(
        transfer_fee_amount
        + (send_amount * fx_margin_bps / 10000.0)
        - promo_discount_amount
    , 4)                                                            as total_revenue,
    send_currency                                                   as revenue_currency
from t
