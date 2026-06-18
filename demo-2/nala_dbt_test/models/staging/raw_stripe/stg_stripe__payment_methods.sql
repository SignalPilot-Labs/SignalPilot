-- One row per Stripe payment method. epoch seconds -> timestamptz.
with source as (
    select * from {{ source('raw_stripe', 'payment_methods') }}
)

select
    id                                                  as payment_method_id,
    customer                                            as stripe_customer_id,
    type                                                as payment_method_type,

    lower(card_brand)                                   as card_brand,
    card_last4,
    card_bin,
    card_exp_month,
    card_exp_year,
    card_funding,
    card_country,
    card_fingerprint,
    -- billing email arrives with casing/space drift
    nullif(lower(trim(billing_email)), '')              as billing_email,
    livemode                                            as is_livemode,

    to_timestamp(created)                               as created_at,
    metadata
from source
