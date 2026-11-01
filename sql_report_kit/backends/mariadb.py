"""MariaDB (and MySQL) through PyMySQL. Every report runs inside START TRANSACTION READ ONLY, on a session that
is also set to read-only by default."""

from __future__ import annotations

from typing import Sequence

from ..dialect import DIALECTS, split_statements
from ..errors import DatabaseError
from .base import Backend
from .target import Target

CONNECT_TIMEOUT_SECONDS = 10
READ_TIMEOUT_SECONDS = 300


def _driver():
    try:
        import pymysql
    except ImportError:
        raise DatabaseError(
            "MariaDB support needs the PyMySQL package: pip install -r requirements-backends.txt"
        ) from None
    return pymysql


def _message(exc: Exception) -> str:
    args = getattr(exc, "args", ())
    return str(args[1]) if len(args) > 1 else str(exc)


class MariaDBBackend(Backend):
    engine = "mariadb"
    dialect = DIALECTS["mariadb"]

    def __init__(self, conn, read_only: bool = True) -> None:
        self.conn = conn
        self.read_only = read_only

    @classmethod
    def open(cls, target: Target, read_only: bool = True) -> "MariaDBBackend":
        pymysql = _driver()
        kwargs: dict[str, object] = {
            "user": target.user or None,
            "password": target.password or None,
            "database": target.database or None,
            "charset": "utf8mb4",
            "autocommit": read_only,        # a reader runs each report in its own READ ONLY transaction; a loader commits explicitly
            "connect_timeout": CONNECT_TIMEOUT_SECONDS,
            "read_timeout": READ_TIMEOUT_SECONDS,
        }
        if target.option("unix_socket"):
            kwargs["unix_socket"] = target.option("unix_socket")
        else:
            kwargs["host"] = target.host or "127.0.0.1"
            kwargs["port"] = target.port or 3306
        try:
            conn = pymysql.connect(**{k: v for k, v in kwargs.items() if v is not None})
        except pymysql.MySQLError as exc:
            raise DatabaseError(f"could not connect to {target.describe()}: {_message(exc)}") from None
        backend = cls(conn, read_only)
        if read_only:
            try:
                with conn.cursor() as cur:
                    for statement in backend.dialect.session_read_only_sql:
                        cur.execute(statement)
            except pymysql.MySQLError as exc:
                conn.close()
                raise DatabaseError(f"could not make the session read-only: {_message(exc)}") from None
        return backend

    def version(self) -> str:
        _, rows = self._execute("version", "SELECT VERSION()", {})
        return "MariaDB " + rows[0][0]

    def _execute(self, name, sql, params):
        pymysql = _driver()
        began = False
        try:
            with self.conn.cursor() as cur:
                if self.read_only:
                    cur.execute(self.dialect.begin_read_only_sql)
                    began = True
                cur.execute(sql, params)
                columns = [d[0] for d in cur.description or []]
                rows = list(cur.fetchall()) if cur.description else []
            return columns, rows
        except pymysql.MySQLError as exc:
            raise DatabaseError(f"{name}: {_message(exc)}") from None
        finally:
            if began:
                try:
                    self.conn.rollback()
                except Exception:
                    pass

    def _explain(self, name, sql, params):
        columns, rows = self._execute(name, sql, params)
        index = {c: i for i, c in enumerate(columns)}
        lines = []
        for row in rows:
            extra = f" ({row[index['Extra']]})" if row[index["Extra"]] else ""
            lines.append(
                f"{row[index['table']]}: type={row[index['type']]} key={row[index['key']]} rows={row[index['rows']]}{extra}"
            )
        return lines

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

    def after_bulk_load(self, tables: Sequence[str]) -> None:
        """Refresh the optimizer statistics of the loaded tables, so query plans do not depend on background timing."""
        with self.conn.cursor() as cur:
            for table in tables:
                cur.execute(f"ANALYZE TABLE {self.dialect.quote_identifier(table)}")
                cur.fetchall()

    def table_names(self) -> list[str]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE()")
            return [r[0] for r in cur.fetchall()]

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
