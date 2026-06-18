-- Intercom conversations, 1:1 with the source.
-- All timestamps are epoch seconds EXCEPT waiting_since (epoch ms) — normalize
-- everything to clean tz timestamps.
with source as (
    select * from {{ source('raw_intercom', 'conversations') }}
)

select
    id                                              as conversation_id,
    contact_external_id                             as customer_code,
    -- PII: normalize the dirty email
    nullif(lower(trim(contact_email)), '')          as contact_email,
    lower(state)                                    as state,
    coalesce(open, false)                           as is_open,
    coalesce(read, false)                           as is_read,
    priority,
    source_type,
    source_subject,
    assignee_admin_id,
    team_assignee_id,
    coalesce(sla_breached, false)                   as is_sla_breached,
    rating                                          as csat_rating,
    tags,
    -- timing metrics out of the statistics blob
    (statistics ->> 'first_response_time')::bigint  as first_response_time_seconds,
    (statistics ->> 'time_to_close')::bigint         as time_to_close_seconds,
    -- waiting_since is epoch MS; created/updated/snoozed are epoch seconds
    to_timestamp(waiting_since / 1000.0)            as waiting_since_at,
    to_timestamp(snoozed_until)                      as snoozed_until_at,
    to_timestamp(created_at)                          as created_at,
    to_timestamp(updated_at)                          as updated_at
from source
