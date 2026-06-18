-- fct_revenue_daily must have one row per (date, corridor, send ccy, receive ccy).
select
    revenue_date, corridor_id, send_currency, receive_currency, count(*) as n
from {{ ref('fct_revenue_daily') }}
group by 1, 2, 3, 4
having count(*) > 1
