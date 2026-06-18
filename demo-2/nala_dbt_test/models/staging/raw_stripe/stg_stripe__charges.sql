-- One row per Stripe charge. epoch seconds -> timestamptz; cents -> major units.
with source as (
    select * from {{ source('raw_stripe', 'charges') }}
)

select
    id                                                  as charge_id,
    payment_intent                                      as payment_intent_id,
    customer                                            as stripe_customer_id,
    payment_method                                      as payment_method_id,
    balance_transaction                                 as balance_transaction_id,

    -- amounts: MINOR units (cents) -> MAJOR units
    amount / 100.0                                      as amount,
    amount_captured / 100.0                             as amount_captured,
    amount_refunded / 100.0                             as amount_refunded,
    upper(currency)                                     as currency,

    -- standardize status: legacy 'paid' -> 'succeeded'
    case
        when lower(status) in ('paid', 'succeeded') then 'succeeded'
        when lower(status) = 'failed'               then 'failed'
        when lower(status) = 'pending'              then 'pending'
        else lower(status)
    end                                                 as status,

    paid                                                as is_paid,
    captured                                            as is_captured,
    refunded                                            as is_refunded,
    disputed                                            as is_disputed,

    card_brand,
    card_last4,
    card_funding,
    card_country,
    receipt_email,
    failure_code,
    failure_message,
    outcome_type,
    risk_level,
    livemode                                            as is_livemode,

    -- epoch SECONDS -> timestamptz
    to_timestamp(created)                               as created_at,
    metadata
from source
