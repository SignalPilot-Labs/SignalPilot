-- Zendesk CSAT ratings, 1:1 with the source.
with source as (
    select * from {{ source('raw_zendesk', 'satisfaction_ratings') }}
)

select
    id                                              as satisfaction_rating_id,
    ticket_id,
    assignee_id,
    requester_id,
    lower(score)                                    as score,
    case lower(score)
        when 'good' then 1
        when 'bad'  then 0
        else null
    end                                             as is_satisfied,
    nullif(trim(comment), '')                       as comment,
    created_at                                       as created_at,
    updated_at                                       as updated_at
from source
