-- title: Orders in a month (index-friendly rewrite)
-- description: Same rows and columns as orders_in_month_slow. The "after" of the pair.
-- description: The month is turned into a half-open date range on the bare column (created_at >= first day AND created_at < first day of next month), so SQLite can search idx_orders_created_at instead of scanning every order.
-- param: month | month | REQUIRED | Month to list, like 2025-03
SELECT o.id          AS order_id,
       o.created_at  AS created_at,
       c.name        AS customer,
       o.status      AS status,
       COALESCE((SELECT SUM(oi.quantity * oi.unit_price_cents)
                   FROM order_items oi
                  WHERE oi.order_id = o.id), 0) AS total_cents
FROM orders o
JOIN customers c ON c.id = o.customer_id
WHERE o.created_at >= date(:month || '-01')
  AND o.created_at <  date(:month || '-01', '+1 month')
ORDER BY o.created_at, o.id;
