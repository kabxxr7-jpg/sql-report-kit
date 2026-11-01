"""The command line and the sample-data loader on each engine."""

import re
import sqlite3

import pytest

from sql_report_kit.backends import connect, parse_target
from sql_report_kit.cli import main
from sql_report_kit.generate import build_sample_db, content_digest
from sql_report_kit.load import backend_digest, drop_sample_tables


def cli(capsys, *args):
    code = main(list(args))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_run_csv_markdown_and_html_on_every_engine(engine_env, capsys, tmp_path):
    url = engine_env.db("tiny")
    code, out, err = cli(capsys, "run", "monthly_revenue", "--db", url)
    assert code == 0 and out.splitlines()[0] == "month,orders,gross_usd,refunds_usd,net_usd"
    assert "2024-05,0,0.00,10.00,-10.00" in out and "5 rows" in err
    md, html = tmp_path / "r.md", tmp_path / "r.html"
    assert cli(capsys, "run", "monthly_revenue", "--db", url, "-f", "markdown", "-o", str(md))[0] == 0
    assert cli(capsys, "run", "monthly_revenue", "--db", url, "-f", "html", "-o", str(html))[0] == 0
    assert md.read_text().startswith("| month | orders | gross_usd")
    page = html.read_text()
    assert "<svg" in page and "Monthly revenue" in page and "to_date=2999-12-31" in page


def test_parameters_empty_results_and_usage_errors(engine_env, capsys):
    url = engine_env.db("tiny")
    code, out, _ = cli(capsys, "run", "top_customers", "--db", url, "-p", "limit=1", "-p", "city=Austin")
    assert code == 0 and out.splitlines()[1].startswith("1,Ann Lee,Austin,3,80.00,10.00,70.00")
    code, out, err = cli(capsys, "run", "monthly_revenue", "--db", url, "-p", "from_date=2030-01-01")
    assert code == 0 and out == "month,orders,gross_usd,refunds_usd,net_usd\n" and "0 rows" in err
    assert cli(capsys, "run", "orders_in_month_fast", "--db", url)[0] == 2
    assert cli(capsys, "run", "monthly_revenue", "--db", url, "-p", "bogus=1")[0] == 2


def test_explain_prints_a_plan_for_each_engine(engine_env, capsys):
    code, out, _ = cli(capsys, "explain", "orders_in_month_fast", "--db", engine_env.db("sample"), "-p", "month=2024-03")
    assert code == 0 and "idx_orders_created_at" in out


def test_info_names_the_engine_and_never_prints_the_password(engine_env, capsys):
    url = engine_env.db("tiny")
    code, out, _ = cli(capsys, "info", "--db", url)
    assert code == 0
    assert {"sqlite": "SQLite 3.", "postgres": "PostgreSQL 16.", "mariadb": "MariaDB 13."}[engine_env.engine] in out
    password = parse_target(url).password
    assert not password or password not in out


def test_init_db_refuses_to_overwrite_then_force_rebuilds(engine_env, capsys):
    url = engine_env.db("tiny", fresh=True)
    password = parse_target(url).password
    code, out, err = cli(capsys, "init-db", "--db", url)
    assert code == 1 and "already exist" in err or "already exists" in err
    code, out, err = cli(capsys, "init-db", "--db", url, "--force")
    assert code == 0 and "customers 512, products 30, orders 1086, order_items 2051, refunds 53" in out
    assert not password or (password not in out and password not in err)
    code, out, _ = cli(capsys, "run", "cohort_retention", "--db", url, "-f", "markdown")
    assert code == 0 and re.search(r"\| 2024-01 \| \d+ \|", out)
    engine_env.db("tiny", fresh=True)               # put the shared test database back


def test_init_db_on_an_empty_database_loads_exactly_the_reference_data(engine_env, capsys, tmp_path):
    url = engine_env.db("tiny", fresh=True)
    if engine_env.engine == "sqlite":
        engine_env.server.path.unlink()               # a SQLite "empty database" is no file at all
    else:
        with engine_env.writer() as w:
            drop_sample_tables(w)
            assert w.table_names() == []
    code, out, _ = cli(capsys, "init-db", "--db", url)
    assert code == 0 and "orders 1086" in out
    with connect(url) as b:
        digest = backend_digest(b)
    build_sample_db(tmp_path / "reference.db", seed=42)
    conn = sqlite3.connect(tmp_path / "reference.db")
    try:
        assert digest == content_digest(conn)
    finally:
        conn.close()
    engine_env.db("tiny", fresh=True)


def test_force_only_touches_the_five_sample_tables_on_servers(engine_env, capsys):
    """On PostgreSQL and MariaDB --force drops the five tables and nothing else. A SQLite file is replaced whole."""
    url = engine_env.db("tiny", fresh=True)
    with engine_env.writer() as w:
        w.execute_script("CREATE TABLE keepme (x INTEGER)")
        w.commit()
    assert cli(capsys, "init-db", "--db", url, "--force")[0] == 0
    with engine_env.writer() as w:
        tables = set(w.table_names())
    if engine_env.engine == "sqlite":
        assert "keepme" not in tables
    else:
        assert "keepme" in tables
        with engine_env.writer() as w:
            w.execute_script("DROP TABLE keepme")
            w.commit()
    engine_env.db("tiny", fresh=True)
