-- Cleaned Rafiki B2B payouts: one row per payout, with a coarse outcome grouping
-- and merchant context. PII (recipient_account) intentionally excluded.
with payouts as (
    select * from {{ ref('stg_rafiki__payouts') }}
),

merchants as (
    select * from {{ ref('stg_rafiki__merchants') }}
)

select
    p.payout_id,
    p.merchant_id,
    m.display_name                              as merchant_name,
    m.tier                                      as merchant_tier,
    p.recipient_type,
    p.rail,
    p.destination_country,
    p.local_currency,
    p.amount_local,
    p.amount_usd,
    p.fx_rate,
    p.fee_usd,
    p.partner,
    p.settlement_id,
    p.canonical_cid,
    p.status,
    -- coarse outcome grouping over the cleaned status enum
    case
        when p.status in ('completed', 'settled', 'paid') then 'succeeded'
        when p.status in ('failed', 'returned', 'cancelled') then 'failed'
        else 'in_progress'
    end                                         as outcome,
    p.failure_reason,
    p.created_at,
    p.completed_at
from payouts p
left join merchants m
    on p.merchant_id = m.merchant_id
