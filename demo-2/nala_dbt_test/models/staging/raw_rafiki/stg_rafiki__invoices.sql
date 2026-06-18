with source as (
    select * from {{ source('raw_rafiki', 'invoices') }}
)

select
    invoice_id,
    merchant_id,
    invoice_number,
    period_start,
    period_end,
    currency           as invoice_currency,
    subtotal_usd,
    tax_usd,
    total_usd,
    amount_paid_usd,
    lower(status)      as status,
    due_date,
    issued_at          as issued_at,
    paid_at            as paid_at,
    pdf_url,
    metadata
from source
