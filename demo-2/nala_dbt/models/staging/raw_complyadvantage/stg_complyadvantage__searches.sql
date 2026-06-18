with source as (
    select * from {{ source('raw_complyadvantage', 'searches') }}
)

select
    id                                          as search_id,
    -- ref / client_ref are duplicate columns; coalesce to one customer_code join key
    nullif(trim(coalesce(ref, client_ref)), '') as customer_code,
    lower(trim(nala_customer_email))            as customer_email,
    search_term,
    searcher_id,
    assignee_id,
    filters,
    lower(match_status)                         as match_status,
    lower(risk_level)                           as risk_level,
    total_hits,
    total_matches,
    coalesce(is_monitored, false)               as is_monitored,
    share_url,
    tags,
    created_at::timestamptz                     as created_at,
    updated_at::timestamptz                     as updated_at
from source
