-- NetSuite GL transaction lines, one row per posted line.
-- Coalesces the messy epoch-ms creation timestamp to a clean timestamptz and
-- standardizes the free-text status enum.
with source as (

    select * from {{ source('raw_netsuite', 'gl_transactions') }}

)

select
    transaction_line_id,
    transaction_id,
    tranid,
    transaction_type,
    line_number,
    account_id,
    subsidiary_id,
    department_id,
    trandate                                                as transaction_date,
    period_name,
    memo,
    debit,
    credit,
    amount                                                  as amount_base,
    currency,
    exchange_rate,
    posting                                                 as is_posting,
    case lower(status)
        when 'paid in full'      then 'paid'
        when 'pending approval'  then 'pending'
        else lower(status)
    end                                                     as status,
    to_timestamp(created_epoch_ms / 1000.0)                 as created_at
from source
