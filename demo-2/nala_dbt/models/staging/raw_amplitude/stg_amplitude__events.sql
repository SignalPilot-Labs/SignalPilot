-- stg_amplitude__events: cleaned Amplitude events, 1:1 with source.
-- Converts the EPOCH MS bigint timestamps into clean timestamptz columns.
with source as (
    select * from {{ source('raw_amplitude', 'events') }}
)

select
    uuid                                       as event_id,
    event_id                                   as client_event_seq,
    amplitude_id,
    nullif(trim(user_id), '')                  as customer_code,
    device_id,
    nullif(session_id, -1)                     as session_id,
    event_type                                 as event_name,
    -- epoch ms (bigint) -> timestamptz
    to_timestamp(event_time / 1000.0)          as event_at,
    to_timestamp(client_event_time / 1000.0)   as client_event_at,
    to_timestamp(server_upload_time / 1000.0)  as server_upload_at,
    event_properties,
    user_properties,
    app_version,
    lower(platform)                            as platform,
    os_name,
    country,
    region,
    city,
    ip_address,
    idfa,
    adid,
    is_attribution_event,
    (user_id is null)                          as is_anonymous
from source
