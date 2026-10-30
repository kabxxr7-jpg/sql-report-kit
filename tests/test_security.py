"""Parameters are values, never SQL; and a report cannot change the database even if a file is wrong."""

import sqlite3

import pytest

from sql_report_kit.cli import main
from sql_report_kit.db import DatabaseError, connect_readonly, run_query
from sql_report_kit.queries import parse_query
from tests.conftest import table_counts

PAYLOADS = [
    "Austin' OR '1'='1",
    "'; DROP TABLE customers; --",
    'Austin" OR 1=1 --',
    "Austin') UNION SELECT 1,2,3,4,5,6,7 --",
    "%",        # would match everything if it were a LIKE pattern
    "_",
    "Austin%",
    "Austin\x00",
]


@pytest.mark.parametrize("payload", PAYLOADS)
def test_text_parameter_payloads_are_just_unmatched_values(run, tiny_db, payload):
    before = table_counts(tiny_db)
    columns, rows = run(tiny_db, "top_customers", city=payload)
    assert rows == []                          # no city is literally called that
    assert table_counts(tiny_db) == before      # nothing was dropped or changed
    assert columns[0] == "customer_id"          # the query shape was not altered


def test_a_payload_that_looks_like_a_city_does_not_widen_the_result(run, tiny_db):
    assert [r[0] for r in run(tiny_db, "top_customers", city="Austin")[1]] == [1, 3]
    assert run(tiny_db, "top_customers", city="Austin' OR city LIKE '%")[1] == []


def test_injection_in_a_date_is_refused_with_exit_code_2(tiny_db, capsys):
    code = main(["run", "monthly_revenue", "--db", str(tiny_db), "-p", "from_date=2024-01-01' OR '1'='1"])
    assert code == 2
    assert "expected a date" in capsys.readouterr().err


def test_injection_through_the_cli_text_parameter_returns_header_only(tiny_db, capsys):
    code = main(["run", "top_customers", "--db", str(tiny_db), "-p", "city='; DROP TABLE orders; --"])
    out = capsys.readouterr().out
    assert code == 0
    assert out.strip() == "customer_id,name,city,orders,spend_usd,refunded_usd,net_usd"   # header only, no rows
    assert table_counts(tiny_db)["orders"] == 9


def test_connection_is_read_only(tiny_db):
    conn = connect_readonly(tiny_db)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO products (id, sku, name, category, price_cents) VALUES (99, 'X', 'X', 'X', 1)")
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DROP TABLE customers")
    finally:
        conn.close()
    assert table_counts(tiny_db)["products"] == 4


def test_a_report_file_that_tries_to_write_is_stopped(tiny_db, tmp_path):
    bad = tmp_path / "evil.sql"
    bad.write_text("-- title: Evil\nUPDATE customers SET name = 'pwned';\n")
    conn = connect_readonly(tiny_db)
    try:
        with pytest.raises(DatabaseError):
            run_query(conn, parse_query(bad), {})
    finally:
        conn.close()
    assert sqlite3.connect(tiny_db).execute("SELECT COUNT(*) FROM customers WHERE name = 'pwned'").fetchone()[0] == 0


def test_a_report_file_with_two_statements_is_refused(tiny_db, tmp_path):
    bad = tmp_path / "two.sql"
    bad.write_text("-- title: Two\nSELECT 1; DROP TABLE customers;\n")
    conn = connect_readonly(tiny_db)
    try:
        with pytest.raises(DatabaseError):
            run_query(conn, parse_query(bad), {})
    finally:
        conn.close()
    assert table_counts(tiny_db)["customers"] == 6


def test_missing_database_is_a_clean_error(tmp_path, capsys):
    code = main(["run", "monthly_revenue", "--db", str(tmp_path / "nope.db")])
    assert code == 1
    assert "database not found" in capsys.readouterr().err


def test_read_only_holds_at_both_layers(tiny_db):
    conn = connect_readonly(tiny_db)
    try:
        assert conn.execute("PRAGMA query_only").fetchone() == (1,)          # layer 1: the session refuses writes
        conn.execute("PRAGMA query_only = OFF")                              # even with that switched off ...
        with pytest.raises(sqlite3.OperationalError, match="readonly"):      # ... layer 2: the file is opened mode=ro
            conn.execute("DELETE FROM customers")
    finally:
        conn.close()
    assert table_counts(tiny_db)["customers"] == 6
