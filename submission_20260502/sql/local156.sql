-- INTERPRETATION: Compute annual average purchase price per BTC per region (total_dollar / total_qty for BUY txns),
-- exclude first year per region, rank regions within each remaining year by avg price (desc),
-- and calculate pct_change vs previous year (LAG applied before first-year exclusion so 2018 compares to 2017).
-- EXPECTED: 20 rows — 5 regions × 4 years (2018-2021, 2017 excluded as first year for all regions)

WITH base AS (
  SELECT
    bm.region,
    CAST(substr(bt.txn_date, 7, 4) AS INTEGER) AS year,
    SUM(bt.quantity * bp.price) AS total_dollar,
    SUM(bt.quantity) AS total_quantity
  FROM bitcoin_transactions bt
  JOIN bitcoin_members bm ON bt.member_id = bm.member_id
  JOIN bitcoin_prices bp ON bp.market_date = bt.txn_date AND bp.ticker = bt.ticker
  WHERE bt.txn_type = 'BUY' AND bt.ticker = 'BTC'
  GROUP BY bm.region, CAST(substr(bt.txn_date, 7, 4) AS INTEGER)
),
avg_prices AS (
  SELECT
    year,
    region,
    total_dollar / total_quantity AS avg_price,
    MIN(year) OVER (PARTITION BY region) AS first_year
  FROM base
),
with_lag AS (
  SELECT
    year,
    region,
    avg_price,
    first_year,
    LAG(avg_price) OVER (PARTITION BY region ORDER BY year) AS prev_avg_price
  FROM avg_prices
),
filtered AS (
  SELECT year, region, avg_price, prev_avg_price
  FROM with_lag
  WHERE year != first_year
),
ranked AS (
  SELECT
    year,
    region,
    avg_price,
    RANK() OVER (PARTITION BY year ORDER BY avg_price DESC) AS rank,
    CASE
      WHEN prev_avg_price IS NULL THEN NULL
      ELSE (avg_price - prev_avg_price) / prev_avg_price * 100
    END AS pct_change
  FROM filtered
)
SELECT year, region, avg_price, rank, pct_change
FROM ranked
ORDER BY year, rank
