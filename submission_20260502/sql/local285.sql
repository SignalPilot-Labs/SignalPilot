-- Financial performance analysis for veg whsle data (2020-2023)
-- Per category per year: avg/max/min/diff/total wholesale price, total selling price,
-- avg loss rate, total loss, and profit. All values rounded to 2 decimal places.
--
-- NOTE: GROUP BY on veg_txn_df fails due to special characters in column names
-- (parentheses, slashes in: qty_sold(kg), unit_selling_px_rmb/kg, sale/return, discount(%)).
-- Workaround: use a correlated subquery for selling price aggregation.
--
-- EXPECTED: 24 rows (4 years x 6 categories)

WITH whsle_stats AS (
    SELECT
        strftime('%Y', w.whsle_date) AS year,
        c.category_name,
        ROUND(SUM(w."whsle_px_rmb-kg") * 1.0 / COUNT(w."whsle_px_rmb-kg"), 2) AS avg_wholesale_price,
        ROUND(MAX(w."whsle_px_rmb-kg"), 2) AS max_wholesale_price,
        ROUND(MIN(w."whsle_px_rmb-kg"), 2) AS min_wholesale_price,
        ROUND(MAX(w."whsle_px_rmb-kg") - MIN(w."whsle_px_rmb-kg"), 2) AS wholesale_price_diff,
        ROUND(SUM(w."whsle_px_rmb-kg"), 2) AS total_wholesale_price
    FROM veg_whsle_df w
    JOIN veg_cat c ON w.item_code = c.item_code
    WHERE strftime('%Y', w.whsle_date) BETWEEN '2020' AND '2023'
    GROUP BY strftime('%Y', w.whsle_date), c.category_name
),
loss_stats AS (
    SELECT
        c.category_name,
        ROUND(SUM(l."loss_rate_%") * 1.0 / COUNT(l."loss_rate_%"), 2) AS avg_loss_rate
    FROM veg_loss_rate_df l
    JOIN veg_cat c ON l.item_code = c.item_code
    GROUP BY c.category_name
),
combined AS (
    SELECT
        ws.year,
        ws.category_name,
        ws.avg_wholesale_price,
        ws.max_wholesale_price,
        ws.min_wholesale_price,
        ws.wholesale_price_diff,
        ws.total_wholesale_price,
        ls.avg_loss_rate,
        ROUND((
            SELECT SUM(t."qty_sold(kg)" * t."unit_selling_px_rmb/kg")
            FROM veg_txn_df t
            JOIN veg_cat c ON t.item_code = c.item_code
            WHERE strftime('%Y', t.txn_date) = ws.year
              AND c.category_name = ws.category_name
              AND t."sale/return" = 'sale'
        ), 2) AS total_selling_price
    FROM whsle_stats ws
    LEFT JOIN loss_stats ls ON ws.category_name = ls.category_name
)
SELECT
    year,
    category_name,
    avg_wholesale_price,
    max_wholesale_price,
    min_wholesale_price,
    wholesale_price_diff,
    total_wholesale_price,
    total_selling_price,
    avg_loss_rate,
    ROUND(total_selling_price * avg_loss_rate / 100, 2) AS total_loss,
    ROUND(total_selling_price - total_wholesale_price - total_selling_price * avg_loss_rate / 100, 2) AS profit
FROM combined
ORDER BY year, category_name;
