"""Each report checked against values worked out by hand from tests/tiny_data.sql."""

import pytest


def test_monthly_revenue_all_time(run, tiny_db):
    columns, rows = run(tiny_db, "monthly_revenue")
    assert columns == ["month", "orders", "gross_cents", "refunds_cents", "net_cents"]
    assert rows == [
        ("2024-01", 2, 3500, 0, 3500),
        ("2024-02", 2, 7500, 3500, 4000),
        ("2024-03", 2, 3000, 0, 3000),      # cancelled o5 and pending o8 are not revenue
        ("2024-04", 1, 3000, 500, 2500),
        ("2024-05", 0, 0, 1000, -1000),     # a month with only a refund still appears
    ]


def test_monthly_revenue_window(run, tiny_db):
    _, rows = run(tiny_db, "monthly_revenue", from_date="2024-02-01", to_date="2024-03-31")
    assert rows == [("2024-02", 2, 7500, 3500, 4000), ("2024-03", 2, 3000, 0, 3000)]


def test_monthly_revenue_dates_are_inclusive_at_both_ends(run, tiny_db):
    # o2 happened on 2024-02-10 09:30; the Feb 3 refund is before the window, o4 (Feb 20) is after it.
    _, rows = run(tiny_db, "monthly_revenue", from_date="2024-02-10", to_date="2024-02-10")
    assert rows == [("2024-02", 1, 2500, 0, 2500)]


def test_top_customers_ranking_and_tie_break(run, tiny_db):
    columns, rows = run(tiny_db, "top_customers")
    assert columns == ["customer_id", "name", "city", "orders", "spend_cents", "refunded_cents", "net_cents"]
    assert rows == [
        (1, "Ann Lee", "Austin", 3, 8000, 1000, 7000),
        (2, "Bob Ray", "Boston", 2, 3000, 500, 2500),   # ties with Cy Day on 2500; name breaks the tie
        (3, "Cy Day", "Austin", 1, 5000, 2500, 2500),
        (5, "Dee Fox", "Denver", 1, 1000, 1000, 0),
    ]


def test_top_customers_limit_and_city(run, tiny_db):
    assert [r[0] for r in run(tiny_db, "top_customers", limit=1)[1]] == [1]
    assert [r[0] for r in run(tiny_db, "top_customers", city="Austin")[1]] == [1, 3]
    assert run(tiny_db, "top_customers", city="Nowhere")[1] == []


def test_top_customers_window_attributes_refunds_paid_in_the_window(run, tiny_db):
    _, rows = run(tiny_db, "top_customers", from_date="2024-02-01")
    assert [(r[0], r[4], r[5], r[6]) for r in rows] == [
        (1, 5500, 1000, 4500),   # o2 + o9; the Feb 3 refund on a January sale is counted
        (3, 5000, 2500, 2500),
        (2, 2000, 500, 1500),
        (5, 1000, 1000, 0),
    ]


def test_repeat_purchase_rate(run, tiny_db):
    columns, rows = run(tiny_db, "repeat_purchase_rate")
    assert columns == ["signup_month", "customers", "repeat_customers", "repeat_rate_pct"]
    assert rows == [("2024-01", 2, 2, 100.0), ("2024-02", 1, 0, 0.0), ("2024-03", 3, 0, 0.0)]


def test_repeat_purchase_rate_threshold_parameter(run, tiny_db):
    _, rows = run(tiny_db, "repeat_purchase_rate", min_orders=3)
    assert rows[0] == ("2024-01", 2, 1, 50.0)   # only Ann has 3 completed orders


def test_refunds_by_product(run, tiny_db):
    columns, rows = run(tiny_db, "refunds_by_product")
    assert columns == [
        "sku", "product", "units_sold", "revenue_cents", "refund_count", "refunded_cents", "refunded_pct_of_revenue",
    ]
    assert rows == [
        ("SKU-002", "Gadget", 3, 7500, 1, 2500, 33.3),
        ("SKU-001", "Widget", 7, 7000, 2, 2000, 28.6),
        ("SKU-003", "Gizmo", 5, 2500, 1, 500, 20.0),
    ]


def test_refunds_by_product_refund_on_a_sale_outside_the_window_has_no_percentage(run, tiny_db):
    _, rows = run(tiny_db, "refunds_by_product", from_date="2024-04-01")
    assert rows == [
        ("SKU-001", "Widget", 3, 3000, 1, 1000, 33.3),
        ("SKU-003", "Gizmo", 0, 0, 1, 500, None),   # sold earlier, refunded in the window: no divide by zero
    ]


def test_products_never_sold(run, tiny_db):
    assert run(tiny_db, "products_never_sold")[1] == [("SKU-004", "Doohickey", "B", 4000)]
    # From March on only Widget (o7, o9) and Gizmo (o6) sold; cancelled/pending orders do not count.
    assert run(tiny_db, "products_never_sold", from_date="2024-03-01")[1] == [
        ("SKU-002", "Gadget", "A", 2500),
        ("SKU-004", "Doohickey", "B", 4000),
    ]


def test_cohort_retention(run, tiny_db):
    columns, rows = run(tiny_db, "cohort_retention")
    assert columns == ["cohort_month", "customers", "m0_pct", "m1_pct", "m2_pct", "m3_pct"]
    assert rows == [
        ("2024-01", 2, 100.0, 50.0, 50.0, 50.0),
        ("2024-02", 1, 100.0, 0.0, 0.0, 0.0),
        ("2024-03", 3, 33.3, 0.0, 0.0, 0.0),
    ]


def test_running_totals_use_window_functions(run, tiny_db):
    columns, rows = run(tiny_db, "running_totals")
    assert columns == ["month", "net_cents", "cumulative_net_cents", "avg3_net_cents"]
    assert rows == [
        ("2024-01", 3500, 3500, 3500),
        ("2024-02", 4000, 7500, 3750),
        ("2024-03", 3000, 10500, 3500),
        ("2024-04", 2500, 13000, 3167),   # (4000 + 3000 + 2500) / 3 = 3166.67
        ("2024-05", -1000, 12000, 1500),  # (3000 + 2500 - 1000) / 3
    ]


def test_running_totals_restart_at_the_window_start(run, tiny_db):
    _, rows = run(tiny_db, "running_totals", from_date="2024-03-01")
    assert rows == [("2024-03", 3000, 3000, 3000), ("2024-04", 2500, 5500, 2750), ("2024-05", -1000, 4500, 1500)]


def test_duplicate_customers(run, tiny_db):
    columns, rows = run(tiny_db, "duplicate_customers")
    assert columns == ["match_type", "match_key", "customer_ids", "customers"]
    assert rows == [
        ("email", "ann@example.com", "1,4", 2),       # 'ANN@example.com ' normalizes to the same email
        ("name_city", "ann lee|austin", "1,4", 2),
        ("name_city", "dee fox|denver", "5,6", 2),    # 'dee fox' and 'Dee Fox' in Denver
    ]


@pytest.mark.parametrize("name", ["orders_in_month_slow", "orders_in_month_fast"])
def test_orders_in_month_both_versions_give_the_hand_computed_rows(run, tiny_db, name):
    columns, rows = run(tiny_db, name, month="2024-03")
    assert columns == ["order_id", "created_at", "customer", "status", "total_cents"]
    assert rows == [
        (6, "2024-03-02 15:00:00", "Bob Ray", "completed", 2000),
        (5, "2024-03-05 11:00:00", "Cy Day", "cancelled", 1000),
        (7, "2024-03-20 10:00:00", "Dee Fox", "completed", 1000),
        (8, "2024-03-25 10:00:00", "Ann Lee", "pending", 2500),
    ]


@pytest.mark.parametrize("name", [
    "monthly_revenue", "top_customers", "repeat_purchase_rate", "refunds_by_product", "products_never_sold",
    "cohort_retention", "running_totals", "duplicate_customers",
])
def test_every_report_returns_header_only_on_an_empty_database(run, tmp_path, name):
    import sqlite3
    from tests.conftest import ROOT

    empty = tmp_path / "empty.db"
    conn = sqlite3.connect(empty)
    conn.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
    conn.close()
    columns, rows = run(empty, name)
    assert columns and rows == []


def test_empty_window_returns_no_rows(run, tiny_db):
    assert run(tiny_db, "monthly_revenue", from_date="2030-01-01")[1] == []
    assert run(tiny_db, "orders_in_month_fast", month="2023-12")[1] == []


@pytest.fixture
def cohort_db(tmp_path):
    """A dedicated dataset where each retention column has a different value, plus month-boundary cases."""
    import sqlite3
    from tests.conftest import ROOT

    path = tmp_path / "cohort.db"
    conn = sqlite3.connect(path)
    conn.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
    conn.executemany(
        "INSERT INTO customers (id, name, email, city, created_at) VALUES (?,?,?,?,?)",
        [
            (1, "C1", "c1@example.com", "X", "2024-04-10"), (2, "C2", "c2@example.com", "X", "2024-04-11"),
            (3, "C3", "c3@example.com", "X", "2024-04-12"), (4, "C4", "c4@example.com", "X", "2024-04-13"),
            (5, "C5", "c5@example.com", "X", "2024-05-31"),   # last day of the month
            (6, "C6", "c6@example.com", "X", "2024-12-20"),   # year boundary
        ],
    )
    orders = [
        (1, "completed", "2024-04-12 10:00:00"), (1, "completed", "2024-05-03 10:00:00"),
        (1, "completed", "2024-06-20 10:00:00"), (1, "completed", "2024-07-15 10:00:00"),
        (1, "completed", "2024-08-02 10:00:00"),          # offset 4: outside the m0 to m3 columns
        (2, "completed", "2024-04-15 10:00:00"), (2, "completed", "2024-05-10 10:00:00"), (2, "completed", "2024-06-05 10:00:00"),
        (3, "completed", "2024-04-20 10:00:00"), (3, "completed", "2024-05-25 10:00:00"),
        (4, "completed", "2024-04-28 10:00:00"), (4, "cancelled", "2024-05-02 10:00:00"),   # cancelled does not count
        (5, "completed", "2024-06-01 00:00:00"),          # the day after signup, but one month later
        (6, "completed", "2025-01-05 10:00:00"),
    ]
    conn.executemany(
        "INSERT INTO orders (customer_id, status, created_at) VALUES (?,?,?)", orders
    )
    conn.commit()
    conn.close()
    return path


def test_cohort_retention_each_column_counts_its_own_month_offset(run, cohort_db):
    _, rows = run(cohort_db, "cohort_retention")
    assert rows == [
        ("2024-04", 4, 100.0, 75.0, 50.0, 25.0),    # m0..m3 are all different on purpose
        ("2024-05", 1, 0.0, 100.0, 0.0, 0.0),       # signed up May 31, ordered June 1: one month later
        ("2024-12", 1, 0.0, 100.0, 0.0, 0.0),       # December to January crosses the year
    ]
