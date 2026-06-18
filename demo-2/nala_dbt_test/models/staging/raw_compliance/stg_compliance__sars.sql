with source as (
    select * from {{ source('raw_compliance', 'sars') }}
)

select
    sar_id,
    sar_ref,
    nullif(trim(customer_code), '')             as customer_code,
    customer_uuid,
    subject_name,
    subject_national_id,
    subject_national_id_hash,
    transfer_id,
    activity_type,
    -- standardize legacy 'SUBMITTED' status into 'filed'
    case lower(status)
        when 'submitted' then 'filed'
        else lower(status)
    end                                         as status,
    priority,
    regulator,
    filing_reference,
    narrative,
    amount_usd,
    filed_by,
    -- internal system: timestamps already timestamptz
    filed_at,
    created_at,
    updated_at
from source
