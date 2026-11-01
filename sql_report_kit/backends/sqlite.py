"""SQLite through the standard library. Read-only twice over: mode=ro on the file and PRAGMA query_only."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Sequence

from ..dialect import DIALECTS
from ..errors import DatabaseError
from .base import Backend


def open_readonly(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    if not db_path.is_file():
        raise DatabaseError(f"database not found: {db_path} (create the sample one with: report init-db)")
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    for statement in DIALECTS["sqlite"].session_read_only_sql:
        conn.execute(statement)
    return conn


class SQLiteBackend(Backend):
    engine = "sqlite"
    dialect = DIALECTS["sqlite"]

    def __init__(self, conn: sqlite3.Connection, read_only: bool = True) -> None:
        self.conn = conn
        self.read_only = read_only

    @classmethod
    def open(cls, path: str | Path, read_only: bool = True) -> "SQLiteBackend":
        if read_only:
            return cls(open_readonly(path), True)
        return cls(sqlite3.connect(path), False)

    def version(self) -> str:
        return "SQLite " + sqlite3.sqlite_version

    def _execute(self, name, sql, params):
        try:
            cursor = self.conn.execute(sql, params)
            rows = cursor.fetchall()
            return [d[0] for d in cursor.description or []], rows
        except sqlite3.Error as exc:
            raise DatabaseError(f"{name}: {exc}") from exc

    def _explain(self, name, sql, params):
        try:
            plan = self.conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            raise DatabaseError(f"{name}: {exc}") from exc
        depth: dict[int, int] = {0: -1}
        lines: list[str] = []
        for node_id, parent, _unused, detail in plan:
            level = depth.get(parent, -1) + 1
            depth[node_id] = level
            lines.append("  " * level + detail)
        return lines

    def execute_script(self, script: str) -> None:
        self._require_writer()
        self.conn.executescript(script)

    def insert_many(self, table: str, rows: Sequence[Sequence[object]]) -> None:
        self._require_writer()
        if not rows:
            return
        marks = ",".join("?" * len(rows[0]))
        self.conn.executemany(f"INSERT INTO {self.dialect.quote_identifier(table)} VALUES ({marks})", rows)

    def table_names(self) -> list[str]:
        cursor = self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
        return [r[0] for r in cursor.fetchall()]

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
