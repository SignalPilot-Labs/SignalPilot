-- Customer risk dimension: one row per customer, latest risk band.
select
    customer_code,
    customer_uuid,
    risk_score,
    risk_band,
    model_version,
    pep_flag,
    sanctions_flag,
    adverse_media_flag,
    high_risk_country,
    scored_at
from {{ ref('int_customer_risk') }}
