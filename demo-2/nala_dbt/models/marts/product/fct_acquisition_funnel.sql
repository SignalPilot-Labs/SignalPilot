-- Acquisition funnel fact: one row per user (customer_code) with the timestamp
-- of each funnel step and boolean step flags. `converted` is true when the user
-- reached the first-transfer step. Also exposes first-touch attribution.
with funnel as (

    select * from {{ ref('int_acquisition_funnel_steps') }}

),

attribution as (

    select
        customer_code,
        first_touch_media_source,
        first_touch_channel,
        first_touch_campaign,
        is_organic_install
    from {{ ref('int_attribution_first_touch') }}

)

select
    f.customer_code,
    f.installed_at,
    f.signed_up_at,
    f.kyc_at,
    f.first_transfer_at,
    (f.installed_at is not null)           as did_install,
    (f.signed_up_at is not null)           as did_signup,
    (f.kyc_at is not null)                 as did_kyc,
    (f.first_transfer_at is not null)      as did_first_transfer,
    (f.first_transfer_at is not null)      as converted,
    a.first_touch_media_source,
    a.first_touch_channel,
    a.first_touch_campaign,
    a.is_organic_install
from funnel f
left join attribution a
    on f.customer_code = a.customer_code
