-- fct_ledger_balances must have one row per (account_id, balance_date).
select account_id, balance_date, count(*) as n
from {{ ref('fct_ledger_balances') }}
group by 1, 2
having count(*) > 1
