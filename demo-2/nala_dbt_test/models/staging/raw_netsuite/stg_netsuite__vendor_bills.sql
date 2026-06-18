-- NetSuite vendor bills, one row per AP bill header.
-- Standardizes the free-text bill status into a clean enum.
with source as (

    select * from {{ source('raw_netsuite', 'vendor_bills') }}

)

select
    bill_id,
    tranid,
    vendor_id,
    subsidiary_id,
    department_id,
    trandate                                                as bill_date,
    duedate                                                 as due_date,
    period_name,
    currency,
    exchange_rate,
    amount                                                  as net_amount,
    tax_amount,
    amount_base                                             as gross_amount_base,
    amount_paid,
    amount_remaining,
    case lower(status)
        when 'paid in full'      then 'paid'
        when 'pending approval'  then 'pending'
        else lower(status)
    end                                                     as status,
    lower(approval_status)                                  as approval_status,
    (amount_remaining > 0 and lower(status) <> 'cancelled') as is_outstanding,
    memo,
    created_at,
    updated_at
from source
