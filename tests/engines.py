"""Throwaway PostgreSQL and MariaDB databases for the test suite, and a per-engine place to load datasets.

Nothing here touches an existing database or user. For each server the suite makes ONE new database with a
random name (sqlreport_kit_test_<tag><hex>) and dedicated users, and drops them again at the end of the run,
also when tests fail. Every DROP is guarded by a check that the name is one this module generates.

Where the servers are is set by environment variables (defaults suit a local setup):

    SQLREPORT_PG_ADMIN_URL        postgresql://you@/postgres?host=/tmp        a role that may CREATE ROLE / DATABASE
    SQLREPORT_MARIADB_ADMIN_URL   mariadb://you@/?unix_socket=<repo>/.local-db/mariadb/mariadb.sock
    SQLREPORT_MARIADB_HOST/PORT   where test users connect over TCP (default 127.0.0.1 and 3308)
    SQLREPORT_REQUIRE_BACKENDS    postgres,mariadb  -> a missing server fails the run instead of skipping its tests
    SQLREPORT_RUN_TAG             short [a-z0-9] tag put in the names, so a killed run can be cleaned up by tag

Clean up leftovers from a run that was killed:   python -m tests.engines cleanup [--tag TAG]
"""

from __future__ import annotations

import getpass
import os
import re
import secrets
import sys
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

from sql_report_kit.backends import Backend, connect, parse_target
from sql_report_kit.errors import DatabaseError
from sql_report_kit.generate import generate_dataset
from sql_report_kit.load import create_schema, load_dataset, load_sql_script

ROOT = Path(__file__).resolve().parent.parent
ENGINES = ("sqlite", "postgres", "mariadb")
NAME_RE = re.compile(r"^sqlreport_kit_(test|role|rw|ro)_[a-z0-9]{1,40}$")


class ServerUnavailable(Exception):
    """The server for an engine cannot be reached or does not allow creating a test database."""


def _safe(name: str) -> str:
    if not NAME_RE.fullmatch(name):
        raise ValueError(f"refusing to touch {name!r}: not a name this test suite generates")
    return name


def _new_names(tag: str) -> dict[str, str]:
    suffix = tag + secrets.token_hex(4)
    return {
        "db": f"sqlreport_kit_test_{suffix}",
        "role": f"sqlreport_kit_role_{suffix}",
        "rw": f"sqlreport_kit_rw_{suffix}",
        "ro": f"sqlreport_kit_ro_{suffix}",
    }


def required_engines() -> set[str]:
    return {e.strip() for e in os.environ.get("SQLREPORT_REQUIRE_BACKENDS", "").split(",") if e.strip()}


def run_tag() -> str:
    tag = os.environ.get("SQLREPORT_RUN_TAG", "")
    if tag and not re.fullmatch(r"[a-z0-9]{1,20}", tag):
        raise ValueError("SQLREPORT_RUN_TAG must be 1 to 20 characters of a-z and 0-9")
    return tag


# ---------------------------------------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------------------------------------


class PostgresServer:
    engine = "postgres"

    def __init__(self) -> None:
        self.admin_url = os.environ.get("SQLREPORT_PG_ADMIN_URL") or f"postgresql://{getpass.getuser()}@/postgres?host=/tmp"
        self.names: dict[str, str] | None = None
        self.password = secrets.token_hex(16)

    def _admin(self) -> Backend:
        return connect(self.admin_url, read_only=False)

    def start(self) -> None:
        try:
            admin = self._admin()
        except DatabaseError as exc:
            raise ServerUnavailable(f"PostgreSQL admin connection failed: {exc}") from None
        self.names = _new_names(run_tag())
        n = self.names
        try:
            admin.conn.autocommit = True
            with admin.conn.cursor() as cur:
                cur.execute(
                    f"CREATE ROLE {_safe(n['role'])} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '{self.password}'"
                )
                cur.execute(
                    f"CREATE DATABASE {_safe(n['db'])} OWNER {n['role']} TEMPLATE template0 ENCODING 'UTF8' LC_COLLATE 'C'"
                )
        except Exception as exc:
            self.stop()
            raise ServerUnavailable(f"could not create the PostgreSQL test database: {exc}") from None
        finally:
            admin.close()

    def url(self, kind: str = "rw") -> str:
        n = self.names
        t = parse_target(self.admin_url)
        creds = f"{n['role']}:{self.password}@"
        if t.option("host"):
            return f"postgresql://{creds}/{n['db']}?host={quote(t.option('host'), safe='/')}"
        return f"postgresql://{creds}{t.host}:{t.port or 5432}/{n['db']}"

    def stop(self) -> None:
        if not self.names:
            return
        n = self.names
        try:
            admin = self._admin()
        except DatabaseError:
            return
        try:
            admin.conn.autocommit = True
            with admin.conn.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS {_safe(n['db'])} WITH (FORCE)")
                cur.execute(f"DROP ROLE IF EXISTS {_safe(n['role'])}")
        finally:
            admin.close()
            self.names = None


# ---------------------------------------------------------------------------------------------------------
# MariaDB
# ---------------------------------------------------------------------------------------------------------


class MariaDBServer:
    engine = "mariadb"

    def __init__(self) -> None:
        socket = ROOT / ".local-db" / "mariadb" / "mariadb.sock"
        self.admin_url = os.environ.get("SQLREPORT_MARIADB_ADMIN_URL") or (
            f"mariadb://{getpass.getuser()}@/?unix_socket={quote(str(socket), safe='/')}"
        )
        self.host = os.environ.get("SQLREPORT_MARIADB_HOST", "127.0.0.1")
        self.port = int(os.environ.get("SQLREPORT_MARIADB_PORT", "3308"))
        self.names: dict[str, str] | None = None
        self.passwords = {"rw": secrets.token_hex(16), "ro": secrets.token_hex(16)}

    def _admin(self) -> Backend:
        return connect(self.admin_url, read_only=False)

    def start(self) -> None:
        try:
            admin = self._admin()
        except DatabaseError as exc:
            raise ServerUnavailable(f"MariaDB admin connection failed: {exc}") from None
        self.names = _new_names(run_tag())
        n = self.names
        try:
            with admin.conn.cursor() as cur:
                cur.execute(f"CREATE DATABASE {_safe(n['db'])} CHARACTER SET utf8mb4 COLLATE utf8mb4_bin")
                for kind, privilege in (("rw", "ALL PRIVILEGES"), ("ro", "SELECT")):
                    cur.execute(f"CREATE USER '{_safe(n[kind])}'@'%' IDENTIFIED BY '{self.passwords[kind]}'")
                    cur.execute(f"GRANT {privilege} ON {n['db']}.* TO '{n[kind]}'@'%'")
        except Exception as exc:
            self.stop()
            raise ServerUnavailable(f"could not create the MariaDB test database: {exc}") from None
        finally:
            admin.close()

    def url(self, kind: str = "rw") -> str:
        n = self.names
        return f"mariadb://{n[kind]}:{self.passwords[kind]}@{self.host}:{self.port}/{n['db']}"

    def stop(self) -> None:
        if not self.names:
            return
        n = self.names
        try:
            admin = self._admin()
        except DatabaseError:
            return
        try:
            with admin.conn.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS {_safe(n['db'])}")
                for kind in ("rw", "ro"):
                    cur.execute(f"DROP USER IF EXISTS '{_safe(n[kind])}'@'%'")
        finally:
            admin.close()
            self.names = None


class SQLiteServer:
    """SQLite has no server: a 'database' is a file in a temp folder."""

    engine = "sqlite"

    def __init__(self, folder: Path) -> None:
        self.path = folder / "engine.db"

    def start(self) -> None:
        pass

    def url(self, kind: str = "rw") -> str:
        return str(self.path)

    def stop(self) -> None:
        pass


# ---------------------------------------------------------------------------------------------------------
# Loading datasets into whichever engine
# ---------------------------------------------------------------------------------------------------------

_TINY_SQL = (ROOT / "tests" / "tiny_data.sql").read_text(encoding="utf-8")
_SAMPLE = generate_dataset(42)


def cohort_dataset() -> dict[str, list[tuple]]:
    """Customers and orders where each retention column differs, plus month and year boundary cases."""
    customers = [
        (1, "C1", "c1@example.com", "X", "2024-04-10"), (2, "C2", "c2@example.com", "X", "2024-04-11"),
        (3, "C3", "c3@example.com", "X", "2024-04-12"), (4, "C4", "c4@example.com", "X", "2024-04-13"),
        (5, "C5", "c5@example.com", "X", "2024-05-31"), (6, "C6", "c6@example.com", "X", "2024-12-20"),
    ]
    raw = [
        (1, "completed", "2024-04-12 10:00:00"), (1, "completed", "2024-05-03 10:00:00"),
        (1, "completed", "2024-06-20 10:00:00"), (1, "completed", "2024-07-15 10:00:00"),
        (1, "completed", "2024-08-02 10:00:00"),
        (2, "completed", "2024-04-15 10:00:00"), (2, "completed", "2024-05-10 10:00:00"), (2, "completed", "2024-06-05 10:00:00"),
        (3, "completed", "2024-04-20 10:00:00"), (3, "completed", "2024-05-25 10:00:00"),
        (4, "completed", "2024-04-28 10:00:00"), (4, "cancelled", "2024-05-02 10:00:00"),
        (5, "completed", "2024-06-01 00:00:00"),
        (6, "completed", "2025-01-05 10:00:00"),
    ]
    orders = [(i, customer, status, at) for i, (customer, status, at) in enumerate(raw, start=1)]
    return {"customers": customers, "products": [], "orders": orders, "order_items": [], "refunds": []}


class EngineEnv:
    """One engine's database for the test session, plus loading and re-loading of the named datasets."""

    def __init__(self, server) -> None:
        self.server = server
        self.engine = server.engine
        self._loaded: str | None = None

    def writer(self) -> Backend:
        return connect(self.server.url("rw"), read_only=False)

    def reader_url(self, kind: str = "rw") -> str:
        return self.server.url(kind)

    def db(self, dataset: str = "tiny", fresh: bool = False) -> str:
        """Make sure `dataset` ('tiny', 'sample', 'cohort' or 'empty') is loaded; return the URL or path to read it."""
        if self._loaded != dataset or fresh:
            self._load(dataset)
        return self.server.url("rw")

    @contextmanager
    def scratch(self, dataset: str):
        """Load `dataset` fresh for a test that changes it. Statements run with execute() stay visible to db() inside
        the block; on leaving it the next db() call reloads, so other tests never see the changes."""
        self._load(dataset)
        try:
            yield self
        finally:
            self._loaded = None

    def _load(self, dataset: str) -> None:
        if self.engine == "sqlite" and self.server.path.exists():
            self.server.path.unlink()
        with self.writer() as w:
            if dataset == "tiny":
                load_sql_script(w, _TINY_SQL)
            elif dataset == "sample":
                load_dataset(w, _SAMPLE, replace=True)
            elif dataset == "cohort":
                load_dataset(w, cohort_dataset(), replace=True)
            elif dataset == "empty":
                create_schema(w, replace=True)
            else:
                raise ValueError(dataset)
        self._loaded = dataset

    def execute(self, *statements: str) -> None:
        """Run write statements as the test owner (only inside scratch())."""
        with self.writer() as w:
            for statement in statements:
                w.execute_script(statement)
            w.commit()


# ---------------------------------------------------------------------------------------------------------
# Command line: python -m tests.engines cleanup [--tag TAG]
# ---------------------------------------------------------------------------------------------------------


def cleanup(tag: str = "") -> list[str]:
    """Drop leftover databases, roles and users made by a killed run. Only names this module generates match."""
    dropped: list[str] = []
    pg = PostgresServer()
    try:
        admin = pg._admin()
    except DatabaseError:
        admin = None
    if admin:
        try:
            admin.conn.autocommit = True
            with admin.conn.cursor() as cur:
                cur.execute("SELECT datname FROM pg_database WHERE datname LIKE 'sqlreport\\_kit\\_test\\_%'")
                for (name,) in cur.fetchall():
                    if tag in name and NAME_RE.fullmatch(name):
                        cur.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
                        dropped.append("postgres database " + name)
                cur.execute("SELECT rolname FROM pg_roles WHERE rolname LIKE 'sqlreport\\_kit\\_role\\_%'")
                for (name,) in cur.fetchall():
                    if tag in name and NAME_RE.fullmatch(name):
                        cur.execute(f"DROP ROLE IF EXISTS {name}")
                        dropped.append("postgres role " + name)
        finally:
            admin.close()
    maria = MariaDBServer()
    try:
        admin = maria._admin()
    except DatabaseError:
        admin = None
    if admin:
        try:
            with admin.conn.cursor() as cur:
                cur.execute("SHOW DATABASES LIKE 'sqlreport\\_kit\\_test\\_%'")
                for (name,) in cur.fetchall():
                    if tag in name and NAME_RE.fullmatch(name):
                        cur.execute(f"DROP DATABASE IF EXISTS {name}")
                        dropped.append("mariadb database " + name)
                cur.execute("SELECT User, Host FROM mysql.user WHERE User LIKE 'sqlreport\\_kit\\_%'")
                for name, host in cur.fetchall():
                    if tag in name and NAME_RE.fullmatch(name):
                        cur.execute(f"DROP USER IF EXISTS '{name}'@'{host}'")
                        dropped.append("mariadb user " + name)
        finally:
            admin.close()
    return dropped


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] != ["cleanup"]:
        sys.exit("usage: python -m tests.engines cleanup [--tag TAG]")
    tag_value = args[2] if len(args) >= 3 and args[1] == "--tag" else ""
    removed = cleanup(tag_value)
    print("\n".join(removed) if removed else "nothing to clean up")
