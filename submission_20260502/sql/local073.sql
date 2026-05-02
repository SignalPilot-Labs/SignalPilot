-- ========== OUTPUT COLUMN SPEC ==========
-- 1. row_id       : sequential row ID from SQLite rowid (1-14)
-- 2. order_id     : order ID from pizza_clean_customer_orders
-- 3. customer_id  : customer ID from pizza_clean_customer_orders
-- 4. pizza_id     : 1 for Meatlovers, 2 for all others
-- 5. ingredients  : formatted string "PizzaName: [2x]ing1, [2x]ing2..."
-- ========================================

-- EXPECTED: 14 rows because there are 14 pizza order rows in pizza_clean_customer_orders
-- INTERPRETATION: For each pizza order row, compute final ingredients by:
--   1. Starting with standard recipe toppings
--   2. Removing excluded toppings
--   3. Adding extra toppings
--   Toppings appearing 2+ times (standard + extra) get "2x" prefix and listed first alphabetically

WITH
recipe_toppings AS (
  SELECT pizza_id, CAST(value AS INTEGER) as topping_id
  FROM pizza_recipes, json_each('[' || REPLACE(toppings, ', ', ',') || ']')
),
excluded_toppings AS (
  SELECT o.rowid as row_id, CAST(e.value AS INTEGER) as topping_id
  FROM pizza_clean_customer_orders o, json_each('[' || REPLACE(COALESCE(o.exclusions, ''), ' ', '') || ']') e
  WHERE o.exclusions IS NOT NULL AND o.exclusions != ''
),
base_toppings AS (
  SELECT o.rowid as row_id, r.topping_id
  FROM pizza_clean_customer_orders o
  JOIN recipe_toppings r ON r.pizza_id = o.pizza_id
  WHERE NOT EXISTS (
    SELECT 1 FROM excluded_toppings ex WHERE ex.row_id = o.rowid AND ex.topping_id = r.topping_id
  )
),
extra_toppings AS (
  SELECT o.rowid as row_id, CAST(e.value AS INTEGER) as topping_id
  FROM pizza_clean_customer_orders o, json_each('[' || REPLACE(COALESCE(o.extras, ''), ' ', '') || ']') e
  WHERE o.extras IS NOT NULL AND o.extras != ''
),
all_toppings AS (
  SELECT row_id, topping_id FROM base_toppings
  UNION ALL
  SELECT row_id, topping_id FROM extra_toppings
),
topping_counts AS (
  SELECT row_id, topping_id, COUNT(*) as cnt
  FROM all_toppings
  GROUP BY row_id, topping_id
),
ingredient_strings AS (
  SELECT
    row_id,
    CASE
      WHEN multi IS NOT NULL AND single IS NOT NULL THEN multi || ', ' || single
      WHEN multi IS NOT NULL THEN multi
      ELSE single
    END as ingredient_list
  FROM (
    SELECT row_id,
      GROUP_CONCAT(CASE WHEN cnt > 1 THEN '2x ' || topping_name END, ', ') as multi,
      GROUP_CONCAT(CASE WHEN cnt = 1 THEN topping_name END, ', ') as single
    FROM (
      SELECT tc.row_id, tc.cnt, pt.topping_name
      FROM topping_counts tc
      JOIN pizza_toppings pt ON pt.topping_id = tc.topping_id
      ORDER BY tc.row_id, LOWER(pt.topping_name)
    )
    GROUP BY row_id
  )
)
SELECT
  o.rowid as row_id,
  o.order_id,
  o.customer_id,
  CASE WHEN pn.pizza_name = 'Meatlovers' THEN 1 ELSE 2 END as pizza_id,
  pn.pizza_name || ': ' || i.ingredient_list as ingredients
FROM pizza_clean_customer_orders o
JOIN pizza_names pn ON pn.pizza_id = o.pizza_id
JOIN ingredient_strings i ON i.row_id = o.rowid
ORDER BY o.rowid
