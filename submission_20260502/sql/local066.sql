-- INTERPRETATION: Summarize total quantity of each ingredient (topping) used in
-- delivered pizzas (cancellation IS NULL in runner orders). Join customer orders
-- with runner orders to filter delivered only, then match recipe toppings to
-- each pizza, and count occurrences per ingredient.
-- EXPECTED: 12 rows (one per unique topping across all delivered pizzas)

-- ========== OUTPUT COLUMN SPEC ==========
-- 1. topping_name : name of the ingredient/topping
-- 2. quantity     : total count of times that ingredient was used across all delivered pizzas
-- ========================================

SELECT pt.topping_name, COUNT(*) AS quantity
FROM pizza_clean_customer_orders co
JOIN pizza_clean_runner_orders ro ON co.order_id = ro.order_id
JOIN pizza_recipes pr ON co.pizza_id = pr.pizza_id
JOIN pizza_toppings pt
  ON (',' || REPLACE(pr.toppings, ' ', '') || ',') LIKE ('%,' || pt.topping_id || ',%')
WHERE ro.cancellation IS NULL
GROUP BY pt.topping_name
ORDER BY quantity DESC, pt.topping_name
