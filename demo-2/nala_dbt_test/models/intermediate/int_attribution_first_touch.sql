-- First-touch acquisition attribution per user: the earliest AppsFlyer install
-- row per customer_code, exposing its media_source / channel / campaign.
with installs as (

    select
        customer_code,
        installed_at,
        media_source,
        channel,
        campaign,
        campaign_id,
        is_organic,
        platform,
        row_number() over (
            partition by customer_code
            order by installed_at asc nulls last, appsflyer_id asc
        ) as rn
    from {{ ref('stg_appsflyer__installs') }}
    where customer_code is not null

)

select
    customer_code,
    installed_at                           as first_install_at,
    media_source                           as first_touch_media_source,
    channel                                as first_touch_channel,
    campaign                               as first_touch_campaign,
    campaign_id                            as first_touch_campaign_id,
    is_organic                             as is_organic_install,
    platform                               as install_platform
from installs
where rn = 1
