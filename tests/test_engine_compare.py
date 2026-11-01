"""SQLite, PostgreSQL and MariaDB must return the same thing for the same report on the same data.

The seed-42 shop (512 customers, 1086 orders) is loaded into all three engines; every report is run on each with
several parameter sets and the results must be equal: same columns, same rows, same order, same Python types
(after the backend normalises Decimal, datetime and bool). Then the rendered CSV, Markdown and HTML must match
byte for byte. The last section pins down the places where the engines intentionally differ.
"""

import pytest

from sql_report_kit.backends import connect
from sql_report_kit.errors import DatabaseError
from sql_report_kit.generate import content_digest
from sql_report_kit.load import backend_digest
from sql_report_kit.params import resolve_params
from sql_report_kit.queries import load_queries
from sql_report_kit.render import render
from tests.conftest import run_report

QUERIES = load_queries()
WINDOW = {"from_date": "2024-03-15", "to_date": "2024-09-30"}
MONTHS = [f"2023-{m:02d}" for m in (11, 12)] + [f"2024-{m:02d}" for m in range(1, 13)] + [f"2025-{m:02d}" for m in range(1, 9)]

VARIANTS = {
    "monthly_revenue": [{}, WINDOW, {"from_date": "2025-01-01"}, {"to_date": "2024-01-31"}, {"from_date": "2030-01-01"}],
    "top_customers": [
        {}, {"limit": 25}, {"limit": 1000}, {"city": "Austin"}, {"city": "Boston", "limit": 3, **WINDOW},
        {"city": "Nowhere"}, {"limit": 5, "from_date": "2025-01-01"},
    ],
    "repeat_purchase_rate": [{}, {"min_orders": 3}, {"min_orders": 4}, {"min_orders": 5}, {"min_orders": 50}],
    "refunds_by_product": [{}, WINDOW, {"from_date": "2025-04-01"}],
    "products_never_sold": [{}, WINDOW, {"from_date": "2025-06-01"}, {"to_date": "2024-01-15"}],
    "cohort_retention": [{}],
    "running_totals": [{}, WINDOW, {"from_date": "2025-01-01"}],
    "duplicate_customers": [{}],
    "orders_in_month_slow": [{"month": m} for m in MONTHS],
    "orders_in_month_fast": [{"month": m} for m in MONTHS],
}


def strict(result):
    """(columns, rows, the Python type of every cell) so 100 and 100.0, or an int and a Decimal, do not compare equal."""
    columns, rows = result
    return columns, rows, [[type(v).__name__ for v in row] for row in rows]


def test_every_report_has_variants():
    assert set(VARIANTS) == set(QUERIES)


@pytest.mark.parametrize("name", sorted(VARIANTS))
def test_all_three_engines_return_identical_results_on_the_sample_data(all_envs, name):
    non_empty = 0
    for raw in VARIANTS[name]:
        results = {engine: strict(run_report(env, name, "sample", **raw)) for engine, env in all_envs.items()}
        assert results["postgres"] == results["sqlite"], (name, raw, "postgres differs from sqlite")
        assert results["mariadb"] == results["sqlite"], (name, raw, "mariadb differs from sqlite")
        non_empty += bool(results["sqlite"][1])
    assert non_empty >= 1           # the comparison is not vacuous: at least one variant returned rows


def test_the_comparison_is_not_vacuous_default_results_have_real_row_counts(all_envs):
    expected = {
        "monthly_revenue": 18, "top_customers": 10, "repeat_purchase_rate": 18, "refunds_by_product": 23,
        "products_never_sold": 4, "cohort_retention": 18, "running_totals": 18, "duplicate_customers": 33,
    }
    for name, count in expected.items():
        for engine, env in all_envs.items():
            assert len(run_report(env, name, "sample")[1]) == count, (name, engine)


@pytest.mark.parametrize("name", ["monthly_revenue", "top_customers", "refunds_by_product", "cohort_retention", "running_totals"])
@pytest.mark.parametrize("dataset", ["tiny", "cohort"])
def test_all_three_engines_agree_on_the_small_datasets_too(all_envs, name, dataset):
    results = {engine: strict(run_report(env, name, dataset)) for engine, env in all_envs.items()}
    assert results["postgres"] == results["sqlite"] and results["mariadb"] == results["sqlite"]


@pytest.mark.parametrize("fmt", ["csv", "markdown", "html"])
def test_rendered_output_is_byte_identical_across_engines(all_envs, fmt):
    for name in ("monthly_revenue", "top_customers", "refunds_by_product", "cohort_retention", "duplicate_customers", "orders_in_month_fast"):
        query = QUERIES[name]
        values = resolve_params(query, {"month": "2025-03"} if name.startswith("orders") else {})
        out = {}
        for engine, env in all_envs.items():
            columns, rows = run_report(env, name, "sample", **({"month": "2025-03"} if name.startswith("orders") else {}))
            out[engine] = render(fmt, query, columns, rows, values)
        assert out["postgres"] == out["sqlite"] and out["mariadb"] == out["sqlite"], (name, fmt)


def test_the_loaded_data_is_identical_in_all_three_engines(all_envs):
    digests = {}
    for engine, env in all_envs.items():
        with connect(env.db("sample")) as backend:
            digests[engine] = backend_digest(backend)
    assert len(set(digests.values())) == 1
    # and it is the same digest the original SQLite-only generator test computes
    import sqlite3

    conn = sqlite3.connect(all_envs["sqlite"].db("sample"))
    try:
        assert digests["sqlite"] == content_digest(conn)
    finally:
        conn.close()


def test_row_counts_match_the_documented_sample(all_envs):
    for engine, env in all_envs.items():
        with connect(env.db("sample")) as backend:
            counts = {t: backend.select(f"SELECT COUNT(*) FROM {t}")[0][0] for t in ("customers", "products", "orders", "order_items", "refunds")}
        assert counts == {"customers": 512, "products": 30, "orders": 1086, "order_items": 2051, "refunds": 53}, engine


def test_amounts_beyond_32_bits_are_identical_on_all_engines(all_envs):
    """A line of 3 x $40 million is 12 billion cents. Money columns are BIGINT on the servers, so sums, running totals
    and the rounded 3-month average all agree with SQLite's 64-bit integers."""
    results = {}
    for engine, env in all_envs.items():
        with env.scratch("tiny"):
            env.execute(
                "INSERT INTO orders (id, customer_id, status, created_at) VALUES (60, 1, 'completed', '2024-06-10 10:00:00')",
                "INSERT INTO order_items (id, order_id, product_id, quantity, unit_price_cents) VALUES (60, 60, 1, 3, 4000000000)",
            )
            results[engine] = {n: strict(run_report(env, n, "tiny")) for n in ("monthly_revenue", "running_totals", "top_customers")}
    assert results["postgres"] == results["sqlite"] and results["mariadb"] == results["sqlite"]
    revenue = results["sqlite"]["monthly_revenue"][1]
    assert revenue[-1] == ("2024-06", 1, 12_000_000_000, 0, 12_000_000_000)
    assert results["sqlite"]["running_totals"][1][-1] == ("2024-06", 12_000_000_000, 12_000_000_000 + 12000, 4_000_000_500)


# ---------------------------------------------------------------------------------------------------------------
# Where the engines intentionally differ. Each of these is a fact about the engine, pinned so a change is noticed.
# ---------------------------------------------------------------------------------------------------------------


def test_difference_a_date_only_timestamp_is_text_in_sqlite_and_midnight_elsewhere(engine_env, er):
    """SQLite stores whatever text it is given. PostgreSQL and MariaDB have a real timestamp type, so '2024-07-01'
    becomes 2024-07-01 00:00:00. The order lands in the same month either way; only the displayed value differs."""
    with engine_env.scratch("tiny"):
        engine_env.execute("INSERT INTO orders (id, customer_id, status, created_at) VALUES (102, 1, 'completed', '2024-07-01')")
        for name in ("orders_in_month_slow", "orders_in_month_fast"):
            rows = er(name, month="2024-07")[1]
            assert [r[0] for r in rows] == [102]
            expected = "2024-07-01" if engine_env.engine == "sqlite" else "2024-07-01 00:00:00"
            assert rows[0][1] == expected
            assert er(name, month="2024-06")[1] == []


def test_difference_invalid_dates_cannot_be_stored_in_the_native_types(engine_env):
    """SQLite accepts any text in a date column; PostgreSQL and MariaDB refuse it."""
    statement = "INSERT INTO orders (id, customer_id, status, created_at) VALUES (103, 1, 'completed', 'not a date')"
    with engine_env.scratch("tiny"):
        if engine_env.engine == "sqlite":
            engine_env.execute(statement)
        else:
            with pytest.raises(Exception, match="(?i)(timestamp|datetime|incorrect)"):
                engine_env.execute(statement)


def test_difference_lower_of_non_ascii_letters(engine_env, er):
    """SQLite's lower() only folds ASCII letters, so 'ÉLISE' and 'élise' are not duplicates there. PostgreSQL and MariaDB fold
    Unicode (PostgreSQL only if the database's LC_CTYPE is not 'C')."""
    with engine_env.scratch("tiny"):
        engine_env.execute(
            "INSERT INTO customers (id, name, email, city, created_at) VALUES (21, 'ÉLISE Roy', 'e1@example.com', 'Lyon', '2024-01-01')",
            "INSERT INTO customers (id, name, email, city, created_at) VALUES (22, 'élise roy', 'e2@example.com', 'Lyon', '2024-01-02')",
        )
        keys = {r[1] for r in er("duplicate_customers")[1]}
        if engine_env.engine == "sqlite":
            folds = False
        elif engine_env.engine == "mariadb":
            folds = True
        else:
            from sql_report_kit.backends import connect

            with connect(engine_env.db("tiny")) as b:
                folds = b.select("SELECT datctype FROM pg_database WHERE datname = current_database()")[0][0] not in ("C", "POSIX")
        assert ("élise roy|lyon" in keys) is folds


def test_difference_a_nul_byte_in_a_text_parameter(engine_env, er):
    """PostgreSQL text cannot hold NUL, so the parameter is refused with a clean error; the others just find no city."""
    if engine_env.engine == "postgres":
        with pytest.raises(DatabaseError):
            er("top_customers", city="Austin\x00")
    else:
        assert er("top_customers", city="Austin\x00")[1] == []


def test_difference_mariadbs_usual_default_collation_ignores_case_which_the_schema_pins_away(all_envs):
    """Under utf8mb4_general_ci 'Austin' = 'austin'. The MariaDB schema declares utf8mb4_bin so it behaves like the others."""
    with connect(all_envs["mariadb"].db("tiny")) as b:
        assert b.select("SELECT 'Austin' = 'austin' COLLATE utf8mb4_general_ci, 'Austin' = 'austin' COLLATE utf8mb4_bin") == [(1, 0)]
        assert b.select("SELECT COUNT(*) FROM customers WHERE city = 'austin'") == [(0,)]
    with connect(all_envs["postgres"].db("tiny")) as b:
        assert b.select("SELECT 'Austin' = 'austin'") == [(0,)]
    with connect(all_envs["sqlite"].db("tiny")) as b:
        assert b.select("SELECT 'Austin' = 'austin'") == [(0,)]
