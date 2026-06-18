-- int_customer_lifetime: per-customer transfer activity aggregate.
-- Grain: one row per customer_id that has at least one transfer.
with transfers as (
    select * from {{ ref('int_transfers_enriched') }}
),

revenue as (
    select transfer_id, total_revenue, revenue_currency
    from {{ ref('int_revenue_per_transfer') }}
)

select
    t.customer_id,
    count(*)                                                       as transfer_count,
    count(*) filter (where t.is_completed)                         as completed_transfer_count,
    min(t.created_at)                                              as first_transfer_at,
    max(t.created_at)                                              as last_transfer_at,
    sum(t.send_amount)                                             as total_send_amount,
    sum(t.send_amount) filter (where t.is_completed)               as total_completed_send_amount,
    sum(t.receive_amount) filter (where t.is_completed)            as total_completed_receive_amount,
    sum(t.fee_total)                                               as total_fees_charged,
    sum(r.total_revenue)                                           as total_revenue,
    count(distinct t.send_currency)                               as distinct_send_currencies,
    count(distinct t.receive_country)                            as distinct_receive_countries,
    count(distinct t.corridor_id)                                as distinct_corridors,
    max(t.send_currency)                                          as primary_send_currency
from transfers t
left join revenue r on t.transfer_id = r.transfer_id
group by t.customer_id
