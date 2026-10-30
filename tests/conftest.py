import sqlite3
from pathlib import Path

import pytest

from sql_report_kit.db import connect_readonly, run_query
from sql_report_kit.generate import build_sample_db
from sql_report_kit.params import resolve_params
from sql_report_kit.queries import load_queries

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def queries():
    return load_queries()


@pytest.fixture
def tiny_db(tmp_path):
    """A fresh copy of the tiny fixed dataset."""
    path = tmp_path / "tiny.db"
    conn = sqlite3.connect(path)
    conn.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
    conn.executescript((ROOT / "tests" / "tiny_data.sql").read_text(encoding="utf-8"))
    conn.commit()
    conn.close()
    return path


@pytest.fixture(scope="session")
def sample_db(tmp_path_factory):
    """The generated fictional database, seed 42, built once per test run."""
    path = tmp_path_factory.mktemp("sample") / "sample.db"
    build_sample_db(path, seed=42)
    return path


@pytest.fixture
def run(queries):
    """run(db, "report_name", key=value, ...) -> (columns, rows), through the same path the CLI uses."""

    def _run(db, name, **raw):
        query = queries[name]
        values = resolve_params(query, {k: str(v) for k, v in raw.items()})
        conn = connect_readonly(db)
        try:
            return run_query(conn, query, values)
        finally:
            conn.close()

    return _run


def table_counts(db) -> dict[str, int]:
    conn = sqlite3.connect(db)
    try:
        return {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # fixed table names, test helper only
            for t in ("customers", "products", "orders", "order_items", "refunds")
        }
    finally:
        conn.close()
