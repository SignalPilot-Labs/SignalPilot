-- Per-user acquisition funnel step timestamps:
--   install      -> earliest AppsFlyer install
--   signup       -> earliest 'Signup Completed' product event
--   kyc          -> earliest 'KYC Approved' (fallback 'KYC Submitted') event
--   first_transfer -> earliest completed transfer in core_transfers
-- Keyed on customer_code. Transfers are joined in via the customer_id<->code map
-- in stg_core_transfers__customers.
with installs as (

    select
        customer_code,
        min(installed_at)                  as installed_at
    from {{ ref('stg_appsflyer__installs') }}
    where customer_code is not null
    group by 1

),

events as (

    select customer_code, event_name, event_at
    from {{ ref('stg_segment__tracks') }}
    where customer_code is not null
    union all
    select customer_code, event_name, event_at
    from {{ ref('stg_amplitude__events') }}
    where customer_code is not null

),

signup as (

    select customer_code, min(event_at) as signed_up_at
    from events
    where event_name = 'Signup Completed'
    group by 1

),

kyc_approved as (

    select customer_code, min(event_at) as kyc_at
    from events
    where event_name = 'KYC Approved'
    group by 1

),

kyc_submitted as (

    select customer_code, min(event_at) as kyc_at
    from events
    where event_name = 'KYC Submitted'
    group by 1

),

kyc as (

    select
        coalesce(a.customer_code, s.customer_code) as customer_code,
        coalesce(a.kyc_at, s.kyc_at)               as kyc_at
    from kyc_approved a
    full outer join kyc_submitted s
        on a.customer_code = s.customer_code

),

customers as (

    select customer_id, customer_code
    from {{ ref('stg_core_transfers__customers') }}

),

first_transfer as (

    select
        c.customer_code,
        min(t.completed_at)                as first_transfer_at
    from {{ ref('stg_core_transfers__transfers') }} t
    inner join customers c
        on t.customer_id = c.customer_id
    where t.status = 'COMPLETED'
      and t.completed_at is not null
    group by 1

),

all_users as (

    select customer_code from installs
    union
    select customer_code from signup
    union
    select customer_code from kyc
    union
    select customer_code from first_transfer

)

select
    u.customer_code,
    i.installed_at,
    s.signed_up_at,
    k.kyc_at,
    f.first_transfer_at
from all_users u
left join installs i        on u.customer_code = i.customer_code
left join signup s          on u.customer_code = s.customer_code
left join kyc k             on u.customer_code = k.customer_code
left join first_transfer f  on u.customer_code = f.customer_code
