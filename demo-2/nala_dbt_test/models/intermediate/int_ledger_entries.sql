-- int_ledger_entries: cleaned double-entry journal lines joined to their account.
-- Grain: one row per journal line (1:1 with stg_ledger__journal_lines).
with lines as (
    select * from {{ ref('stg_ledger__journal_lines') }}
),

accounts as (
    select
        account_id,
        account_code,
        account_name,
        account_type_id,
        currency        as account_currency,
        customer_code,
        is_contra
    from {{ ref('stg_ledger__accounts') }}
)

select
    l.line_id,
    l.entry_id,
    l.line_no,
    l.account_id,
    a.account_code,
    a.account_name,
    a.account_type_id,
    a.customer_code,
    a.is_contra,
    l.direction,
    l.amount,
    l.signed_amount,
    l.debit_amount,
    l.credit_amount,
    coalesce(l.currency, a.account_currency)            as currency,
    l.memo,
    l.posted_at,
    l.posted_at::date                                   as posted_date
from lines l
left join accounts a on l.account_id = a.account_id
