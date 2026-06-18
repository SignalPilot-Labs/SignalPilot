-- Latest risk score per customer. The source is_current flag is unreliable
-- (~4% of customers have >1 true), so trust the staging-derived is_latest flag,
-- which is computed via a window over scored_at.
with risk_scores as (
    select * from {{ ref('stg_compliance__risk_scores') }}
)

select
    risk_score_id,
    customer_code,
    customer_uuid,
    risk_score,
    risk_band,
    model_version,
    factors,
    pep_flag,
    sanctions_flag,
    adverse_media_flag,
    high_risk_country,
    is_current_flag,
    is_latest,
    scored_at,
    created_at
from risk_scores
where is_latest
    and customer_code is not null
