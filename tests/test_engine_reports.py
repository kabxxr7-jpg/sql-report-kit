"""The hand-computed expectations of tests/test_reports.py, run on SQLite, PostgreSQL and MariaDB.

Each test uses the `er` fixture, so it runs once per engine. Expected rows are written with exact types: a whole
number the database computed with ROUND stays a float (100.0), a count is an int, a timestamp is text.
"""

import pytest

MONTHLY_ALL = [
    ("2024-01", 2, 3500, 0, 3500),
    ("2024-02", 2, 7500, 3500, 4000),
    ("2024-03", 2, 3000, 0, 3000),
    ("2024-04", 1, 3000, 500, 2500),
    ("2024-05", 0, 0, 1000, -1000),
]


def same(rows, expected):
    """Equal values AND equal Python types, so 100 vs 100.0 or Decimal vs int is a failure."""
    assert rows == expected
    assert [[type(v) for v in r] for r in rows] == [[type(v) for v in r] for r in expected]


def test_monthly_revenue_all_time(er):
    columns, rows = er("monthly_revenue")
    assert columns == ["month", "orders", "gross_cents", "refunds_cents", "net_cents"]
    same(rows, MONTHLY_ALL)


def test_monthly_revenue_window_and_inclusive_dates(er):
    same(er("monthly_revenue", from_date="2024-02-01", to_date="2024-03-31")[1],
         [("2024-02", 2, 7500, 3500, 4000), ("2024-03", 2, 3000, 0, 3000)])
    same(er("monthly_revenue", from_date="2024-02-10", to_date="2024-02-10")[1], [("2024-02", 1, 2500, 0, 2500)])
    assert er("monthly_revenue", from_date="2030-01-01")[1] == []


def test_month_end_date_includes_the_last_second_of_that_day(er, engine_env):
    with engine_env.scratch("tiny"):
        engine_env.execute(
            "INSERT INTO orders (id, customer_id, status, created_at) VALUES (50, 1, 'completed', '2024-06-30 23:59:59')",
            "INSERT INTO order_items (id, order_id, product_id, quantity, unit_price_cents) VALUES (50, 50, 1, 1, 1000)",
        )
        same(er("monthly_revenue", from_date="2024-06-30", to_date="2024-06-30")[1], [("2024-06", 1, 1000, 0, 1000)])
        assert er("monthly_revenue", from_date="2024-07-01", to_date="2024-07-31")[1] == []


def test_top_customers_ranking_and_tie_break(er):
    columns, rows = er("top_customers")
    assert columns == ["customer_id", "name", "city", "orders", "spend_cents", "refunded_cents", "net_cents"]
    same(rows, [
        (1, "Ann Lee", "Austin", 3, 8000, 1000, 7000),
        (2, "Bob Ray", "Boston", 2, 3000, 500, 2500),
        (3, "Cy Day", "Austin", 1, 5000, 2500, 2500),
        (5, "Dee Fox", "Denver", 1, 1000, 1000, 0),
    ])


def test_top_customers_limit_city_and_window(er):
    assert [r[0] for r in er("top_customers", limit=1)[1]] == [1]
    assert [r[0] for r in er("top_customers", city="Austin")[1]] == [1, 3]
    assert er("top_customers", city="Nowhere")[1] == []
    assert [(r[0], r[4], r[5], r[6]) for r in er("top_customers", from_date="2024-02-01")[1]] == [
        (1, 5500, 1000, 4500), (3, 5000, 2500, 2500), (2, 2000, 500, 1500), (5, 1000, 1000, 0),
    ]


def test_city_matching_is_case_sensitive_on_every_engine(er):
    assert er("top_customers", city="austin")[1] == []
    assert er("top_customers", city="AUSTIN")[1] == []


def test_repeat_purchase_rate(er):
    columns, rows = er("repeat_purchase_rate")
    assert columns == ["signup_month", "customers", "repeat_customers", "repeat_rate_pct"]
    same(rows, [("2024-01", 2, 2, 100.0), ("2024-02", 1, 0, 0.0), ("2024-03", 3, 0, 0.0)])
    same(er("repeat_purchase_rate", min_orders=3)[1][:1], [("2024-01", 2, 1, 50.0)])


def test_refunds_by_product(er):
    columns, rows = er("refunds_by_product")
    assert columns == ["sku", "product", "units_sold", "revenue_cents", "refund_count", "refunded_cents", "refunded_pct_of_revenue"]
    same(rows, [
        ("SKU-002", "Gadget", 3, 7500, 1, 2500, 33.3),
        ("SKU-001", "Widget", 7, 7000, 2, 2000, 28.6),
        ("SKU-003", "Gizmo", 5, 2500, 1, 500, 20.0),
    ])
    same(er("refunds_by_product", from_date="2024-04-01")[1], [
        ("SKU-001", "Widget", 3, 3000, 1, 1000, 33.3),
        ("SKU-003", "Gizmo", 0, 0, 1, 500, None),
    ])


def test_products_never_sold(er):
    same(er("products_never_sold")[1], [("SKU-004", "Doohickey", "B", 4000)])
    same(er("products_never_sold", from_date="2024-03-01")[1], [("SKU-002", "Gadget", "A", 2500), ("SKU-004", "Doohickey", "B", 4000)])


def test_cohort_retention(er):
    columns, rows = er("cohort_retention")
    assert columns == ["cohort_month", "customers", "m0_pct", "m1_pct", "m2_pct", "m3_pct"]
    same(rows, [
        ("2024-01", 2, 100.0, 50.0, 50.0, 50.0),
        ("2024-02", 1, 100.0, 0.0, 0.0, 0.0),
        ("2024-03", 3, 33.3, 0.0, 0.0, 0.0),
    ])


def test_cohort_retention_month_and_year_boundaries(er):
    same(er("cohort_retention", "cohort")[1], [
        ("2024-04", 4, 100.0, 75.0, 50.0, 25.0),
        ("2024-05", 1, 0.0, 100.0, 0.0, 0.0),      # signed up May 31, ordered June 1
        ("2024-12", 1, 0.0, 100.0, 0.0, 0.0),      # December to January
    ])


def test_running_totals_window_functions(er):
    columns, rows = er("running_totals")
    assert columns == ["month", "net_cents", "cumulative_net_cents", "avg3_net_cents"]
    same(rows, [
        ("2024-01", 3500, 3500, 3500),
        ("2024-02", 4000, 7500, 3750),
        ("2024-03", 3000, 10500, 3500),
        ("2024-04", 2500, 13000, 3167),
        ("2024-05", -1000, 12000, 1500),
    ])
    same(er("running_totals", from_date="2024-03-01")[1],
         [("2024-03", 3000, 3000, 3000), ("2024-04", 2500, 5500, 2750), ("2024-05", -1000, 4500, 1500)])


def test_duplicate_customers(er):
    columns, rows = er("duplicate_customers")
    assert columns == ["match_type", "match_key", "customer_ids", "customers"]
    same(rows, [
        ("email", "ann@example.com", "1,4", 2),
        ("name_city", "ann lee|austin", "1,4", 2),
        ("name_city", "dee fox|denver", "5,6", 2),
    ])


@pytest.mark.parametrize("name", ["orders_in_month_slow", "orders_in_month_fast"])
def test_orders_in_month_both_versions(er, name):
    columns, rows = er(name, month="2024-03")
    assert columns == ["order_id", "created_at", "customer", "status", "total_cents"]
    same(rows, [
        (6, "2024-03-02 15:00:00", "Bob Ray", "completed", 2000),
        (5, "2024-03-05 11:00:00", "Cy Day", "cancelled", 1000),
        (7, "2024-03-20 10:00:00", "Dee Fox", "completed", 1000),
        (8, "2024-03-25 10:00:00", "Ann Lee", "pending", 2500),
    ])
    assert er(name, month="2023-12")[1] == []


@pytest.mark.parametrize("name", [
    "monthly_revenue", "top_customers", "repeat_purchase_rate", "refunds_by_product", "products_never_sold",
    "cohort_retention", "running_totals", "duplicate_customers",
])
def test_every_report_returns_a_header_only_on_an_empty_database(er, name):
    columns, rows = er(name, "empty")
    assert columns and rows == []


def test_a_new_row_without_an_id_gets_one_after_a_bulk_load(engine_env):
    """The identity sequences are moved past the loaded ids, so an INSERT that leaves id out does not collide."""
    from sql_report_kit.backends import connect

    with engine_env.scratch("sample"):
        engine_env.execute("INSERT INTO orders (customer_id, status, created_at) VALUES (1, 'pending', '2025-06-30 12:00:00')")
        with connect(engine_env.db("sample")) as b:
            assert b.select("SELECT MAX(id) FROM orders") == [(1087,)]
