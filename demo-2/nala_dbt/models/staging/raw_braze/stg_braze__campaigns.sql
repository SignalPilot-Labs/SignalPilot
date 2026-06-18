-- Braze single-step campaigns, 1:1 with the source.
-- Standardizes the legacy STOPPED status and parses the ISO-Z text sent dates.
with source as (
    select * from {{ source('raw_braze', 'campaigns') }}
)

select
    campaign_id,
    name                                            as campaign_name,
    lower(channel)                                  as channel,
    messaging_type,
    tags,
    case
        when lower(status) = 'stopped' then 'archived'
        else lower(status)
    end                                             as status,
    coalesce(is_archived, false)                    as is_archived,
    first_sent::timestamptz                         as first_sent_at,
    last_sent::timestamptz                          as last_sent_at,
    created_at                                       as created_at,
    updated_at                                       as updated_at
from source
