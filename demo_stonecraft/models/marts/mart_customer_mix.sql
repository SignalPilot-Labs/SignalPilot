-- Revenue breakdown by customer and slab type, excluding internal test orders.

SELECT
    so.customer,
    so.slab_type,
    SUM(so.qty) AS total_qty,
    SUM(so.qty * so.unit_price) AS total_revenue,
    AVG(so.unit_price) AS avg_unit_price,
    COUNT(*) AS order_count
FROM {{ source('stonecraft', 'sales_orders') }} AS so
WHERE so.source != 'internal'
GROUP BY so.customer, so.slab_type
