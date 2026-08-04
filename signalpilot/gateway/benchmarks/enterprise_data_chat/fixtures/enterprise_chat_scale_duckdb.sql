-- Deterministic local scale fixture: 100k customers, 2m orders, 200k refunds.
-- DuckDB generates it without shipping customer data or a large checked-in binary.
CREATE TABLE scale_customers AS
SELECT i::BIGINT AS customer_id,
       'Customer ' || i::VARCHAR AS name,
       CASE i % 4
         WHEN 0 THEN 'enterprise'
         WHEN 1 THEN 'growth'
         WHEN 2 THEN 'commercial'
         ELSE 'self_service'
       END AS segment,
       DATE '2018-01-01' + ((i * 17) % 2922)::INTEGER AS created_at
FROM range(1, 100001) AS t(i);

CREATE TABLE scale_orders AS
SELECT i::BIGINT AS order_id,
       (1 + ((i * 7919) % 100000))::BIGINT AS customer_id,
       DATE '2018-01-01' + ((i * 13) % 2922)::INTEGER AS ordered_at,
       (10 + ((i * 37) % 50000))::DECIMAL(12, 2) / 100 AS amount,
       CASE WHEN i % 20 = 0 THEN 'cancelled' ELSE 'completed' END AS status
FROM range(1, 2000001) AS t(i);

CREATE TABLE scale_refunds AS
SELECT i::BIGINT AS refund_id,
       (i * 10)::BIGINT AS order_id,
       (1 + ((i * 11) % 5000))::DECIMAL(12, 2) / 100 AS amount,
       DATE '2018-01-01' + ((i * 19) % 2922)::INTEGER AS refunded_at
FROM range(1, 200001) AS t(i);

CREATE INDEX scale_orders_customer_idx ON scale_orders(customer_id);
CREATE INDEX scale_refunds_order_idx ON scale_refunds(order_id);

-- Certification records these exact logical counts plus the generated DB file size.
SELECT 'scale_customers' AS table_name, COUNT(*) AS row_count FROM scale_customers
UNION ALL
SELECT 'scale_orders', COUNT(*) FROM scale_orders
UNION ALL
SELECT 'scale_refunds', COUNT(*) FROM scale_refunds
ORDER BY table_name;
