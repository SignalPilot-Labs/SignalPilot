-- Braze message-send event stream, one row per message event.
-- Coalesces the ISO-Z string and epoch-second columns into one clean sent_at.
with source as (
    select * from {{ source('raw_braze', 'messages_sent') }}
)

select
    id                                              as message_event_id,
    dispatch_id,
    campaign_id,
    canvas_id,
    external_user_id                                as customer_code,
    user_id                                         as braze_user_id,
    -- PII: normalize the dirty email (trim + lowercase)
    nullif(lower(trim(email)), '')                  as email,
    lower(channel)                                  as channel,
    message_variation,
    lower(event_type)                               as event_type,
    -- coalesce ISO-Z string / epoch seconds into one tz timestamp
    coalesce(
        sent_at::timestamptz,
        to_timestamp("time")
    )                                               as sent_at,
    coalesce(is_amp, false)                         as is_amp
from source
