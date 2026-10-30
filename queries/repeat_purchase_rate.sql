-- title: Repeat-purchase rate by signup month
-- description: For each signup month, how many customers have placed at least min_orders completed orders (ever), and that share.
-- description: Customers who never ordered count in the denominator. Younger cohorts have had less time to repeat, so compare like with like.
-- param: min_orders | int:2..50 | 2 | Completed orders needed to count as a repeat customer
-- chart: signup_month, repeat_rate_pct
WITH counts AS (
    SELECT c.id,
           strftime('%Y-%m', c.created_at) AS signup_month,
           (SELECT COUNT(*)
              FROM orders o
             WHERE o.customer_id = c.id
               AND o.status = 'completed') AS completed_orders
    FROM customers c
)
SELECT signup_month,
       COUNT(*) AS customers,
       SUM(CASE WHEN completed_orders >= :min_orders THEN 1 ELSE 0 END) AS repeat_customers,
       ROUND(100.0 * SUM(CASE WHEN completed_orders >= :min_orders THEN 1 ELSE 0 END) / COUNT(*), 1) AS repeat_rate_pct
FROM counts
GROUP BY signup_month
ORDER BY signup_month;
