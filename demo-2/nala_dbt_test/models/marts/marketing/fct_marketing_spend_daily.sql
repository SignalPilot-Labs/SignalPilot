-- Daily paid-marketing spend fact, one row per report_date x channel x campaign.
-- Surrogate key hashes the grain. Spend is in the campaign's account currency.
with spend as (

    select * from {{ ref('int_marketing_spend_unioned') }}

)

select
    md5(
        coalesce(report_date::text, '') || '|' ||
        coalesce(channel, '') || '|' ||
        coalesce(campaign_id, '')
    )                                      as marketing_spend_id,
    report_date,
    channel,
    campaign_id,
    currency_code,
    impressions,
    clicks,
    spend,
    conversions,
    case
        when impressions > 0
            then round(clicks::numeric / impressions, 5)
        else 0
    end                                    as ctr,
    case
        when clicks > 0
            then round(spend / clicks, 4)
        else null
    end                                    as cost_per_click,
    case
        when conversions > 0
            then round(spend / conversions, 4)
        else null
    end                                    as cost_per_conversion
from spend
