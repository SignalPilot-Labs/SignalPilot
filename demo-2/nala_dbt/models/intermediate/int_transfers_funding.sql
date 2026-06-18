-- int_transfers_funding: each transfer joined to its funding leg.
-- Funding can arrive via Stripe (card/PI), Plaid (bank debit) or Marqeta (card).
-- All three carry nala_transfer_id (lowercase uuid) = transfers.transfer_id.
-- Grain: one row per transfer_id. We pick ONE funding source with priority
-- stripe > plaid > marqeta, de-duping multiple rows per transfer.
-- transfer_id is uuid in core; the funding sources carry it as a text
-- nala_transfer_id, so we compare on text.
with transfers as (
    select
        transfer_id::text                               as transfer_id,
        send_amount, send_currency, funding_method, funding_partner
    from {{ ref('stg_core_transfers__transfers') }}
),

stripe_pi as (
    select
        nala_transfer_id                                as transfer_id,
        payment_intent_id                               as funding_reference,
        amount                                          as funding_amount,
        currency                                        as funding_currency,
        status                                          as funding_status,
        created_at                                      as funded_at,
        row_number() over (
            partition by nala_transfer_id order by created_at desc
        )                                               as rn
    from {{ ref('stg_stripe__payment_intents') }}
    where nala_transfer_id is not null
),

plaid_tx as (
    select
        nala_transfer_id                                as transfer_id,
        transaction_id                                  as funding_reference,
        amount                                          as funding_amount,
        currency                                        as funding_currency,
        case when is_pending then 'pending' else 'succeeded' end as funding_status,
        created_at                                      as funded_at,
        row_number() over (
            partition by nala_transfer_id order by created_at desc
        )                                               as rn
    from {{ ref('stg_plaid__transactions') }}
    where nala_transfer_id is not null
),

marqeta_tx as (
    select
        nala_transfer_id                                as transfer_id,
        card_transaction_id                             as funding_reference,
        amount                                          as funding_amount,
        currency                                        as funding_currency,
        status                                          as funding_status,
        transacted_at                                   as funded_at,
        row_number() over (
            partition by nala_transfer_id order by transacted_at desc
        )                                               as rn
    from {{ ref('stg_marqeta__card_transactions') }}
    where nala_transfer_id is not null
)

select
    t.transfer_id,
    coalesce(s.transfer_id is not null, false) as has_stripe_funding,
    coalesce(p.transfer_id is not null, false) as has_plaid_funding,
    coalesce(m.transfer_id is not null, false) as has_marqeta_funding,

    case
        when s.transfer_id is not null then 'stripe'
        when p.transfer_id is not null then 'plaid'
        when m.transfer_id is not null then 'marqeta'
        else null
    end                                        as funding_source,

    coalesce(s.funding_reference, p.funding_reference, m.funding_reference) as funding_reference,
    coalesce(s.funding_amount,    p.funding_amount,    m.funding_amount)    as funding_amount,
    coalesce(s.funding_currency,  p.funding_currency,  m.funding_currency)  as funding_currency,
    coalesce(s.funding_status,    p.funding_status,    m.funding_status)    as funding_status,
    coalesce(s.funded_at,         p.funded_at,         m.funded_at)         as funded_at
from transfers t
left join stripe_pi  s on t.transfer_id = s.transfer_id  and s.rn = 1
left join plaid_tx   p on t.transfer_id = p.transfer_id  and p.rn = 1
left join marqeta_tx m on t.transfer_id = m.transfer_id  and m.rn = 1
