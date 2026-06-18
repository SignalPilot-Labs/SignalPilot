with source as (
    select * from {{ source('raw_onfido', 'checks') }}
)

select
    id                                          as onfido_check_id,
    applicant_id                                as onfido_applicant_id,
    status,
    -- standardize legacy PASS/FAIL into the modern clear/consider enum
    case lower(result)
        when 'pass' then 'clear'
        when 'fail' then 'consider'
        else lower(result)
    end                                         as result,
    tags,
    report_ids,
    applicant_provides_data,
    redirect_uri,
    -- created_at is an ISO string; completed_at is epoch SECONDS -> unify to timestamptz
    created_at::timestamptz                     as created_at,
    to_timestamp(completed_at_epoch)            as completed_at
from source
