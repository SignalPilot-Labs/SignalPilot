-- int_transfers_enriched: one row per transfer, with a cleaned status,
-- aggregated fee breakdown, and the fx margin figures attached.
-- Grain: one row per transfer_id (1:1 with stg_core_transfers__transfers).
with transfers as (
    select * from {{ ref('stg_core_transfers__transfers') }}
),

fees as (
    select
        transfer_id,
        sum(case when not is_waived then fee_amount else 0 end)                          as fee_total,
        sum(case when fee_type = 'transfer'       and not is_waived then fee_amount else 0 end) as transfer_fee_amount,
        sum(case when fee_type = 'fx_margin'      and not is_waived then fee_amount else 0 end) as fx_margin_fee_amount,
        sum(case when fee_type = 'promo_discount' then fee_amount else 0 end)             as promo_discount_amount,
        max(fee_currency)                                                                as fee_currency
    from {{ ref('stg_core_transfers__transfer_fees') }}
    group by 1
)

select
    t.transfer_id,
    t.reference,
    t.customer_id,
    t.recipient_id,
    t.corridor_id,
    t.quote_id,
    t.cancellation_reason_id,

    -- corridor descriptors
    t.send_country,
    t.send_currency,
    t.receive_country,
    t.receive_currency,
    t.send_currency || '->' || t.receive_currency                       as currency_pair,

    -- amounts
    t.send_amount,
    t.receive_amount,
    t.fee_amount,
    t.fee_currency,
    t.fx_rate,
    t.mid_market_rate,
    t.fx_margin_bps,

    -- aggregated fee breakdown (from transfer_fees)
    coalesce(f.fee_total, t.fee_amount)                                 as fee_total,
    coalesce(f.transfer_fee_amount, 0)                                  as transfer_fee_amount,
    coalesce(f.fx_margin_fee_amount, 0)                                 as fx_margin_fee_amount,
    coalesce(f.promo_discount_amount, 0)                                as promo_discount_amount,

    -- cleaned status: collapse the enum into a coarse state for reporting
    t.status,
    case
        when t.status = 'COMPLETED' then 'completed'
        when t.status = 'PENDING'   then 'pending'
        when t.status = 'FAILED'    then 'failed'
        when t.status = 'CANCELLED' then 'cancelled'
        when t.status = 'REFUNDED'  then 'refunded'
        else lower(t.status)
    end                                                                 as status_clean,
    (t.status = 'COMPLETED')                                            as is_completed,

    t.rail,
    t.payout_partner,
    t.funding_method,
    t.funding_partner,
    t.promo_code,
    t.is_first_transfer,

    t.created_at,
    t.funded_at,
    t.completed_at,
    t.updated_at
from transfers t
left join fees f on t.transfer_id = f.transfer_id
