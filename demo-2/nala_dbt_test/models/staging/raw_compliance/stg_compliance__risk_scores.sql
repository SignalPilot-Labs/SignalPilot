with source as (
    select * from {{ source('raw_compliance', 'risk_scores') }}
)

select
    id                                          as risk_score_id,
    nullif(trim(customer_code), '')             as customer_code,
    customer_uuid,
    score                                       as risk_score,
    lower(risk_band)                            as risk_band,
    model_version,
    factors,
    coalesce(pep_flag, false)                   as pep_flag,
    coalesce(sanctions_flag, false)             as sanctions_flag,
    coalesce(adverse_media_flag, false)         as adverse_media_flag,
    coalesce(high_risk_country, false)          as high_risk_country,
    coalesce(is_current, false)                 as is_current_flag,
    -- the is_current flag is unreliable (~4% have >1 true); derive a trustworthy one
    row_number() over (
        partition by customer_code order by scored_at desc, id desc
    ) = 1                                       as is_latest,
    scored_at,
    created_at
from source
