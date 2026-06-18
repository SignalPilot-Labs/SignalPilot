-- Daily product-event fact, one row per event_date x event_source x event_name.
-- Surrogate key hashes the grain. Sourced from the unioned Segment + Amplitude
-- event aggregate.
with events as (

    select * from {{ ref('int_app_events_daily') }}

)

select
    md5(
        coalesce(event_date::text, '') || '|' ||
        coalesce(event_source, '') || '|' ||
        coalesce(event_name, '')
    )                                      as product_event_daily_id,
    event_date,
    event_source,
    event_name,
    event_count,
    distinct_users
from events
