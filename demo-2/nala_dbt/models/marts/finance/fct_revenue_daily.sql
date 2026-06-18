-- fct_revenue_daily: daily transfer revenue rolled up by corridor + currency.
-- Built from int_revenue_per_transfer (one row per transfer). Only completed
-- transfers contribute realized revenue; all transfers contribute volume.
-- Grain: one row per (revenue_date, corridor_id, send_currency, receive_currency).
with revenue as (
    select
        r.transfer_id,
        r.corridor_id,
        r.send_currency,
        r.receive_currency,
        r.currency_pair,
        r.send_amount,
        r.is_completed,
        r.fee_revenue,
        r.fx_margin_revenue_modelled,
        r.total_revenue,
        r.created_at::date                              as revenue_date
    from {{ ref('int_revenue_per_transfer') }} r
)

select
    revenue_date,
    corridor_id,
    send_currency,
    receive_currency,
    currency_pair,

    count(*)                                            as transfer_count,
    count(*) filter (where is_completed)                as completed_transfer_count,

    sum(send_amount)                                    as gross_send_amount,
    sum(send_amount) filter (where is_completed)        as completed_send_amount,

    sum(fee_revenue)                                    as fee_revenue,
    sum(fx_margin_revenue_modelled)                     as fx_margin_revenue,
    sum(total_revenue)                                  as total_revenue,
    sum(total_revenue) filter (where is_completed)      as completed_revenue
from revenue
group by 1, 2, 3, 4, 5
