-- MariaDB version of schema.sql (the fictional shop used by sql-report-kit).
-- Money is integer cents. Dates and timestamps use native types here (SQLite keeps ISO text):
-- customers.created_at is a DATE, orders.created_at and refunds.refunded_at are DATETIME.
-- Every table uses the binary collation utf8mb4_bin, so equality and sorting are case-sensitive and in byte
-- order exactly as in SQLite. MariaDB's usual default collation is case-insensitive; see the README.

CREATE TABLE customers (
    id          INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(200) NOT NULL,
    email       VARCHAR(255) NOT NULL,
    city        VARCHAR(100) NOT NULL,
    created_at  DATE NOT NULL            -- signup date
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE products (
    id           INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    sku          VARCHAR(40) NOT NULL UNIQUE,
    name         VARCHAR(200) NOT NULL,
    category     VARCHAR(100) NOT NULL,
    price_cents  INT NOT NULL CHECK (price_cents >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE orders (
    id           INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    customer_id  INT NOT NULL,
    status       VARCHAR(20) NOT NULL CHECK (status IN ('completed', 'cancelled', 'pending')),
    created_at   DATETIME NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE order_items (
    id                INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    order_id          INT NOT NULL,
    product_id        INT NOT NULL,
    quantity          INT NOT NULL CHECK (quantity > 0),
    unit_price_cents  INT NOT NULL CHECK (unit_price_cents >= 0),
    FOREIGN KEY (order_id) REFERENCES orders(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE refunds (
    id              INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    order_item_id   INT NOT NULL,
    amount_cents    INT NOT NULL CHECK (amount_cents > 0),
    refunded_at     DATETIME NOT NULL,
    reason          VARCHAR(100) NOT NULL,
    FOREIGN KEY (order_item_id) REFERENCES order_items(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE INDEX idx_orders_created_at       ON orders(created_at);
CREATE INDEX idx_orders_customer_id      ON orders(customer_id);
CREATE INDEX idx_order_items_order_id    ON order_items(order_id);
CREATE INDEX idx_order_items_product_id  ON order_items(product_id);
CREATE INDEX idx_refunds_order_item_id   ON refunds(order_item_id);
