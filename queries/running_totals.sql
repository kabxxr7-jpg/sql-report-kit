-- title: Running totals and 3-month average (window functions)
-- description: Monthly net revenue (completed-order sales minus refunds paid out that month), the cumulative net since the first month shown, and the average of the current and previous two months.
-- description: Uses SUM() OVER and AVG() OVER with explicit ROWS frames, so months with no activity at all are simply absent, not zero. Needs SQLite 3.25 or newer.
-- param: from_date | date | 1900-01-01 | First day to include (YYYY-MM-DD)
-- param: to_date | date | 2999-12-31 | Last day to include (YYYY-MM-DD)
-- chart: month, cumulative_net_cents
WITH gross AS (
    SELECT strftime('%Y-%m', o.created_at)        AS month,
           SUM(oi.quantity * oi.unit_price_cents) AS gross_cents
    FROM orders o
    JOIN order_items oi ON oi.order_id = o.id
    WHERE o.status = 'completed'
      AND o.created_at >= :from_date
      AND o.created_at <  date(:to_date, '+1 day')
    GROUP BY month
),
refunded AS (
    SELECT strftime('%Y-%m', r.refunded_at) AS month,
           SUM(r.amount_cents)              AS refunds_cents
    FROM refunds r
    WHERE r.refunded_at >= :from_date
      AND r.refunded_at <  date(:to_date, '+1 day')
    GROUP BY month
),
months AS (
    SELECT month FROM gross
    UNION
    SELECT month FROM refunded
),
monthly AS (
    SELECT m.month,
           COALESCE(g.gross_cents, 0) - COALESCE(f.refunds_cents, 0) AS net_cents
    FROM months m
    LEFT JOIN gross    g ON g.month = m.month
    LEFT JOIN refunded f ON f.month = m.month
)
SELECT month,
       net_cents,
       SUM(net_cents) OVER (ORDER BY month ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cumulative_net_cents,
       CAST(ROUND(AVG(net_cents) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 0) AS INTEGER) AS avg3_net_cents
FROM monthly
ORDER BY month;
