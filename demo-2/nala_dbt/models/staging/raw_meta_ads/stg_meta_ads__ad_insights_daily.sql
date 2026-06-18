-- Meta ad insights, daily per ad set/platform.
-- Extracts install + purchase conversions out of the actions JSON array.
with source as (
    select * from {{ source('raw_meta_ads', 'ad_insights_daily') }}
)

select
    id                                              as ad_insight_id,
    date_start                                      as report_date,
    account_id,
    campaign_id,
    adset_id                                        as ad_set_id,
    lower(publisher_platform)                       as publisher_platform,
    impressions,
    clicks,
    spend,
    reach,
    account_currency                                as currency_code,
    -- pull conversions out of the actions jsonb array
    coalesce((
        select sum((a ->> 'value')::numeric)
        from jsonb_array_elements(coalesce(actions, '[]'::jsonb)) as a
        where a ->> 'action_type' = 'mobile_app_install'
    ), 0)                                           as app_installs,
    coalesce((
        select sum((a ->> 'value')::numeric)
        from jsonb_array_elements(coalesce(actions, '[]'::jsonb)) as a
        where a ->> 'action_type' = 'offsite_conversion.fb_pixel_purchase'
    ), 0)                                           as purchases,
    loaded_at                                        as loaded_at
from source
