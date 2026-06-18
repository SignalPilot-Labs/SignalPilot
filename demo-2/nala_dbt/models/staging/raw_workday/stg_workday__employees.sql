-- Workday employees (staff), one row per worker.
-- Standardizes the worker status enum and normalizes the dirty personal email.
with source as (

    select * from {{ source('raw_workday', 'employees') }}

)

select
    employee_id,
    worker_uuid,
    first_name,
    last_name,
    preferred_name,
    work_email,
    lower(trim(personal_email))                 as personal_email,
    phone,
    national_id,
    national_id_hash,
    date_of_birth,
    gender,
    department_id,
    job_title,
    job_level,
    management_chain                            as manager_employee_id,
    location,
    employment_type,
    case lower(worker_status)
        when 'on leave' then 'on_leave'
        else lower(worker_status)
    end                                         as worker_status,
    hire_date,
    termination_date,
    is_active,
    created_at,
    raw_attributes
from source
