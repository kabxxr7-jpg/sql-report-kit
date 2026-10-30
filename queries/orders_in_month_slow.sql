-- title: Orders in a month (slow version)
-- description: Lists every order placed in a month with its customer and total. This is the "before" of a slow-query pair.
-- description: It wraps orders.created_at in strftime(), so SQLite cannot use the index on that column and scans every order. Compare with orders_in_month_fast using: report explain <name> --param month=2025-03
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
WHERE strftime('%Y-%m', o.created_at) = :month
ORDER BY o.created_at, o.id;
