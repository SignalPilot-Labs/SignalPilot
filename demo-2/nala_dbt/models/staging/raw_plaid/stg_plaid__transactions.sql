-- One row per Plaid bank transaction. ISO strings -> proper date/timestamptz.
-- Plaid sign convention: positive amount = money OUT of the account.
with source as (
    select * from {{ source('raw_plaid', 'transactions') }}
)

select
    transaction_id,
    account_id,
    item_id,

    amount,
    upper(iso_currency_code)                            as currency,

    -- date strings -> date / timestamp
    date::date                                          as posted_date,
    authorized_date::date                               as authorized_date,

    name                                                as description,
    merchant_name,
    payment_channel,
    pending                                             as is_pending,
    category                                            as legacy_category,
    personal_finance_category,
    pending_transaction_id,

    -- transfer key arrives with dirty casing; normalize to lowercase uuid
    nullif(lower(nala_transfer_id), '')                 as nala_transfer_id,

    -- ISO-8601 string -> timestamptz
    created_at::timestamptz                             as created_at
from source
