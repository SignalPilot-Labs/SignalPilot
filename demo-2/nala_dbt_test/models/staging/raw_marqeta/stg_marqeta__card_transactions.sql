-- One row per Marqeta card transaction. ISO-offset strings -> timestamptz/date.
with source as (
    select * from {{ source('raw_marqeta', 'card_transactions') }}
)

select
    token                                               as card_transaction_id,
    card_token                                          as card_id,
    user_token                                          as cardholder_id,
    funding_source_token                                as funding_source_id,

    type                                                as transaction_type,
    -- standardize state to lowercase
    lower(state)                                        as status,

    amount,
    upper(currency_code)                                as currency,

    approval_code,
    response_code,
    response_memo,
    network,
    acquirer_mid,
    merchant_name,
    mcc,
    merchant_country,
    is_recurring,

    -- transfer key arrives with dirty casing; normalize to lowercase uuid
    nullif(lower(nala_transfer_id), '')                 as nala_transfer_id,

    -- ISO-8601 offset string -> timestamptz; date string -> date
    user_transaction_time::timestamptz                  as transacted_at,
    settlement_date::date                               as settlement_date
from source
