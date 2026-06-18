-- fct_ledger_balances: per-account running balance over time.
-- Aggregates the cleaned double-entry lines to a daily net movement per account,
-- then accumulates a running end-of-day balance. A day appears only if the
-- account had activity that day.
-- Grain: one row per (account_id, balance_date).
with entries as (
    select * from {{ ref('int_ledger_entries') }}
),

daily as (
    select
        account_id,
        account_code,
        account_name,
        account_type_id,
        customer_code,
        currency,
        posted_date                                     as balance_date,
        sum(signed_amount)                              as net_movement,
        sum(debit_amount)                               as total_debits,
        sum(credit_amount)                              as total_credits,
        count(*)                                        as line_count
    from entries
    group by 1, 2, 3, 4, 5, 6, 7
)

select
    account_id,
    balance_date,
    account_code,
    account_name,
    account_type_id,
    customer_code,
    currency,
    net_movement,
    total_debits,
    total_credits,
    line_count,
    sum(net_movement) over (
        partition by account_id
        order by balance_date
        rows between unbounded preceding and current row
    )                                                   as running_balance
from daily
