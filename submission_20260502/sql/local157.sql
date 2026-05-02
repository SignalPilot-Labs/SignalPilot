-- ========== OUTPUT COLUMN SPEC ==========
-- 1. ticker        : cryptocurrency ticker symbol
-- 2. market_date   : trading date (original DD-MM-YYYY format from DB)
-- 3. volume_numeric: converted numeric volume (K→×1000, M→×1000000, -→0)
-- 4. prev_volume   : most recent prior non-zero volume
-- 5. pct_change    : daily percentage change in trading volume
-- ========================================

-- INTERPRETATION: For each ticker, compute the daily % change in trading volume
-- for Aug 1–10, 2021. Volume strings are converted (K=thousands, M=millions, -=0).
-- The previous day's volume is the most recent prior day with non-zero volume.
-- Results ordered by ticker, then date.

WITH volume_numeric AS (
    SELECT
        ticker,
        market_date,
        substr(market_date, 7, 4) || '-' || substr(market_date, 4, 2) || '-' || substr(market_date, 1, 2) AS market_date_iso,
        CASE
            WHEN volume = '-' THEN 0.0
            WHEN volume LIKE '%K' THEN CAST(REPLACE(volume, 'K', '') AS REAL) * 1000
            WHEN volume LIKE '%M' THEN CAST(REPLACE(volume, 'M', '') AS REAL) * 1000000
            ELSE CAST(volume AS REAL)
        END AS volume_numeric
    FROM bitcoin_prices
),
target AS (
    SELECT *
    FROM volume_numeric
    WHERE market_date_iso BETWEEN '2021-08-01' AND '2021-08-10'
),
with_prev AS (
    SELECT
        t.ticker,
        t.market_date,
        t.market_date_iso,
        t.volume_numeric,
        (SELECT v2.volume_numeric
         FROM volume_numeric v2
         WHERE v2.ticker = t.ticker
           AND v2.market_date_iso < t.market_date_iso
           AND v2.volume_numeric > 0
         ORDER BY v2.market_date_iso DESC
         LIMIT 1) AS prev_volume
    FROM target t
)
SELECT
    ticker,
    market_date,
    volume_numeric,
    prev_volume,
    CASE
        WHEN prev_volume IS NULL THEN NULL
        ELSE (volume_numeric - prev_volume) / prev_volume * 100
    END AS pct_change
FROM with_prev
ORDER BY ticker, market_date_iso
