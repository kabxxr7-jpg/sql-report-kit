-- A tiny fixed dataset. Every expected value in tests/test_reports.py was worked out by hand from these rows.
-- Money is integer cents.
--
-- Completed orders: o1 (Jan, c1, 2500), o3 (Jan, c2, 1000), o2 (Feb, c1, 2500), o4 (Feb, c3, 5000),
--                   o6 (Mar, c2, 2000), o7 (Mar, c5, 1000), o9 (Apr, c1, 3000)
-- Not completed:    o5 cancelled (c3, Mar), o8 pending (c1, Mar)
-- Refunds paid:     Feb 1000 + 2500, Apr 500, May 1000 (a month with only a refund)

INSERT INTO customers (id, name, email, city, created_at) VALUES
  (1, 'Ann Lee',  'ann@example.com',   'Austin', '2024-01-10'),
  (2, 'Bob Ray',  'bob@example.com',   'Boston', '2024-01-20'),
  (3, 'Cy Day',   'cy@example.com',    'Austin', '2024-02-05'),
  (4, 'Ann Lee',  'ANN@example.com ',  'Austin', '2024-03-01'),
  (5, 'Dee Fox',  'dee@example.com',   'Denver', '2024-03-15'),
  (6, 'dee fox',  'dee.fox@example.com', 'Denver', '2024-03-20');

INSERT INTO products (id, sku, name, category, price_cents) VALUES
  (1, 'SKU-001', 'Widget',    'A', 1000),
  (2, 'SKU-002', 'Gadget',    'A', 2500),
  (3, 'SKU-003', 'Gizmo',     'B', 500),
  (4, 'SKU-004', 'Doohickey', 'B', 4000);

INSERT INTO orders (id, customer_id, status, created_at) VALUES
  (1, 1, 'completed', '2024-01-15 10:00:00'),
  (2, 1, 'completed', '2024-02-10 09:30:00'),
  (3, 2, 'completed', '2024-01-25 12:00:00'),
  (4, 3, 'completed', '2024-02-20 08:00:00'),
  (5, 3, 'cancelled', '2024-03-05 11:00:00'),
  (6, 2, 'completed', '2024-03-02 15:00:00'),
  (7, 5, 'completed', '2024-03-20 10:00:00'),
  (8, 1, 'pending',   '2024-03-25 10:00:00'),
  (9, 1, 'completed', '2024-04-02 10:00:00');

INSERT INTO order_items (id, order_id, product_id, quantity, unit_price_cents) VALUES
  (1,  1, 1, 2, 1000),
  (2,  1, 3, 1,  500),
  (3,  2, 2, 1, 2500),
  (4,  3, 1, 1, 1000),
  (5,  4, 2, 2, 2500),
  (6,  5, 1, 1, 1000),
  (7,  6, 3, 4,  500),
  (8,  7, 1, 1, 1000),
  (9,  8, 2, 1, 2500),
  (10, 9, 1, 3, 1000);

INSERT INTO refunds (id, order_item_id, amount_cents, refunded_at, reason) VALUES
  (1, 1, 1000, '2024-02-03 10:00:00', 'damaged'),
  (2, 5, 2500, '2024-02-25 10:00:00', 'not as described'),
  (3, 7,  500, '2024-04-10 10:00:00', 'changed mind'),
  (4, 8, 1000, '2024-05-02 10:00:00', 'arrived late');
