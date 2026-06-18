-- Daily product-event counts from Segment tracks + Amplitude events, unioned
-- and aggregated by event_date x source x event_name. Distinct users tracked
-- via customer_code (null when anonymous, so counted only where present).
with segment as (

    select
        event_at,
        event_name,
        customer_code,
        'segment'                          as event_source
    from {{ ref('stg_segment__tracks') }}

),

amplitude as (

    select
        event_at,
        event_name,
        customer_code,
        'amplitude'                        as event_source
    from {{ ref('stg_amplitude__events') }}

),

unioned as (

    select * from segment
    union all
    select * from amplitude

)

select
    cast(event_at as date)                 as event_date,
    event_source,
    event_name,
    count(*)                               as event_count,
    count(distinct customer_code)          as distinct_users
from unioned
where event_at is not null
group by 1, 2, 3
