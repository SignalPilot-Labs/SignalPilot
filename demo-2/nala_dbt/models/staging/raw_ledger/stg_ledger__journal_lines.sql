-- Ledger fact: one debit/credit line per row. Debits = credits per entry_id.
-- 1:1 with source, no joins. Normalizes the (direction, amount) sign and the
-- denormalized debit/credit columns into a single signed_amount.
with source as (
    select * from {{ source('raw_ledger', 'journal_lines') }}
)

select
    line_id,
    entry_id,
    line_no,
    account_id,
    upper(direction)                              as direction,
    amount,
    case when upper(direction) = 'DEBIT'
         then amount else -amount end             as signed_amount,
    coalesce(debit, 0)                            as debit_amount,
    coalesce(credit, 0)                           as credit_amount,
    currency,
    memo,
    posted_at                                     as posted_at
from source
