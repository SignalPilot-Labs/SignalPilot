-- stg_appsflyer__installs: cleaned AppsFlyer installs, 1:1 with source.
-- Parses the naive ISO-string install_time/attributed_touch_time into timestamptz.
with source as (
    select * from {{ source('raw_appsflyer', 'installs') }}
)

select
    appsflyer_id,
    nullif(trim(customer_user_id), '')         as customer_code,
    -- naive ISO string -> timestamptz
    to_timestamp(install_time, 'YYYY-MM-DD HH24:MI:SS')           as installed_at,
    to_timestamp(attributed_touch_time, 'YYYY-MM-DD HH24:MI:SS')  as attributed_touch_at,
    attributed_touch_type,
    media_source,
    campaign,
    campaign_id,
    af_adset                                   as adset,
    af_ad                                      as ad,
    af_channel                                 as channel,
    lower(platform)                            as platform,
    app_id,
    app_version,
    device_model,
    os_version,
    country_code,
    language,
    idfa,
    idfv,
    advertising_id,
    ip                                         as ip_address,
    is_organic,
    is_retargeting,
    is_primary_attribution
from source
