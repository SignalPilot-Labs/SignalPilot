-- dim_customers: identity-resolved customer dimension with PII flags and
-- lifetime activity rolled in. Grain: one row per customer.
with identity as (
    select * from {{ ref('int_customer_identity_resolved') }}
),

lifetime as (
    select * from {{ ref('int_customer_lifetime') }}
)

select
    i.customer_id,
    i.customer_code,
    i.customer_uuid,

    -- PII attributes
    i.first_name,
    i.last_name,
    i.full_name,
    i.email,
    i.phone,
    i.date_of_birth,
    i.last_ip_address,

    -- PII presence flags (governance)
    (i.email is not null)                                          as has_email,
    (i.phone is not null)                                          as has_phone,
    (i.date_of_birth is not null)                                  as has_date_of_birth,

    -- profile
    i.home_country,
    i.default_currency,
    i.kyc_tier,
    i.account_status,
    i.signup_platform,
    i.platform,
    i.last_app_version,

    -- identity resolution
    i.has_onfido_applicant,
    i.onfido_applicant_id,
    i.has_segment_identity,
    i.segment_identify_count,
    i.systems_matched,
    i.email_matches_kyc,

    -- lifetime activity
    coalesce(l.transfer_count, 0)                                  as transfer_count,
    coalesce(l.completed_transfer_count, 0)                        as completed_transfer_count,
    l.first_transfer_at,
    l.last_transfer_at,
    coalesce(l.total_send_amount, 0)                               as total_send_amount,
    coalesce(l.total_completed_send_amount, 0)                     as total_completed_send_amount,
    coalesce(l.total_fees_charged, 0)                              as total_fees_charged,
    coalesce(l.total_revenue, 0)                                   as total_revenue,
    coalesce(l.distinct_corridors, 0)                              as distinct_corridors,
    l.primary_send_currency,
    (l.transfer_count is not null and l.transfer_count > 0)        as is_active_sender,

    i.is_deleted,
    i.created_at
from identity i
left join lifetime l on i.customer_id = l.customer_id
