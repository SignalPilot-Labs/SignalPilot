-- ============================================================================
-- Domain 4 — FX & Pricing : raw_fx
-- Internal FX engine + pricing/treasury tables. Source system: NALA internal
-- "fx-engine" service (rate ingestion, pricing margins, hedging, P&L).
-- Naming style WITHIN this vendor (internal service) is snake_case + a few
-- legacy camelCase leftovers from an early Node service.
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS raw_fx;

-- ----------------------------------------------------------------------------
-- rate_providers : lookup of upstream rate sources the engine ingests from.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_fx.rate_providers (
    provider_id      integer PRIMARY KEY,
    provider_code    text NOT NULL,         -- e.g. 'OPENEXCHANGE', 'REUTERS'
    provider_name    text,
    tier             text,                  -- 'primary' | 'fallback' | 'reference'
    weight           numeric(5,4),          -- blend weight in the engine
    is_active        boolean,
    created_at       timestamptz
);

-- ----------------------------------------------------------------------------
-- fx_rates : FACT. Hourly mid/bid/ask time series per currency pair.
-- Sizeable but capped (see generator + business-definition doc for the cap).
-- ts stored as text ISO-Z (vendor stored strings) AND ts_epoch_ms (legacy col).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_fx.fx_rates (
    rate_id          bigint PRIMARY KEY,
    base_currency    text NOT NULL,         -- e.g. 'GBP'
    quote_currency   text NOT NULL,         -- e.g. 'KES'
    pair             text,                  -- 'GBP/KES' (denormalized convenience)
    mid_rate         numeric(20,8),
    bid_rate         numeric(20,8),
    ask_rate         numeric(20,8),
    spread_bps       numeric(10,4),         -- (ask-bid)/mid in basis points
    provider_id      integer,               -- -> rate_providers (not FK-enforced)
    ts_iso           text,                  -- '2024-03-01T13:00:00.000Z'
    ts_epoch_ms      bigint,                -- legacy duplicate of ts as epoch ms
    ingested_at      timestamptz,
    is_stale         boolean                -- engine flagged the tick as stale
);

-- ----------------------------------------------------------------------------
-- fx_rate_snapshots : denormalized point-in-time snapshot blob the pricing
-- service caches each hour (whole rate board as jsonb).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_fx.fx_rate_snapshots (
    snapshot_id      bigint PRIMARY KEY,
    snapshot_at      timestamptz,
    base_currency    text,                  -- the board's pivot (usually 'USD')
    rates            jsonb,                 -- {"KES":129.1,"NGN":1551.2,...}
    provider_id      integer,
    rate_count       integer,
    source_label     text                   -- free-text, has legacy values
);

-- ----------------------------------------------------------------------------
-- pricing_margins : the FX margin (markup over mid) applied by tier/segment.
-- SCD-ish: effective_from / effective_to, soft-deletable.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_fx.pricing_margins (
    margin_id        integer PRIMARY KEY,
    send_currency    text,
    receive_currency text,
    customer_segment text,                  -- 'consumer' | 'rafiki' | 'vip'
    margin_bps       numeric(10,4),         -- markup in basis points over mid
    min_margin_bps   numeric(10,4),
    max_margin_bps   numeric(10,4),
    effective_from   date,
    effective_to     date,                  -- nullable = currently active
    is_deleted       boolean,
    deleted_at       timestamptz,
    updated_at       timestamptz
);

-- ----------------------------------------------------------------------------
-- corridor_pricing : per-corridor pricing config (fixed fee + fx margin) the
-- quote service reads. One row per send->receive corridor + method.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_fx.corridor_pricing (
    corridor_pricing_id integer PRIMARY KEY,
    send_currency    text,
    send_country     text,
    receive_currency text,
    receive_country  text,
    payout_method    text,                  -- 'M-PESA','Bank','MTN MoMo',...
    fixed_fee_amount numeric(18,2),
    fixed_fee_ccy    text,
    fx_margin_bps    numeric(10,4),
    promo_active     boolean,
    min_send_amount  numeric(18,2),
    max_send_amount  numeric(18,2),
    "isActive"       boolean,               -- legacy camelCase column kept around
    effective_from   date,
    updated_at       timestamptz
);

-- ----------------------------------------------------------------------------
-- fx_pnl : daily realized/unrealized FX P&L per currency pair (treasury).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_fx.fx_pnl (
    pnl_id           bigint PRIMARY KEY,
    pnl_date         date,
    base_currency    text,
    quote_currency   text,
    volume_usd       numeric(20,2),
    realized_pnl_usd numeric(20,2),
    unrealized_pnl_usd numeric(20,2),
    avg_margin_bps   numeric(10,4),
    notional_local   numeric(24,2),
    notional_ccy     text,
    created_at       timestamptz
);

-- ----------------------------------------------------------------------------
-- fx_hedges : treasury hedge positions (forwards/spots) to manage FX exposure.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_fx.fx_hedges (
    hedge_id         text PRIMARY KEY,      -- uuid
    instrument       text,                  -- 'spot' | 'forward' | 'swap'
    base_currency    text,
    quote_currency   text,
    notional         numeric(24,2),
    notional_ccy     text,
    strike_rate      numeric(20,8),
    counterparty     text,                  -- 'MUFG','Citi','StoneX',...
    trade_date       date,
    value_date       date,                  -- settlement date (forwards)
    status           text,                  -- 'open' | 'settled' | 'cancelled'
    mark_to_market_usd numeric(20,2),
    created_at       timestamptz,
    updated_at       timestamptz
);
