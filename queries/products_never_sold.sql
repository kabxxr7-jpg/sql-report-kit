-- title: Products never sold
-- description: Products with no completed-order sale inside the window. Cancelled and pending orders do not count as a sale.
-- param: from_date | date | 1900-01-01 | First day to include (YYYY-MM-DD)
-- param: to_date | date | 2999-12-31 | Last day to include (YYYY-MM-DD)
SELECT p.sku,
       p.name,
       p.category,
       p.price_cents
FROM products p
WHERE NOT EXISTS (
    SELECT 1
    FROM order_items oi
    JOIN orders o ON o.id = oi.order_id
    WHERE oi.product_id = p.id
      AND o.status = 'completed'
      AND o.created_at >= :from_date
      AND o.created_at <  date(:to_date, '+1 day')
)
ORDER BY p.sku;
