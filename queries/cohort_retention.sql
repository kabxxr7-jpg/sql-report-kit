-- title: Cohort retention by signup month
-- description: Customers grouped by signup month. mN_pct is the share of the cohort with at least one completed order N calendar months after the signup month (m0 is the signup month itself).
-- description: Not adjusted for cohorts younger than 3 months: their later columns are low because the time has not passed, not because customers left.
-- chart: cohort_month, m1_pct
WITH cust AS (
    SELECT c.id,
           strftime('%Y-%m', c.created_at) AS cohort_month,
           CAST(strftime('%Y', c.created_at) AS INTEGER) * 12 + CAST(strftime('%m', c.created_at) AS INTEGER) AS cohort_idx
    FROM customers c
),
active AS (
    SELECT DISTINCT o.customer_id,
           CAST(strftime('%Y', o.created_at) AS INTEGER) * 12 + CAST(strftime('%m', o.created_at) AS INTEGER) AS active_idx
    FROM orders o
    WHERE o.status = 'completed'
),
joined AS (
    SELECT c.cohort_month, c.id, a.active_idx - c.cohort_idx AS offset
    FROM cust c
    LEFT JOIN active a ON a.customer_id = c.id
)
SELECT cohort_month,
       COUNT(DISTINCT id) AS customers,
       ROUND(100.0 * COUNT(DISTINCT CASE WHEN offset = 0 THEN id END) / COUNT(DISTINCT id), 1) AS m0_pct,
       ROUND(100.0 * COUNT(DISTINCT CASE WHEN offset = 1 THEN id END) / COUNT(DISTINCT id), 1) AS m1_pct,
       ROUND(100.0 * COUNT(DISTINCT CASE WHEN offset = 2 THEN id END) / COUNT(DISTINCT id), 1) AS m2_pct,
       ROUND(100.0 * COUNT(DISTINCT CASE WHEN offset = 3 THEN id END) / COUNT(DISTINCT id), 1) AS m3_pct
FROM joined
GROUP BY cohort_month
ORDER BY cohort_month;
