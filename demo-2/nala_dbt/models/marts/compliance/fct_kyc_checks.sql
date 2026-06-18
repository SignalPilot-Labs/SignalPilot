-- KYC check fact: one row per Onfido check.
select
    onfido_check_id,
    onfido_applicant_id,
    customer_code,
    customer_uuid,
    first_name,
    last_name,
    email,
    address_country,
    status,
    result,
    outcome,
    is_sandbox,
    created_at,
    completed_at
from {{ ref('int_kyc_checks') }}
