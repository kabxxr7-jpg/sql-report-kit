"""Database backends: SQLite, PostgreSQL and MariaDB behind one small interface."""

from __future__ import annotations

from .base import Backend
from .sqlite import SQLiteBackend
from .target import Target, parse_target


def connect(db: str, read_only: bool = True) -> Backend:
    """Open `db` (a SQLite path or a postgresql:// or mariadb:// URL). Read-only unless asked otherwise."""
    target = parse_target(db)
    if target.engine == "sqlite":
        return SQLiteBackend.open(target.path, read_only)
    if target.engine == "postgres":
        from .postgres import PostgresBackend

        return PostgresBackend.open(target, read_only)
    from .mariadb import MariaDBBackend

    return MariaDBBackend.open(target, read_only)


__all__ = ["Backend", "SQLiteBackend", "Target", "connect", "parse_target"]
