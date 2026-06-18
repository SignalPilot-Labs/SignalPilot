-- Unions Google Ads + Meta Ads daily spend into one grain:
-- report_date x channel x campaign. Staging already normalized spend to major
-- currency units (google cost from micros, meta spend already major units), so
-- this layer only aligns column shapes and tags the channel.
with google as (

    select
        report_date,
        'google_ads'                       as channel,
        campaign_id::text                  as campaign_id,
        currency_code,
        impressions::bigint                as impressions,
        clicks::bigint                     as clicks,
        cost                               as spend,
        conversions::numeric               as conversions
    from {{ ref('stg_google_ads__ad_performance_daily') }}

),

google_agg as (

    -- staging is at ad_group/device grain; roll up to date x campaign
    select
        report_date,
        channel,
        campaign_id,
        max(currency_code)                 as currency_code,
        sum(impressions)                   as impressions,
        sum(clicks)                        as clicks,
        sum(spend)                         as spend,
        sum(conversions)                   as conversions
    from google
    group by 1, 2, 3

),

meta as (

    select
        report_date,
        'meta_ads'                         as channel,
        campaign_id::text                  as campaign_id,
        currency_code,
        impressions::bigint                as impressions,
        clicks::bigint                     as clicks,
        spend                              as spend,
        (app_installs + purchases)::numeric as conversions
    from {{ ref('stg_meta_ads__ad_insights_daily') }}

),

meta_agg as (

    -- staging is at ad_set/platform grain; roll up to date x campaign
    select
        report_date,
        channel,
        campaign_id,
        max(currency_code)                 as currency_code,
        sum(impressions)                   as impressions,
        sum(clicks)                        as clicks,
        sum(spend)                         as spend,
        sum(conversions)                   as conversions
    from meta
    group by 1, 2, 3

)

select * from google_agg
union all
select * from meta_agg
