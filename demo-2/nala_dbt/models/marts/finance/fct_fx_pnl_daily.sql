-- fct_fx_pnl_daily: daily FX profit-and-loss by currency pair.
-- Source (stg_fx__fx_pnl) is already at one row per (date, base, quote); this
-- mart adds a stable surrogate pnl_id passthrough and derived margin %.
-- Grain: one row per (pnl_date, base_currency, quote_currency).
with pnl as (
    select * from {{ ref('stg_fx__fx_pnl') }}
)

select
    pnl_id,
    pnl_date,
    base_currency,
    quote_currency,
    pair,

    volume_usd,
    notional_local,
    notional_ccy,

    realized_pnl_usd,
    unrealized_pnl_usd,
    total_pnl_usd,
    avg_margin_bps,

    -- realized pnl as a fraction of traded volume (guard divide-by-zero)
    case when volume_usd > 0
         then round((realized_pnl_usd / volume_usd) * 10000, 2)
         end                                            as realized_margin_bps,

    created_at
from pnl
