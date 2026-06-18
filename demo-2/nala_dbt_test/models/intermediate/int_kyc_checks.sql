-- One row per Onfido KYC check, enriched with applicant identity and an outcome.
with checks as (
    select * from {{ ref('stg_onfido__checks') }}
),

applicants as (
    select * from {{ ref('stg_onfido__applicants') }}
)

select
    c.onfido_check_id,
    c.onfido_applicant_id,
    a.customer_code,
    a.customer_uuid,
    a.first_name,
    a.last_name,
    a.email,
    a.address_country,
    c.status,
    c.result,
    -- derive a coarse pass/fail outcome from the standardized result enum
    case
        when c.result = 'clear' then 'pass'
        when c.result = 'consider' then 'fail'
        else 'unknown'
    end                                         as outcome,
    c.tags,
    c.report_ids,
    c.applicant_provides_data,
    a.is_sandbox,
    c.created_at,
    c.completed_at
from checks c
left join applicants a
    on c.onfido_applicant_id = a.onfido_applicant_id
