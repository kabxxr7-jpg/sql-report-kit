"""Build the FICTIONAL sample database: a small online shop, deterministic for a given seed.

Names are random first/last combinations, emails use example.com, cities are generic. None of it is real.
The generator plants things the reports are meant to find: a few duplicate customers, products that never
sell, cancelled and pending orders, partial and full refunds.
"""

from __future__ import annotations

import hashlib
import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schema.sql"

DATA_START = date(2024, 1, 1)
DATA_END = date(2025, 6, 30)

FIRST_NAMES = [
    "Avery", "Blake", "Casey", "Dana", "Eli", "Finley", "Gray", "Harper", "Indy", "Jules",
    "Kai", "Lane", "Morgan", "Noel", "Oak", "Parker", "Quinn", "Reese", "Sage", "Tatum",
    "Uma", "Vale", "Wren", "Xan", "Yael", "Zion", "Arden", "Briar", "Cleo", "Drew",
]
LAST_NAMES = [
    "Alder", "Birch", "Cobb", "Dunn", "Ellis", "Frost", "Grove", "Hale", "Ives", "Joyce",
    "Knox", "Lowe", "Marsh", "Nash", "Oakes", "Pryce", "Quill", "Rowe", "Shaw", "Thorn",
    "Upton", "Voss", "Wick", "Yates", "Zeal", "Ames", "Bell", "Crane", "Dale", "Fenn",
]
CITIES = [
    "Austin", "Boston", "Chicago", "Denver", "Evanston", "Fresno", "Galveston", "Houston", "Irvine", "Jackson",
]
# (name, category, price in cents). The last four are never sold in the sample data.
PRODUCTS = [
    ("Cedar Planter", "Garden", 3400), ("Garden Trowel", "Garden", 1200), ("Seed Starter Kit", "Garden", 2200),
    ("Drip Hose 25ft", "Garden", 1800), ("Pruning Shears", "Garden", 2600), ("Compost Bin", "Garden", 5900),
    ("Cast Iron Skillet", "Kitchen", 4200), ("Bamboo Board", "Kitchen", 2400), ("Chef Knife", "Kitchen", 6800),
    ("Spice Rack", "Kitchen", 3100), ("Tea Kettle", "Kitchen", 3900), ("Mixing Bowls", "Kitchen", 2700),
    ("Desk Lamp", "Office", 3500), ("Notebook 3-pack", "Office", 1100), ("Pen Set", "Office", 1900),
    ("Monitor Stand", "Office", 4800), ("Cable Organizer", "Office", 900), ("Desk Mat", "Office", 2300),
    ("Camp Mug", "Outdoor", 1400), ("Dry Bag 10L", "Outdoor", 2900), ("Headlamp", "Outdoor", 3300),
    ("Trail Blanket", "Outdoor", 4500), ("Folding Stool", "Outdoor", 3700), ("Water Bottle", "Outdoor", 2100),
    ("Dog Leash", "Pet", 1600), ("Pet Bowl Set", "Pet", 2000), ("Cat Scratch Pad", "Pet", 1700),
    ("Travel Pet Mat", "Pet", 2500), ("Brass Bookend", "Office", 5200), ("Linen Apron", "Kitchen", 3600),
]
NEVER_SOLD = 4
REFUND_REASONS = ["damaged", "not as described", "changed mind", "arrived late", "wrong size"]

BASE_CUSTOMERS = 500
PLANTED_DUPLICATES = 12


def _random_time(rng: random.Random) -> str:
    return f"{rng.randrange(8, 22):02d}:{rng.randrange(60):02d}:{rng.randrange(60):02d}"


TABLES = ("customers", "products", "orders", "order_items", "refunds")


def generate_dataset(seed: int = 42) -> dict[str, list[tuple]]:
    """The whole fictional shop as {table: rows}, in schema column order. Pure Python, no database involved.

    Dates and timestamps are ISO text ('2024-01-31', '2024-01-31 10:15:00'); the loader for each engine
    converts them to that engine's native types."""
    rng = random.Random(seed)
    span_days = (DATA_END - DATA_START).days

    customers: list[tuple] = []
    for i in range(1, BASE_CUSTOMERS + 1):
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        signup = DATA_START + timedelta(days=rng.randrange(span_days + 1))
        customers.append(
            (i, f"{first} {last}", f"{first}.{last}{i}@example.com".lower(), rng.choice(CITIES), signup.isoformat())
        )
    # Plant duplicates: half share the email after normalizing, half share name and city only.
    originals = rng.sample(customers, PLANTED_DUPLICATES)
    for n, original in enumerate(originals):
        new_id = BASE_CUSTOMERS + 1 + n
        signup = min(date.fromisoformat(original[4]) + timedelta(days=rng.randrange(1, 40)), DATA_END)
        if n % 2 == 0:
            email = f" {original[2].upper()} "
        else:
            email = original[2].replace("@", ".alt@")
        customers.append((new_id, original[1], email, original[3], signup.isoformat()))

    products = [(i + 1, f"SKU-{i + 1:03d}", name, category, price) for i, (name, category, price) in enumerate(PRODUCTS)]
    sellable = products[: len(products) - NEVER_SOLD]
    order_counts = [0, 1, 2, 3, 4, 5, 6]
    order_weights = [15, 30, 22, 14, 9, 6, 4]

    raw_orders: list[tuple[str, int, str]] = []  # (created_at, customer_id, status)
    for cust in customers:
        signup = date.fromisoformat(cust[4])
        days_left = (DATA_END - signup).days
        for _ in range(rng.choices(order_counts, order_weights)[0]):
            day = signup + timedelta(days=int((rng.random() ** 1.4) * days_left))
            status = rng.choices(["completed", "cancelled", "pending"], [85, 8, 7])[0]
            raw_orders.append((f"{day.isoformat()} {_random_time(rng)}", cust[0], status))
    raw_orders.sort()

    orders: list[tuple] = []
    items: list[tuple] = []
    refunds: list[tuple] = []
    item_id = 0
    refund_id = 0
    for order_id, (created_at, customer_id, status) in enumerate(raw_orders, start=1):
        orders.append((order_id, customer_id, status, created_at))
        n_items = rng.choices([1, 2, 3, 4], [45, 30, 17, 8])[0]
        for product in rng.sample(sellable, n_items):
            item_id += 1
            quantity = rng.choice([1, 1, 1, 2, 2, 3])
            items.append((item_id, order_id, product[0], quantity, product[4]))
            if status == "completed" and rng.random() < 0.04:
                refund_id += 1
                total = quantity * product[4]
                amount = total if rng.random() < 0.6 else max(1, round(total * rng.choice([0.25, 0.5])))
                sold_at = datetime.fromisoformat(created_at)
                refunded_at = min(sold_at + timedelta(days=rng.randrange(1, 31)), datetime(2025, 6, 30, 23, 59, 59))
                refunds.append((refund_id, item_id, amount, refunded_at.strftime("%Y-%m-%d %H:%M:%S"), rng.choice(REFUND_REASONS)))

    return {"customers": customers, "products": products, "orders": orders, "order_items": items, "refunds": refunds}


def build_sample_db(path: str | Path, seed: int = 42, force: bool = False) -> dict[str, int]:
    """Create the SQLite database at `path` and return the row count of each table."""
    db_path = Path(path)
    if db_path.exists():
        if not force:
            raise FileExistsError(f"{db_path} already exists (use --force to replace it)")
        db_path.unlink()

    dataset = generate_dataset(seed)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:
            conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?)", dataset["customers"])
            conn.executemany("INSERT INTO products VALUES (?,?,?,?,?)", dataset["products"])
            conn.executemany("INSERT INTO orders VALUES (?,?,?,?)", dataset["orders"])
            conn.executemany("INSERT INTO order_items VALUES (?,?,?,?,?)", dataset["order_items"])
            conn.executemany("INSERT INTO refunds VALUES (?,?,?,?,?)", dataset["refunds"])
        return {table: len(dataset[table]) for table in TABLES}
    finally:
        conn.close()


def content_digest(conn: sqlite3.Connection) -> str:
    """SHA-256 over every row of every table in a fixed order, to compare two databases."""
    statements = (
        "SELECT * FROM customers ORDER BY id",
        "SELECT * FROM products ORDER BY id",
        "SELECT * FROM orders ORDER BY id",
        "SELECT * FROM order_items ORDER BY id",
        "SELECT * FROM refunds ORDER BY id",
    )
    digest = hashlib.sha256()
    for statement in statements:
        for row in conn.execute(statement):
            digest.update(repr(row).encode())
    return digest.hexdigest()
