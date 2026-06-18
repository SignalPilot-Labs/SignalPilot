-- Unions paid-ads daily spend into one grain: report_date x channel x campaign.
-- Staging already normalized spend to major currency units.
--
-- 2026-06 CHANGE (ticket GROW-555): we now run Google Performance Max as its own
-- channel, so add it below.
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

-- Performance Max channel
pmax_agg as (

    select
        report_date,
        'google_pmax'                      as channel,
        campaign_id,
        max(currency_code)                 as currency_code,
        sum(impressions)                   as impressions,
        sum(clicks)                        as clicks,
        sum(spend)                         as spend,
        sum(conversions)                   as conversions
    from google
    group by 1, 3

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
select * from pmax_agg
union all
select * from meta_agg
