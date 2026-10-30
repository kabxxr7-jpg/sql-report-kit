-- title: Refunds by product
-- description: For every product that had a refund inside the window: units and revenue from completed orders in the same window, refund count and amount, and refunds as a share of revenue.
-- description: A refund for a sale made outside the window shows a revenue of 0 and an empty percentage instead of a divide-by-zero.
-- param: from_date | date | 1900-01-01 | First day to include (YYYY-MM-DD)
-- param: to_date | date | 2999-12-31 | Last day to include (YYYY-MM-DD)
-- chart: sku, refunded_cents
WITH sold AS (
    SELECT oi.product_id,
           SUM(oi.quantity)                       AS units_sold,
           SUM(oi.quantity * oi.unit_price_cents) AS revenue_cents
    FROM order_items oi
    JOIN orders o ON o.id = oi.order_id
    WHERE o.status = 'completed'
      AND o.created_at >= :from_date
      AND o.created_at <  date(:to_date, '+1 day')
    GROUP BY oi.product_id
),
refunded AS (
    SELECT oi.product_id,
           COUNT(*)            AS refund_count,
           SUM(r.amount_cents) AS refunded_cents
    FROM refunds r
    JOIN order_items oi ON oi.id = r.order_item_id
    WHERE r.refunded_at >= :from_date
      AND r.refunded_at <  date(:to_date, '+1 day')
    GROUP BY oi.product_id
)
SELECT p.sku,
       p.name                         AS product,
       COALESCE(s.units_sold, 0)      AS units_sold,
       COALESCE(s.revenue_cents, 0)   AS revenue_cents,
       f.refund_count,
       f.refunded_cents,
       CASE WHEN COALESCE(s.revenue_cents, 0) = 0 THEN NULL
            ELSE ROUND(100.0 * f.refunded_cents / s.revenue_cents, 1) END AS refunded_pct_of_revenue
FROM refunded f
JOIN products p ON p.id = f.product_id
LEFT JOIN sold s ON s.product_id = f.product_id
ORDER BY f.refunded_cents DESC, p.sku ASC;
