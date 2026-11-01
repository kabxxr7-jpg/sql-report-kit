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


# ---------------------------------------------------------------------------------------------------------------
# Multi-engine fixtures: the same tests run on SQLite, PostgreSQL and MariaDB. The two servers are started lazily
# (one throwaway database each, dropped at the end of the session; see tests/engines.py). A server that is not
# reachable skips its tests, unless SQLREPORT_REQUIRE_BACKENDS names it, in which case the run fails.
# ---------------------------------------------------------------------------------------------------------------

from tests.engines import (  # noqa: E402
    ENGINES, EngineEnv, MariaDBServer, PostgresServer, ServerUnavailable, SQLiteServer, required_engines,
)


def pytest_report_header(config):
    lines = []
    for server in (PostgresServer(), MariaDBServer()):
        try:
            from sql_report_kit.backends import connect

            with connect(server.admin_url, read_only=False) as admin:
                version = admin.version()
            lines.append(f"{server.engine}: {version}")
        except Exception as exc:  # reachability probe only
            lines.append(f"{server.engine}: not reachable ({type(exc).__name__})")
    lines.append(f"sqlite: {sqlite3.sqlite_version}")
    return lines


@pytest.fixture(scope="session")
def _envs(tmp_path_factory):
    envs: dict[str, EngineEnv | ServerUnavailable] = {}
    folder = tmp_path_factory.mktemp("engines")
    yield envs, folder
    for env in envs.values():
        if isinstance(env, EngineEnv):
            env.server.stop()


def _get_env(engine, store):
    envs, folder = store
    if engine not in envs:
        server = {"sqlite": lambda: SQLiteServer(folder), "postgres": PostgresServer, "mariadb": MariaDBServer}[engine]()
        try:
            server.start()
            envs[engine] = EngineEnv(server)
        except ServerUnavailable as exc:
            envs[engine] = exc
    env = envs[engine]
    if isinstance(env, ServerUnavailable):
        if engine in required_engines():
            pytest.fail(f"{engine} is required (SQLREPORT_REQUIRE_BACKENDS) but unavailable: {env}")
        pytest.skip(f"{engine} not available: {env}")
    return env


@pytest.fixture(params=ENGINES)
def engine_env(request, _envs):
    """The EngineEnv for each engine in turn: tests using it run once on SQLite, PostgreSQL and MariaDB."""
    return _get_env(request.param, _envs)


@pytest.fixture
def all_envs(_envs):
    """All three EngineEnvs together, for tests that compare engines with each other."""
    return {engine: _get_env(engine, _envs) for engine in ENGINES}


def run_report(env, name, dataset="tiny", fresh=False, **raw):
    """Run a report on one engine through the same validation and read-only path the CLI uses."""
    from sql_report_kit.backends import connect

    query = load_queries()[name]
    values = resolve_params(query, {k: str(v) for k, v in raw.items()})
    with connect(env.db(dataset, fresh=fresh)) as backend:
        return backend.run(query, values)


@pytest.fixture
def er(engine_env):
    """er("monthly_revenue", "tiny", from_date="2024-02-01") -> (columns, rows) on the current engine."""

    def _er(name, dataset="tiny", fresh=False, **raw):
        return run_report(engine_env, name, dataset, fresh, **raw)

    return _er
