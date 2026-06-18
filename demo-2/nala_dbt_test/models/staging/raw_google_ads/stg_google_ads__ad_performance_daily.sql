-- Google Ads daily performance per ad group/device.
-- Converts micros to currency units and recomputes CTR (legacy ctr is stale).
with source as (
    select * from {{ source('raw_google_ads', 'ad_performance_daily') }}
)

select
    id                                              as ad_performance_id,
    date                                            as report_date,
    campaign_id,
    ad_group_id,
    lower(device)                                   as device,
    impressions,
    clicks,
    -- micros -> currency units
    round(cost_micros / 1000000.0, 2)               as cost,
    conversions,
    conversions_value,
    currency_code,
    -- recompute CTR rather than trust the stale precomputed column
    case
        when impressions > 0 then round(clicks::numeric / impressions, 5)
        else 0
    end                                             as ctr,
    loaded_at                                        as loaded_at
from source
