-- title: Monthly revenue
-- description: Gross sales from completed orders by order month, refunds by the month they were paid out, and net (gross minus refunds).
-- description: A month that only has refunds still appears, with zero gross. Dates are inclusive. Money columns are integer cents.
-- param: from_date | date | 1900-01-01 | First day to include (YYYY-MM-DD)
-- param: to_date | date | 2999-12-31 | Last day to include (YYYY-MM-DD)
-- chart: month, net_cents
WITH gross AS (
    SELECT {{month_key(o.created_at)}}           AS month,
           COUNT(DISTINCT o.id)                      AS orders,
           SUM(oi.quantity * oi.unit_price_cents)    AS gross_cents
    FROM orders o
    JOIN order_items oi ON oi.order_id = o.id
    WHERE o.status = 'completed'
      AND o.created_at >= {{day_start(:from_date)}}
      AND o.created_at < {{day_after(:to_date)}}
    GROUP BY month
),
refunded AS (
    SELECT {{month_key(r.refunded_at)}}  AS month,
           SUM(r.amount_cents)               AS refunds_cents
    FROM refunds r
    WHERE r.refunded_at >= {{day_start(:from_date)}}
      AND r.refunded_at < {{day_after(:to_date)}}
    GROUP BY month
),
months AS (
    SELECT month FROM gross
    UNION
    SELECT month FROM refunded
)
SELECT m.month,
       COALESCE(g.orders, 0)         AS orders,
       COALESCE(g.gross_cents, 0)    AS gross_cents,
       COALESCE(f.refunds_cents, 0)  AS refunds_cents,
       COALESCE(g.gross_cents, 0) - COALESCE(f.refunds_cents, 0) AS net_cents
FROM months m
LEFT JOIN gross    g ON g.month = m.month
LEFT JOIN refunded f ON f.month = m.month
ORDER BY m.month;
