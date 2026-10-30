-- Schema for the fictional shop used by sql-report-kit.
-- Money is stored as integer cents. Dates are ISO text: customers.created_at is YYYY-MM-DD,
-- orders.created_at and refunds.refunded_at are YYYY-MM-DD HH:MM:SS.

PRAGMA foreign_keys = ON;

CREATE TABLE customers (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL,
    city        TEXT NOT NULL,
    created_at  TEXT NOT NULL            -- signup date
);

CREATE TABLE products (
    id           INTEGER PRIMARY KEY,
    sku          TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    category     TEXT NOT NULL,
    price_cents  INTEGER NOT NULL CHECK (price_cents >= 0)
);

CREATE TABLE orders (
    id           INTEGER PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES customers(id),
    status       TEXT NOT NULL CHECK (status IN ('completed', 'cancelled', 'pending')),
    created_at   TEXT NOT NULL
);

CREATE TABLE order_items (
    id                INTEGER PRIMARY KEY,
    order_id          INTEGER NOT NULL REFERENCES orders(id),
    product_id        INTEGER NOT NULL REFERENCES products(id),
    quantity          INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_cents  INTEGER NOT NULL CHECK (unit_price_cents >= 0)
);

CREATE TABLE refunds (
    id              INTEGER PRIMARY KEY,
    order_item_id   INTEGER NOT NULL REFERENCES order_items(id),
    amount_cents    INTEGER NOT NULL CHECK (amount_cents > 0),
    refunded_at     TEXT NOT NULL,
    reason          TEXT NOT NULL
);

-- Indexes the reports rely on. idx_orders_created_at is the one the slow/fast query pair is about.
CREATE INDEX idx_orders_created_at       ON orders(created_at);
CREATE INDEX idx_orders_customer_id      ON orders(customer_id);
CREATE INDEX idx_order_items_order_id    ON order_items(order_id);
CREATE INDEX idx_order_items_product_id  ON order_items(product_id);
CREATE INDEX idx_refunds_order_item_id   ON refunds(order_item_id);
