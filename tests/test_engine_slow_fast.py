"""The slow query and its index-friendly rewrite, on each engine: same rows, and a different query plan.

The plan text is engine-specific, so each engine has its own assertion. They are checked on the 1086-order sample
(tiny tables would let any planner pick a scan for both)."""

import re

import pytest

from sql_report_kit.backends import connect
from sql_report_kit.params import resolve_params
from sql_report_kit.queries import load_queries
from tests.test_slow_vs_fast import MONTHS

QUERIES = load_queries()


def plan(env, name, month="2025-03"):
    query = QUERIES[name]
    with connect(env.db("sample")) as backend:
        return backend.explain(query, resolve_params(query, {"month": month}))


def test_identical_rows_for_every_month(er):
    non_empty = 0
    for month in MONTHS:
        slow = er("orders_in_month_slow", "sample", month=month)
        fast = er("orders_in_month_fast", "sample", month=month)
        assert slow == fast, month
        non_empty += bool(slow[1])
    assert non_empty >= 15


def test_a_midnight_and_a_last_second_order_land_in_the_right_month(engine_env, er):
    with engine_env.scratch("tiny"):
        engine_env.execute(
            "INSERT INTO orders (id, customer_id, status, created_at) VALUES (100, 1, 'completed', '2024-06-30 23:59:59')",
            "INSERT INTO orders (id, customer_id, status, created_at) VALUES (101, 1, 'completed', '2024-07-01 00:00:00')",
        )
        for name in ("orders_in_month_slow", "orders_in_month_fast"):
            assert [r[0] for r in er(name, month="2024-06")[1]] == [100]
            assert [r[0] for r in er(name, month="2024-07")[1]] == [101]


def test_leap_day_and_year_end_months(engine_env, er):
    with engine_env.scratch("tiny"):
        engine_env.execute(
            "INSERT INTO orders (id, customer_id, status, created_at) VALUES (110, 1, 'completed', '2024-02-29 12:00:00')",
            "INSERT INTO orders (id, customer_id, status, created_at) VALUES (111, 1, 'completed', '2024-12-31 23:59:59')",
            "INSERT INTO orders (id, customer_id, status, created_at) VALUES (112, 1, 'completed', '2025-01-01 00:00:00')",
        )
        for name in ("orders_in_month_slow", "orders_in_month_fast"):
            assert 110 in [r[0] for r in er(name, month="2024-02")[1]]
            assert [r[0] for r in er(name, month="2024-12")[1]] == [111]
            assert [r[0] for r in er(name, month="2025-01")[1]] == [112]


def test_fast_version_searches_the_index_by_range_and_slow_reads_every_order(engine_env):
    fast, slow = plan(engine_env, "orders_in_month_fast"), plan(engine_env, "orders_in_month_slow")
    text_fast, text_slow = "\n".join(fast), "\n".join(slow)
    if engine_env.engine == "sqlite":
        assert "SEARCH o USING INDEX idx_orders_created_at (created_at>? AND created_at<?)" in text_fast
        assert any(line.strip().startswith("SCAN o") for line in slow), slow
        assert "created_at>?" not in text_slow
    elif engine_env.engine == "postgres":
        # an index scan or a bitmap index scan, depending on the planner's statistics; either way on this index, by range
        assert re.search(r"Index Scan (using idx_orders_created_at on orders|on idx_orders_created_at)", text_fast), text_fast
        assert "Index Cond: ((created_at >=" in text_fast
        assert "cost=" not in text_fast                  # EXPLAIN (COSTS OFF): the plan text is stable and readable
        assert "Seq Scan on orders o" in text_slow and "idx_orders_created_at" not in text_slow
        assert "to_char(created_at, 'YYYY-MM'::text)" in text_slow
    else:
        o_fast = next(line for line in fast if line.startswith("o:"))
        o_slow = next(line for line in slow if line.startswith("o:"))
        assert "type=range key=idx_orders_created_at" in o_fast, fast
        assert "type=ALL key=None" in o_slow, slow
