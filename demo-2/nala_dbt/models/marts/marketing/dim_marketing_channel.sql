-- Marketing channel dimension. Distinct paid channels observed in spend plus the
-- first-touch acquisition media sources from AppsFlyer, classified into a coarse
-- channel_type for reporting (paid_search / paid_social / organic / referral).
with paid_channels as (

    select distinct channel as channel_name
    from {{ ref('int_marketing_spend_unioned') }}

),

attribution_sources as (

    select distinct first_touch_media_source as channel_name
    from {{ ref('int_attribution_first_touch') }}
    where first_touch_media_source is not null

),

all_channels as (

    select channel_name from paid_channels
    union
    select channel_name from attribution_sources

)

select
    md5(channel_name)                      as marketing_channel_id,
    channel_name,
    case
        when lower(channel_name) in ('google_ads', 'googleadwords_int', 'apple search ads')
            then 'paid_search'
        when lower(channel_name) in ('meta_ads', 'facebook ads', 'snapchat_int', 'tiktokglobal_int')
            then 'paid_social'
        when lower(channel_name) like '%organic%'
            then 'organic'
        when lower(channel_name) like '%referral%'
            then 'referral'
        else 'other'
    end                                    as channel_type,
    case
        when lower(channel_name) like '%organic%'
          or lower(channel_name) like '%referral%'
            then false
        else true
    end                                    as is_paid
from all_channels
