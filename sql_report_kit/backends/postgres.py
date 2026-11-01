"""PostgreSQL through psycopg 3. Read-only twice over: the session default is read-only, and every transaction
starts as BEGIN READ ONLY."""

from __future__ import annotations

from typing import Sequence

from ..dialect import DIALECTS, split_statements
from ..errors import DatabaseError
from .base import Backend
from .target import Target

CONNECT_TIMEOUT_SECONDS = 10


def _driver():
    try:
        import psycopg
    except ImportError:
        raise DatabaseError(
            "PostgreSQL support needs the psycopg package: pip install -r requirements-backends.txt"
        ) from None
    return psycopg


def _message(exc: Exception) -> str:
    diag = getattr(exc, "diag", None)
    primary = getattr(diag, "message_primary", None)
    text = str(exc).strip()
    return primary or (text.splitlines()[0] if text else type(exc).__name__)


class PostgresBackend(Backend):
    engine = "postgres"
    dialect = DIALECTS["postgres"]

    def __init__(self, conn, read_only: bool = True) -> None:
        self.conn = conn
        self.read_only = read_only

    @classmethod
    def open(cls, target: Target, read_only: bool = True) -> "PostgresBackend":
        psycopg = _driver()
        kwargs: dict[str, object] = {
            "dbname": target.database or None,
            "user": target.user or None,
            "password": target.password or None,
            "port": target.port,
            "host": target.option("host") or target.host or None,
            "connect_timeout": CONNECT_TIMEOUT_SECONDS,
            "application_name": "sql-report-kit",
        }
        if target.option("sslmode"):
            kwargs["sslmode"] = target.option("sslmode")
        try:
            conn = psycopg.connect(**{k: v for k, v in kwargs.items() if v is not None})
            conn.read_only = read_only          # every transaction starts as BEGIN READ ONLY
            if read_only:
                with conn.cursor() as cur:
                    for statement in cls.dialect.session_read_only_sql:
                        cur.execute(statement)
                conn.commit()
        except psycopg.Error as exc:
            raise DatabaseError(f"could not connect to {target.describe()}: {_message(exc)}") from None
        return cls(conn, read_only)

    def version(self) -> str:
        _, rows = self._execute("version", "SHOW server_version", {})
        return "PostgreSQL " + rows[0][0]

    def _execute(self, name, sql, params):
        psycopg = _driver()
        try:
            with self.conn.cursor() as cur:
                cur.execute(sql, params)
                columns = [d.name for d in cur.description or []]
                rows = cur.fetchall() if cur.description else []
            return columns, rows
        except psycopg.Error as exc:
            raise DatabaseError(f"{name}: {_message(exc)}") from None
        finally:
            if self.read_only:
                try:
                    self.conn.rollback()           # end the read-only transaction; the next report starts a new one
                except Exception:
                    pass

    def _explain(self, name, sql, params):
        _, rows = self._execute(name, sql, params)
        return [r[0] for r in rows]

    def execute_script(self, script: str) -> None:
        self._require_writer()
        with self.conn.cursor() as cur:
            for statement in split_statements(script):
                cur.execute(statement)

    def insert_many(self, table: str, rows: Sequence[Sequence[object]]) -> None:
        self._require_writer()
        if not rows:
            return
        marks = ",".join(["%s"] * len(rows[0]))
        with self.conn.cursor() as cur:
            cur.executemany(f"INSERT INTO {self.dialect.quote_identifier(table)} VALUES ({marks})", rows)

    def table_names(self) -> list[str]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")
            return [r[0] for r in cur.fetchall()]

    def after_bulk_load(self, tables: Sequence[str]) -> None:
        """Rows were inserted with explicit ids, so move each identity sequence past the largest id.
        Then refresh the planner statistics of those tables, so query plans do not depend on autovacuum timing."""
        with self.conn.cursor() as cur:
            for table in tables:
                q = self.dialect.quote_identifier(table)
                cur.execute(
                    f"SELECT setval(pg_get_serial_sequence('{q}', 'id'), COALESCE((SELECT MAX(id) FROM {q}), 0) + 1, false)"
                )
                cur.execute(f"ANALYZE {q}")

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
