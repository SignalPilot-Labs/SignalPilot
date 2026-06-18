-- B2B settlement fact: one row per Rafiki merchant settlement, with reconciled
-- line-level rollups from collections and payouts.
with settlements as (
    select * from {{ ref('stg_rafiki__settlements') }}
),

lines as (
    select
        settlement_id,
        count(*)                                            as line_count_actual,
        sum(case when line_type = 'collection' then amount_usd else 0 end) as lines_collected_usd,
        sum(case when line_type = 'payout' then amount_usd else 0 end)     as lines_paid_out_usd,
        sum(fee_usd)                                        as lines_fees_usd,
        sum(signed_amount_usd)                              as lines_net_usd
    from {{ ref('int_rafiki_settlement_lines') }}
    group by settlement_id
)

select
    s.settlement_id,
    s.merchant_id,
    s.settlement_date,
    s.settlement_currency,
    s.gross_collected_usd,
    s.gross_paid_out_usd,
    s.total_fees_usd,
    s.net_amount_usd,
    s.line_count,
    s.status,
    -- reconciled line-level rollups
    coalesce(l.line_count_actual, 0)            as line_count_actual,
    coalesce(l.lines_collected_usd, 0)          as lines_collected_usd,
    coalesce(l.lines_paid_out_usd, 0)           as lines_paid_out_usd,
    coalesce(l.lines_fees_usd, 0)               as lines_fees_usd,
    coalesce(l.lines_net_usd, 0)                as lines_net_usd,
    s.created_at,
    s.settled_at
from settlements s
left join lines l
    on s.settlement_id = l.settlement_id
