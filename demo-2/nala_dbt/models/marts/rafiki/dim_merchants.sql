-- Rafiki merchant dimension: one row per merchant, with lifetime activity rollups.
with merchants as (
    select * from {{ ref('stg_rafiki__merchants') }}
),

activity as (
    select * from {{ ref('int_rafiki_merchant_activity') }}
)

select
    m.merchant_id,
    m.legal_name,
    m.display_name,
    m.website,
    m.hq_country,
    m.settlement_currency,
    m.accepted_stablecoins,
    m.industry,
    m.tier,
    m.status,
    m.mrr_usd,
    m.account_manager,
    m.is_test,
    m.is_deleted,
    -- lifetime activity rollups
    coalesce(a.collection_count, 0)             as collection_count,
    coalesce(a.collected_usd, 0)                as collected_usd,
    coalesce(a.payout_count, 0)                 as payout_count,
    coalesce(a.paid_out_usd, 0)                 as paid_out_usd,
    coalesce(a.net_flow_usd, 0)                 as net_flow_usd,
    a.last_activity_at,
    m.created_at,
    m.updated_at
from merchants m
left join activity a
    on m.merchant_id = a.merchant_id
