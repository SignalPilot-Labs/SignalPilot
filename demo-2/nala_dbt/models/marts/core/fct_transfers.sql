-- fct_transfers: the clean transfer fact. One row per transfer, combining the
-- enriched transfer, its revenue, funding leg and payout leg, plus foreign keys
-- to the customer / recipient / corridor dimensions.
-- Grain: one row per transfer_id.
with enriched as (
    select * from {{ ref('int_transfers_enriched') }}
),

revenue as (
    select
        transfer_id,
        fee_revenue,
        fx_margin_fee_revenue,
        fx_margin_revenue_modelled,
        total_revenue,
        revenue_currency
    from {{ ref('int_revenue_per_transfer') }}
),

funding as (
    select
        transfer_id,
        funding_source,
        funding_reference,
        funding_amount,
        funding_currency,
        funding_status
    from {{ ref('int_transfers_funding') }}
),

payout as (
    select
        transfer_id,
        payout_attempt_id,
        payout_partner,
        payout_rail,
        payout_status,
        partner_reference,
        external_rail_source,
        external_reference,
        payout_completed_at
    from {{ ref('int_transfers_payout') }}
)

select
    e.transfer_id,
    e.reference,

    -- dimension foreign keys
    e.customer_id,
    e.recipient_id,
    e.corridor_id,
    e.quote_id,

    -- corridor attributes
    e.send_country,
    e.send_currency,
    e.receive_country,
    e.receive_currency,
    e.currency_pair,

    -- amounts & fx
    e.send_amount,
    e.receive_amount,
    e.fx_rate,
    e.mid_market_rate,
    e.fx_margin_bps,

    -- fees
    e.fee_total,
    e.transfer_fee_amount,
    e.fx_margin_fee_amount,
    e.promo_discount_amount,

    -- revenue
    coalesce(r.fee_revenue, 0)                          as fee_revenue,
    coalesce(r.fx_margin_revenue_modelled, 0)           as fx_margin_revenue,
    coalesce(r.total_revenue, 0)                        as total_revenue,
    r.revenue_currency,

    -- status
    e.status,
    e.status_clean,
    e.is_completed,
    e.is_first_transfer,

    -- funding leg
    f.funding_source,
    f.funding_reference,
    f.funding_amount,
    f.funding_currency,
    f.funding_status,
    e.funding_method,
    e.funding_partner,

    -- payout leg
    p.payout_attempt_id,
    coalesce(p.payout_partner, e.payout_partner)        as payout_partner,
    coalesce(p.payout_rail, e.rail)                     as payout_rail,
    p.payout_status,
    p.partner_reference,
    p.external_rail_source,
    p.external_reference,

    -- timestamps
    e.created_at,
    e.funded_at,
    e.completed_at,
    p.payout_completed_at,
    e.created_at::date                                  as created_date
from enriched e
left join revenue r on e.transfer_id = r.transfer_id
left join funding f on e.transfer_id = f.transfer_id::uuid
left join payout  p on e.transfer_id = p.transfer_id
