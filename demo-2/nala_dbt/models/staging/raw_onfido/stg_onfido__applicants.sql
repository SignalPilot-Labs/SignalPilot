with source as (
    select * from {{ source('raw_onfido', 'applicants') }}
)

select
    id                                          as onfido_applicant_id,
    -- join key to NALA core; trim/upper the dirtied customer code
    nullif(trim(external_id), '')               as customer_code,
    nullif(nala_customer_uuid, '')              as customer_uuid,
    first_name,
    last_name,
    -- email dirtied across systems: trim + lowercase to a canonical form
    lower(trim(email))                          as email,
    dob,
    address_line1,
    address_town,
    address_postcode,
    upper(address_country)                      as address_country,
    nullif(trim(phone_number), '')              as phone_number,
    id_numbers,
    coalesce(sandbox, false)                    as is_sandbox,
    coalesce(is_deleted, false)                 as is_deleted,
    -- coalesce the messy ISO-string timestamps into clean timestamptz
    created_at::timestamptz                     as created_at,
    deleted_at::timestamptz                     as deleted_at
from source
