-- title: Possible duplicate customers
-- description: Groups of customers who share a normalized email (lowercase, trimmed) or a normalized name plus city. These are candidates to review by hand, not proof of a duplicate.
-- description: customer_ids lists the ids in each group in ascending order. Needs SQLite 3.44 or newer for group_concat(... ORDER BY ...).
SELECT match_type,
       match_key,
       group_concat(id, ',' ORDER BY id) AS customer_ids,
       COUNT(*)                          AS customers
FROM (
    SELECT 'email' AS match_type, lower(trim(email)) AS match_key, id
    FROM customers
    UNION ALL
    SELECT 'name_city', lower(trim(name)) || '|' || lower(trim(city)), id
    FROM customers
)
GROUP BY match_type, match_key
HAVING COUNT(*) > 1
ORDER BY match_type, match_key;
