-- int_customer_identity_resolved: one row per canonical customer.
-- The canonical customer population lives in core_transfers.customers, keyed by
-- customer_code (CUS_xxxxxxxx). We stitch in identity signals observed across
-- Onfido (KYC) and Segment (analytics) by joining on customer_code, and surface
-- the cleaned email/phone for downstream identity matching.
-- Grain: one row per customer_id (== one canonical customer_code).
with customers as (
    select
        customer_id,
        customer_code,
        customer_uuid,
        first_name,
        last_name,
        email,
        phone,
        date_of_birth,
        send_country                                    as home_country,
        default_currency,
        kyc_tier,
        account_status,
        signup_platform,
        is_deleted,
        created_at
    from {{ ref('stg_core_transfers__customers') }}
),

onfido as (
    select
        customer_code,
        max(onfido_applicant_id)                        as onfido_applicant_id,
        max(customer_uuid)                              as onfido_customer_uuid,
        min(email)                                      as onfido_email,
        max(phone_number)                               as onfido_phone,
        max(address_country)                            as kyc_address_country,
        bool_or(true)                                   as has_onfido_applicant
    from {{ ref('stg_onfido__applicants') }}
    where customer_code is not null
    group by 1
),

segment as (
    select
        customer_code,
        min(email)                                      as segment_email,
        max(phone)                                      as segment_phone,
        max(ip_address)                                 as segment_ip_address,
        max(app_version)                                as segment_app_version,
        max(platform)                                   as segment_platform,
        count(*)                                        as segment_identify_count,
        bool_or(true)                                   as has_segment_identity
    from {{ ref('stg_segment__identifies') }}
    where customer_code is not null
    group by 1
)

select
    c.customer_id,
    c.customer_code,
    c.customer_uuid,
    c.first_name,
    c.last_name,
    nullif(trim(coalesce(c.first_name,'') || ' ' || coalesce(c.last_name,'')), '') as full_name,

    -- canonical contact (core is source of truth; fall back to other systems)
    coalesce(c.email, o.onfido_email, s.segment_email)              as email,
    coalesce(c.phone, o.onfido_phone, s.segment_phone)              as phone,
    c.date_of_birth,
    c.home_country,
    c.default_currency,
    c.kyc_tier,
    c.account_status,
    c.signup_platform,

    -- linked external identities
    o.onfido_applicant_id,
    coalesce(o.has_onfido_applicant, false)                         as has_onfido_applicant,
    coalesce(s.has_segment_identity, false)                         as has_segment_identity,
    coalesce(s.segment_identify_count, 0)                           as segment_identify_count,
    s.segment_ip_address                                           as last_ip_address,
    s.segment_app_version                                          as last_app_version,
    coalesce(c.signup_platform, s.segment_platform)                as platform,

    -- identity confidence: how many independent systems we matched
    (1
       + case when o.customer_code is not null then 1 else 0 end
       + case when s.customer_code is not null then 1 else 0 end)  as systems_matched,

    -- does the KYC email agree with the core email?
    case
        when o.onfido_email is null then null
        else (o.onfido_email = c.email)
    end                                                            as email_matches_kyc,

    c.is_deleted,
    c.created_at
from customers c
left join onfido  o on c.customer_code = o.customer_code
left join segment s on c.customer_code = s.customer_code
