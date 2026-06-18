-- Per-merchant Rafiki activity aggregate: collections, payouts and balance.
with collections as (
    select * from {{ ref('stg_rafiki__collections') }}
),

payouts as (
    select * from {{ ref('stg_rafiki__payouts') }}
),

balance_txns as (
    select * from {{ ref('stg_rafiki__balance_transactions') }}
),

collection_agg as (
    select
        merchant_id,
        count(*)                                as collection_count,
        sum(amount_usd)                         as collected_usd,
        sum(fee_usd)                            as collection_fees_usd,
        max(received_at)                        as last_collection_at
    from collections
    group by merchant_id
),

payout_agg as (
    select
        merchant_id,
        count(*)                                as payout_count,
        sum(amount_usd)                         as paid_out_usd,
        sum(fee_usd)                            as payout_fees_usd,
        max(created_at)                         as last_payout_at
    from payouts
    group by merchant_id
),

balance_agg as (
    select
        merchant_id,
        count(*)                                as balance_txn_count,
        sum(amount)                             as net_balance_movement
    from balance_txns
    group by merchant_id
),

merchant_ids as (
    select merchant_id from collection_agg
    union
    select merchant_id from payout_agg
    union
    select merchant_id from balance_agg
)

select
    m.merchant_id,
    coalesce(c.collection_count, 0)             as collection_count,
    coalesce(c.collected_usd, 0)                as collected_usd,
    coalesce(c.collection_fees_usd, 0)          as collection_fees_usd,
    coalesce(p.payout_count, 0)                 as payout_count,
    coalesce(p.paid_out_usd, 0)                 as paid_out_usd,
    coalesce(p.payout_fees_usd, 0)              as payout_fees_usd,
    coalesce(b.balance_txn_count, 0)            as balance_txn_count,
    coalesce(b.net_balance_movement, 0)         as net_balance_movement,
    coalesce(c.collected_usd, 0) - coalesce(p.paid_out_usd, 0) as net_flow_usd,
    greatest(
        coalesce(c.last_collection_at, '1970-01-01'::timestamptz),
        coalesce(p.last_payout_at, '1970-01-01'::timestamptz)
    )                                           as last_activity_at
from merchant_ids m
left join collection_agg c on m.merchant_id = c.merchant_id
left join payout_agg p on m.merchant_id = p.merchant_id
left join balance_agg b on m.merchant_id = b.merchant_id
