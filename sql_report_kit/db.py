"""Run reports against SQLite, PostgreSQL or MariaDB, read-only, with bound parameters only.

The SQLite functions keep their original shape (connect_readonly returns a sqlite3 connection); the engine
differences live in dialect.py and the per-engine connection code in backends/.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .backends import Backend, SQLiteBackend, connect, parse_target
from .backends.sqlite import open_readonly
from .errors import DatabaseError
from .queries import Query

__all__ = ["DatabaseError", "connect", "connect_readonly", "explain_query", "run_query"]


def connect_readonly(target: str | Path) -> sqlite3.Connection | Backend:
    """A SQLite file gives a read-only sqlite3 connection; a postgresql:// or mariadb:// URL gives a Backend."""
    text = str(target)
    if parse_target(text).engine == "sqlite":
        return open_readonly(text)
    return connect(text)


def _backend(conn: sqlite3.Connection | Backend) -> Backend:
    return conn if isinstance(conn, Backend) else SQLiteBackend(conn)


def run_query(conn: sqlite3.Connection | Backend, query: Query, values: dict[str, object]) -> tuple[list[str], list[tuple]]:
    return _backend(conn).run(query, values)


def explain_query(conn: sqlite3.Connection | Backend, query: Query, values: dict[str, object]) -> list[str]:
    """Return the engine's query plan, one line per plan node (SQLite lines are indented by nesting depth)."""
    return _backend(conn).explain(query, values)
