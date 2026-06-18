-- Daily Active Users (DAU) from product events. A user is "active" on a day if
-- they fired at least one identified (customer_code present) event in either
-- Segment or Amplitude. Counts distinct customer_code per event_date.
with events as (

    select customer_code, event_at
    from {{ ref('stg_segment__tracks') }}
    where customer_code is not null
      and event_at is not null
    union all
    select customer_code, event_at
    from {{ ref('stg_amplitude__events') }}
    where customer_code is not null
      and event_at is not null

)

select
    cast(event_at as date)                 as activity_date,
    count(distinct customer_code)          as active_users
from events
group by 1
