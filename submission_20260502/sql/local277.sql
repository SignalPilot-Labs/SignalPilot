-- ========== OUTPUT COLUMN SPEC ==========
-- 1. avg_forecasted_annual_sales : average of annual forecasted sales for products 4160 and 7790 in 2018
-- ========================================

-- INTERPRETATION: Using 36 months of monthly_sales data from Jan 2016 (time steps 1-36),
-- compute 2x12 centered moving average (CMA) for time steps 7-30, derive seasonal indices,
-- normalize them, deseasonalize the series, apply weighted least squares regression
-- (weights = time step t), forecast each month of 2018 (t=25-36), sum to annual totals,
-- and return the average across both products.

-- EXPECTED: 1 row (average across 2 products)

WITH base_data AS (
  SELECT
    product_id, mth, qty,
    ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY mth) AS t,
    CAST(strftime('%m', mth) AS INTEGER) AS month_num
  FROM monthly_sales
  WHERE product_id IN (4160, 7790)
    AND mth >= '2016-01-01'
    AND mth < '2019-01-01'
),
-- 2x12 Centered Moving Average:
-- CMA(t) = (0.5*qty(t-6) + qty(t-5) + ... + qty(t+5) + 0.5*qty(t+6)) / 12
-- Valid for t = 7 to 30 (requires 6 months before and after)
cma_calc AS (
  SELECT
    b.product_id, b.t, b.month_num, b.qty,
    (0.5*p6.qty + p5.qty + p4.qty + p3.qty + p2.qty + p1.qty
     + b.qty
     + n1.qty + n2.qty + n3.qty + n4.qty + n5.qty + 0.5*n6.qty) / 12.0 AS cma
  FROM base_data b
  JOIN base_data p6 ON p6.product_id=b.product_id AND p6.t=b.t-6
  JOIN base_data p5 ON p5.product_id=b.product_id AND p5.t=b.t-5
  JOIN base_data p4 ON p4.product_id=b.product_id AND p4.t=b.t-4
  JOIN base_data p3 ON p3.product_id=b.product_id AND p3.t=b.t-3
  JOIN base_data p2 ON p2.product_id=b.product_id AND p2.t=b.t-2
  JOIN base_data p1 ON p1.product_id=b.product_id AND p1.t=b.t-1
  JOIN base_data n1 ON n1.product_id=b.product_id AND n1.t=b.t+1
  JOIN base_data n2 ON n2.product_id=b.product_id AND n2.t=b.t+2
  JOIN base_data n3 ON n3.product_id=b.product_id AND n3.t=b.t+3
  JOIN base_data n4 ON n4.product_id=b.product_id AND n4.t=b.t+4
  JOIN base_data n5 ON n5.product_id=b.product_id AND n5.t=b.t+5
  JOIN base_data n6 ON n6.product_id=b.product_id AND n6.t=b.t+6
  WHERE b.t BETWEEN 7 AND 30
),
-- Average sales-to-CMA ratio by month position → raw seasonal indices
season_ratios AS (
  SELECT
    product_id, month_num,
    AVG(CASE WHEN cma > 0 THEN qty * 1.0 / cma ELSE NULL END) AS avg_ratio
  FROM cma_calc
  GROUP BY product_id, month_num
),
-- Sum of all 12 monthly indices per product (for normalization)
si_sum AS (
  SELECT product_id, SUM(avg_ratio) AS total_ratio
  FROM season_ratios
  GROUP BY product_id
),
-- Normalize so the 12 seasonal indices sum to 12 (average = 1)
normalized_si AS (
  SELECT
    sr.product_id, sr.month_num,
    sr.avg_ratio * 12.0 / ss.total_ratio AS si
  FROM season_ratios sr
  JOIN si_sum ss ON ss.product_id = sr.product_id
),
-- Deseasonalize: D(t) = qty / SI(month_num); NULL when SI=0
deseasonalized AS (
  SELECT
    b.product_id, b.t, b.month_num, b.qty,
    nsi.si,
    CASE WHEN nsi.si > 0 THEN b.qty * 1.0 / nsi.si ELSE NULL END AS d_t
  FROM base_data b
  JOIN normalized_si nsi ON nsi.product_id = b.product_id AND nsi.month_num = b.month_num
),
-- Weighted Least Squares regression (weights w_t = t):
-- slope  b = (Σw · Σ(w·t·D) - Σ(w·t) · Σ(w·D)) / (Σw · Σ(w·t²) - (Σ(w·t))²)
-- intercept a = (Σ(w·D) - b · Σ(w·t)) / Σw
-- With w_t = t: Σw=Σt, Σ(w·t)=Σt², Σ(w·t²)=Σt³, Σ(w·D)=Σ(t·D), Σ(w·t·D)=Σ(t²·D)
regression AS (
  SELECT
    product_id,
    (SUM(t) * SUM(CAST(t AS REAL)*t*d_t) - SUM(CAST(t AS REAL)*t) * SUM(t*d_t)) /
      NULLIF(SUM(t)*SUM(CAST(t AS REAL)*t*t) - SUM(CAST(t AS REAL)*t)*SUM(CAST(t AS REAL)*t), 0) AS slope,
    (SUM(t*d_t) - (SUM(t)*SUM(CAST(t AS REAL)*t*d_t) - SUM(CAST(t AS REAL)*t)*SUM(t*d_t)) /
      NULLIF(SUM(t)*SUM(CAST(t AS REAL)*t*t) - SUM(CAST(t AS REAL)*t)*SUM(CAST(t AS REAL)*t), 0) * SUM(CAST(t AS REAL)*t)) /
      NULLIF(SUM(t), 0) AS intercept
  FROM deseasonalized
  GROUP BY product_id
),
-- Monthly forecast for 2018 (t=25..36): (intercept + slope*t) * SI(month)
forecast_2018 AS (
  SELECT
    d.product_id,
    d.t,
    d.month_num,
    d.si,
    (r.intercept + r.slope * d.t) * d.si AS monthly_forecast
  FROM deseasonalized d
  JOIN regression r ON r.product_id = d.product_id
  WHERE d.t BETWEEN 25 AND 36
),
-- Sum monthly forecasts to get annual forecast per product
annual_forecast AS (
  SELECT
    product_id,
    SUM(monthly_forecast) AS annual_sales_forecast
  FROM forecast_2018
  GROUP BY product_id
)
-- Average annual forecast across both products
SELECT
  AVG(annual_sales_forecast) AS avg_forecasted_annual_sales
FROM annual_forecast
