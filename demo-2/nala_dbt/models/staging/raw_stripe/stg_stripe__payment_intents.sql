-- One row per Stripe payment intent. epoch seconds -> timestamptz; cents -> major.
with source as (
    select * from {{ source('raw_stripe', 'payment_intents') }}
)

select
    id                                                  as payment_intent_id,
    latest_charge                                       as charge_id,
    customer                                            as stripe_customer_id,
    payment_method                                      as payment_method_id,

    amount / 100.0                                      as amount,
    amount_received / 100.0                             as amount_received,
    upper(currency)                                     as currency,

    lower(status)                                       as status,
    capture_method,
    confirmation_method,
    description,
    statement_descriptor,
    cancellation_reason,

    -- transfer key arrives with dirty casing; normalize to lowercase uuid
    nullif(lower(nala_transfer_id), '')                 as nala_transfer_id,

    to_timestamp(created)                               as created_at,
    case when canceled_at is not null
         then to_timestamp(canceled_at) end             as canceled_at,
    metadata
from source
