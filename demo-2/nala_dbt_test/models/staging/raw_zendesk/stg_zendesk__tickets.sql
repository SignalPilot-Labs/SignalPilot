-- Zendesk tickets, 1:1 with the source.
-- Parses the ISO-Z solved_at text into a clean solved_at timestamp.
with source as (
    select * from {{ source('raw_zendesk', 'tickets') }}
)

select
    id                                              as ticket_id,
    requester_id,
    assignee_id,
    subject,
    lower(status)                                   as status,
    lower(priority)                                 as priority,
    lower(type)                                     as ticket_type,
    lower(channel)                                  as channel,
    tags,
    group_name,
    -- PII: normalize the dirty denormalized email
    nullif(lower(trim(requester_email)), '')        as requester_email,
    transfer_id,
    lower(satisfaction)                             as satisfaction,
    coalesce(is_public, true)                       as is_public,
    created_at                                       as created_at,
    updated_at                                       as updated_at,
    solved_at::timestamptz                          as solved_at,
    case when lower(status) in ('solved', 'closed') then true else false end
                                                    as is_resolved
from source
