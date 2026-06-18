-- dim_corridors: send->receive corridor lookup with pricing.
-- corridor_id (from core transfers) maps 1:1 to a send/receive country+currency
-- tuple. We attach corridor_pricing (finer-grained by payout method) aggregated
-- to the corridor level. Grain: one row per corridor_id.
with corridors as (
    select distinct
        corridor_id,
        send_country,
        send_currency,
        receive_country,
        receive_currency,
        send_currency || '->' || receive_currency      as currency_pair
    from {{ ref('int_transfers_enriched') }}
    where corridor_id is not null
),

pricing as (
    -- aggregate the per-payout-method pricing rows up to the corridor tuple.
    -- send_country can be dirty/null in pricing, so match on the currency +
    -- receive_country which are reliably populated.
    select
        send_currency,
        receive_currency,
        receive_country,
        count(*)                                        as pricing_row_count,
        count(*) filter (where is_active)               as active_pricing_rows,
        bool_or(promo_active)                           as any_promo_active,
        avg(fx_margin_bps)                              as avg_fx_margin_bps,
        min(fx_margin_bps)                              as min_fx_margin_bps,
        max(fx_margin_bps)                              as max_fx_margin_bps,
        min(fixed_fee_amount)                           as min_fixed_fee_amount,
        max(fixed_fee_amount)                           as max_fixed_fee_amount
    from {{ ref('stg_fx__corridor_pricing') }}
    group by 1, 2, 3
)

select
    c.corridor_id,
    c.send_country,
    c.send_currency,
    c.receive_country,
    c.receive_currency,
    c.currency_pair,

    coalesce(p.pricing_row_count, 0)                    as pricing_row_count,
    coalesce(p.active_pricing_rows, 0)                  as active_pricing_rows,
    coalesce(p.any_promo_active, false)                 as any_promo_active,
    p.avg_fx_margin_bps,
    p.min_fx_margin_bps,
    p.max_fx_margin_bps,
    p.min_fixed_fee_amount,
    p.max_fixed_fee_amount,
    (p.send_currency is not null)                       as has_pricing
from corridors c
left join pricing p
    on c.send_currency    = p.send_currency
   and c.receive_currency = p.receive_currency
   and c.receive_country  = p.receive_country
