-- One row per settlement line: the individual collections (money in) and payouts
-- (money out) that roll up into a Rafiki merchant settlement. Unioned to a common
-- grain so a settlement fact can sum signed USD per settlement.
with collections as (
    select * from {{ ref('stg_rafiki__collections') }}
),

payouts as (
    select * from {{ ref('stg_rafiki__payouts') }}
),

collection_lines as (
    select
        settlement_id,
        collection_id                           as line_id,
        'collection'                            as line_type,
        merchant_id,
        amount_usd,
        fee_usd,
        -- collections are money in: positive contribution
        amount_usd                              as signed_amount_usd,
        status,
        received_at                             as line_at
    from collections
    where settlement_id is not null
),

payout_lines as (
    select
        settlement_id,
        payout_id                               as line_id,
        'payout'                                as line_type,
        merchant_id,
        amount_usd,
        fee_usd,
        -- payouts are money out: negative contribution
        -1 * amount_usd                         as signed_amount_usd,
        status,
        created_at                              as line_at
    from payouts
    where settlement_id is not null
)

select * from collection_lines
union all
select * from payout_lines
