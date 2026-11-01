"""Parameters are values and the session is read-only, on SQLite, PostgreSQL and MariaDB alike.

The write-refusal tests are the important ones: a report file that contains UPDATE, INSERT, DELETE, DROP or CREATE
is run against a real database and must fail, and the data must be exactly as before.
"""

import pytest

from sql_report_kit.backends import connect, parse_target
from sql_report_kit.cli import main
from sql_report_kit.errors import DatabaseError
from sql_report_kit.queries import parse_query
from tests.test_security import PAYLOADS

COUNT_SQL = "SELECT (SELECT COUNT(*) FROM customers), (SELECT COUNT(*) FROM orders), (SELECT COUNT(*) FROM products), (SELECT COUNT(*) FROM refunds)"
EXPECTED_TINY = [(6, 9, 4, 4)]
# one message pattern per engine for "the database itself said no"
REFUSED = {
    "sqlite": r"readonly|read-only|query_only|attempt to write",
    "postgres": r"read-only transaction",
    "mariadb": r"READ ONLY transaction|command denied",
}
WRITES = [
    "UPDATE customers SET name = 'pwned'",
    "INSERT INTO products (id, sku, name, category, price_cents) VALUES (99, 'X', 'X', 'X', 1)",
    "DELETE FROM refunds",
    "DROP TABLE customers",
    "CREATE TABLE evil (x INTEGER)",
    "ALTER TABLE products ADD COLUMN evil INTEGER",
]


def counts(env):
    with env.writer() as w:
        return w.select(COUNT_SQL)


def report_file(tmp_path, sql):
    path = tmp_path / "r.sql"
    path.write_text("-- title: R\n" + sql + ";\n")
    return parse_query(path)


@pytest.mark.parametrize("payload", [p for p in PAYLOADS if "\x00" not in p])
def test_text_parameter_payloads_are_just_unmatched_values(engine_env, er, payload):
    engine_env.db("tiny")
    before = counts(engine_env)
    columns, rows = er("top_customers", city=payload)
    assert rows == [] and columns[0] == "customer_id"
    assert counts(engine_env) == before == EXPECTED_TINY


def test_a_payload_that_looks_like_a_city_does_not_widen_the_result(er):
    assert [r[0] for r in er("top_customers", city="Austin")[1]] == [1, 3]
    assert er("top_customers", city="Austin' OR city LIKE '%")[1] == []


@pytest.mark.parametrize("sql", WRITES, ids=[w.split()[0] + "_" + w.split()[1] for w in WRITES])
def test_a_report_file_that_tries_to_write_is_refused_by_the_database_and_changes_nothing(engine_env, tmp_path, sql):
    engine_env.db("tiny", fresh=True)
    with connect(engine_env.reader_url()) as backend:
        with pytest.raises(DatabaseError, match=f"(?i){REFUSED[engine_env.engine]}"):
            backend.run(report_file(tmp_path, sql), {})
    assert counts(engine_env) == EXPECTED_TINY
    with engine_env.writer() as w:
        assert w.select("SELECT COUNT(*) FROM customers WHERE name = 'pwned'") == [(0,)]
        assert "evil" not in w.table_names()


def test_the_same_statement_does_work_on_a_writer_connection(engine_env):
    """Negative control: the refusals above come from read-only mode, not from a typo or missing privilege."""
    with engine_env.scratch("tiny"):
        engine_env.execute("UPDATE customers SET name = 'renamed' WHERE id = 1")
        with engine_env.writer() as w:
            assert w.select("SELECT name FROM customers WHERE id = 1") == [("renamed",)]


def test_two_statements_in_one_report_are_refused_and_nothing_runs(engine_env, tmp_path):
    engine_env.db("tiny", fresh=True)
    with connect(engine_env.reader_url()) as backend:
        for sql in ("SELECT 1; DROP TABLE customers", "SELECT 1; SELECT 2", "SELECT 1; UPDATE customers SET name = 'x'"):
            with pytest.raises(DatabaseError, match="exactly one SQL statement"):
                backend.run(report_file(tmp_path, sql), {})
    assert counts(engine_env) == EXPECTED_TINY


def test_the_session_reports_itself_read_only(engine_env):
    with connect(engine_env.reader_url()) as backend:
        if engine_env.engine == "sqlite":
            assert backend.select("PRAGMA query_only") == [(1,)]
        elif engine_env.engine == "postgres":
            assert backend.select("SHOW default_transaction_read_only") == [("on",)]
            assert backend.select("SHOW transaction_read_only") == [("on",)]
        else:
            assert backend.select("SELECT @@session.tx_read_only") == [(1,)]


def test_a_report_cannot_switch_the_session_back_to_read_write(engine_env, tmp_path):
    """Even if a statement flips the session default, every report still runs in its own read-only transaction."""
    engine_env.db("tiny", fresh=True)
    with connect(engine_env.reader_url()) as backend:
        flip = {
            "sqlite": "PRAGMA query_only = OFF",
            "postgres": "SET default_transaction_read_only = off",
            "mariadb": "SET SESSION TRANSACTION READ WRITE",
        }[engine_env.engine]
        try:
            backend._execute("flip", flip, {})
        except DatabaseError:
            pass
        if engine_env.engine == "sqlite":
            # the file itself is opened mode=ro, which no pragma can undo
            pass
        with pytest.raises(DatabaseError):
            backend.run(report_file(tmp_path, "DELETE FROM refunds"), {})
    assert counts(engine_env) == EXPECTED_TINY


def test_mariadb_select_only_user_is_refused_by_privileges_as_well(all_envs, tmp_path):
    env = all_envs["mariadb"]
    env.db("tiny", fresh=True)
    with connect(env.reader_url("ro")) as backend:
        assert backend.select("SELECT COUNT(*) FROM customers") == [(6,)]
        backend._execute("flip", "SET SESSION TRANSACTION READ WRITE", {})
        with pytest.raises(DatabaseError, match="denied"):
            backend._execute("w", "DELETE FROM refunds", {})
    with connect(env.reader_url("rw")) as backend:
        with pytest.raises(DatabaseError, match="READ ONLY"):
            backend.run(report_file(tmp_path, "DELETE FROM refunds"), {})
    assert counts(env) == EXPECTED_TINY


def test_injection_through_the_cli_gets_a_header_only_or_a_usage_error(engine_env, capsys):
    url = engine_env.db("tiny", fresh=True)
    assert main(["run", "monthly_revenue", "--db", url, "-p", "from_date=2024-01-01' OR '1'='1"]) == 2
    assert "expected a date" in capsys.readouterr().err
    assert main(["run", "top_customers", "--db", url, "-p", "city='; DROP TABLE orders; --"]) == 0
    assert capsys.readouterr().out.strip() == "customer_id,name,city,orders,spend_usd,refunded_usd,net_usd"
    assert counts(engine_env) == EXPECTED_TINY


@pytest.mark.parametrize("engine", ["postgres", "mariadb"])
def test_a_wrong_database_name_is_a_clean_error_that_hides_the_password(all_envs, capsys, engine):
    url = all_envs[engine].db("tiny")
    target = parse_target(url)
    assert main(["run", "monthly_revenue", "--db", url.replace("/" + target.database, "/no_such_db_here")]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: could not connect") and target.password not in err


def test_a_wrong_password_is_a_clean_error_that_hides_both_passwords(all_envs, capsys):
    """MariaDB checks passwords on every connection. (The local PostgreSQL trusts its unix socket, so it is not tried there.)"""
    url = all_envs["mariadb"].db("tiny")
    target = parse_target(url)
    wrong = "wrong" + target.password[5:]
    assert main(["run", "monthly_revenue", "--db", url.replace(target.password, wrong)]) == 1
    err = capsys.readouterr().err
    assert "Access denied" in err and target.password not in err and wrong not in err
