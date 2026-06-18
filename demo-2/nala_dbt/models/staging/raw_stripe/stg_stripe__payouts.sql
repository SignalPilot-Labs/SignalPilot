-- One row per Stripe payout (NALA balance -> bank). epoch s -> timestamptz; cents -> major.
with source as (
    select * from {{ source('raw_stripe', 'payouts') }}
)

select
    id                                                  as payout_id,
    destination                                         as bank_account_id,

    amount / 100.0                                      as amount,
    upper(currency)                                     as currency,

    lower(status)                                       as status,
    type                                                as payout_type,
    method                                              as payout_method,
    bank_name,
    bank_last4,
    statement_descriptor,
    failure_code,
    automatic                                           as is_automatic,

    to_timestamp(created)                               as created_at,
    to_timestamp(arrival_date)                          as arrival_at,
    metadata
from source
