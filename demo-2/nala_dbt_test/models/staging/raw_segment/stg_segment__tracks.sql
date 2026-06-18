-- stg_segment__tracks: cleaned Segment track event stream, 1:1 with source.
-- Coalesces the messy Segment timestamp set into one event_at; trims user_id.
with source as (
    select * from {{ source('raw_segment', 'tracks') }}
)

select
    id                                         as event_id,
    event                                      as event_name,
    event_text,
    anonymous_id,
    nullif(trim(user_id), '')                  as customer_code,
    properties,
    context_ip                                 as ip_address,
    context_library_name                       as library_name,
    context_app_version                        as app_version,
    lower(context_device_type)                 as platform,
    context_device_id                          as device_id,
    context_os_name                            as os_name,
    context_locale                             as locale,
    context_timezone                           as timezone,
    -- canonical event time: prefer the tz timestamp, fall back to received_at
    coalesce(timestamp, received_at)           as event_at,
    sent_at,
    received_at                                as received_at,
    loaded_at                                  as loaded_at,
    (user_id is null)                          as is_anonymous
from source
