-- title: Top customers by net spend
-- description: Customers ranked by spend on completed orders minus refunds paid to them, inside the date window. Ties are broken by name, then id.
-- description: Only customers with at least one completed order in the window appear. The city filter is bound as a value, never pasted into the SQL.
-- param: limit | int:1..1000 | 10 | How many customers to return
-- param: city | text | | Only customers in this city (leave empty for all cities)
-- param: from_date | date | 1900-01-01 | First day to include (YYYY-MM-DD)
-- param: to_date | date | 2999-12-31 | Last day to include (YYYY-MM-DD)
-- chart: name, net_cents
WITH spend AS (
    SELECT o.customer_id,
           COUNT(DISTINCT o.id)                   AS orders,
           SUM(oi.quantity * oi.unit_price_cents) AS spend_cents
    FROM orders o
    JOIN order_items oi ON oi.order_id = o.id
    WHERE o.status = 'completed'
      AND o.created_at >= {{day_start(:from_date)}}
      AND o.created_at < {{day_after(:to_date)}}
    GROUP BY o.customer_id
),
refunded AS (
    SELECT o.customer_id,
           SUM(r.amount_cents) AS refunded_cents
    FROM refunds r
    JOIN order_items oi ON oi.id = r.order_item_id
    JOIN orders o       ON o.id  = oi.order_id
    WHERE r.refunded_at >= {{day_start(:from_date)}}
      AND r.refunded_at < {{day_after(:to_date)}}
    GROUP BY o.customer_id
)
SELECT c.id    AS customer_id,
       c.name  AS name,
       c.city  AS city,
       s.orders,
       s.spend_cents,
       COALESCE(f.refunded_cents, 0)                     AS refunded_cents,
       s.spend_cents - COALESCE(f.refunded_cents, 0)     AS net_cents
FROM spend s
JOIN customers c ON c.id = s.customer_id
LEFT JOIN refunded f ON f.customer_id = s.customer_id
WHERE (:city = '' OR c.city = :city)
ORDER BY net_cents DESC, c.name ASC, c.id ASC
{{limit(:limit)}};
