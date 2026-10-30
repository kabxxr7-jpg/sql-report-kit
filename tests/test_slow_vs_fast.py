"""The slow query and its index-friendly rewrite return identical rows, and SQLite plans them differently."""

import pytest

from sql_report_kit.db import connect_readonly, explain_query
from sql_report_kit.params import resolve_params

MONTHS = [f"2023-{m:02d}" for m in (11, 12)] + [f"2024-{m:02d}" for m in range(1, 13)] + [f"2025-{m:02d}" for m in range(1, 9)]


def plan(queries, db, name, month):
    query = queries[name]
    conn = connect_readonly(db)
    try:
        return explain_query(conn, query, resolve_params(query, {"month": month}))
    finally:
        conn.close()


def test_identical_rows_for_every_month_on_the_generated_database(run, sample_db):
    non_empty = 0
    for month in MONTHS:
        slow = run(sample_db, "orders_in_month_slow", month=month)
        fast = run(sample_db, "orders_in_month_fast", month=month)
        assert slow == fast, month
        non_empty += bool(slow[1])
    assert non_empty >= 15    # the comparison is not vacuous: most months have orders; the edges are empty


def test_identical_rows_on_the_tiny_database_including_month_boundaries(run, tiny_db):
    for month in ("2023-12", "2024-01", "2024-02", "2024-03", "2024-04", "2024-05"):
        assert run(tiny_db, "orders_in_month_slow", month=month) == run(tiny_db, "orders_in_month_fast", month=month)


def test_a_midnight_and_last_second_order_land_in_the_right_month(tiny_db, run):
    import sqlite3

    conn = sqlite3.connect(tiny_db)
    conn.execute("INSERT INTO orders VALUES (100, 1, 'completed', '2024-06-30 23:59:59')")
    conn.execute("INSERT INTO orders VALUES (101, 1, 'completed', '2024-07-01 00:00:00')")
    conn.commit()
    conn.close()
    for name in ("orders_in_month_slow", "orders_in_month_fast"):
        assert [r[0] for r in run(tiny_db, name, month="2024-06")[1]] == [100]
        assert [r[0] for r in run(tiny_db, name, month="2024-07")[1]] == [101]


@pytest.mark.parametrize("db_fixture", ["tiny_db", "sample_db"])
def test_fast_version_searches_the_index_by_range(queries, db_fixture, request):
    db = request.getfixturevalue(db_fixture)
    lines = plan(queries, db, "orders_in_month_fast", "2025-03")
    assert any("SEARCH o USING INDEX idx_orders_created_at (created_at>? AND created_at<?)" in line for line in lines), lines
    assert not any(line.strip().startswith("SCAN o") for line in lines), lines


@pytest.mark.parametrize("db_fixture", ["tiny_db", "sample_db"])
def test_slow_version_has_no_index_range_and_visits_every_order(queries, db_fixture, request):
    db = request.getfixturevalue(db_fixture)
    lines = plan(queries, db, "orders_in_month_slow", "2025-03")
    assert any(line.strip().startswith("SCAN o") for line in lines), lines     # reads every order
    assert not any("created_at>?" in line or "created_at<?" in line for line in lines), lines   # no range on the index


def test_a_date_only_timestamp_belongs_to_its_own_month_in_both_versions(tiny_db, run):
    import sqlite3

    conn = sqlite3.connect(tiny_db)
    conn.execute("INSERT INTO orders VALUES (102, 1, 'completed', '2024-07-01')")   # no time part
    conn.commit()
    conn.close()
    for name in ("orders_in_month_slow", "orders_in_month_fast"):
        assert [r[0] for r in run(tiny_db, name, month="2024-07")[1]] == [102]
        assert run(tiny_db, name, month="2024-06")[1] == []
