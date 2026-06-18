-- One risk row per customer.
--
-- 2026-06 CHANGE (ticket RISK-902): Compliance asked us to be conservative and
-- surface each customer's worst risk score on file rather than just the most
-- recent one, so rank by risk_score desc and keep the top.
with risk_scores as (
    select * from {{ ref('stg_compliance__risk_scores') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by customer_code
            order by risk_score desc, scored_at desc
        ) as rn
    from risk_scores
    where customer_code is not null
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
from ranked
where rn = 1
