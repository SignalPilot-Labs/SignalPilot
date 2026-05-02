-- INTERPRETATION: Among cities with delivered orders, find the 5 cities with the lowest total
-- payment sums, then return the average of those total payments and the average of their
-- total delivered order counts.
-- EXPECTED: 1 row, 2 columns

SELECT AVG(city_total) AS avg_total_payments, AVG(city_orders) AS avg_total_order_count
FROM (
    SELECT olist_customers.customer_city,
           SUM(cust_data.cust_total) AS city_total,
           SUM(cust_data.cust_cnt)   AS city_orders
    FROM olist_customers,
         (WITH pmts AS (
              SELECT order_id, SUM(payment_value) AS order_total
              FROM olist_order_payments
              GROUP BY order_id
          ),
          del_orders AS (
              SELECT order_id, customer_id
              FROM olist_orders
              WHERE order_status = 'delivered'
          )
          SELECT del_orders.customer_id,
                 SUM(pmts.order_total) AS cust_total,
                 COUNT(*)              AS cust_cnt
          FROM del_orders, pmts
          WHERE del_orders.order_id = pmts.order_id
          GROUP BY del_orders.customer_id
         ) cust_data
    WHERE olist_customers.customer_id = cust_data.customer_id
    GROUP BY olist_customers.customer_city
    ORDER BY city_total ASC
    LIMIT 5
) bottom5
