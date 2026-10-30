"""Run reports against a SQLite file, read-only, with bound parameters only."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .queries import Query


class DatabaseError(Exception):
    """The database file is missing or the query could not run."""


def connect_readonly(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    if not db_path.is_file():
        raise DatabaseError(f"database not found: {db_path} (create the sample one with: report init-db)")
    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA query_only = ON")
    return conn


def run_query(conn: sqlite3.Connection, query: Query, values: dict[str, object]) -> tuple[list[str], list[tuple]]:
    try:
        cursor = conn.execute(query.sql, values)
        rows = cursor.fetchall()
        columns = [d[0] for d in cursor.description or []]
    except sqlite3.Error as exc:
        raise DatabaseError(f"{query.name}: {exc}") from exc
    return columns, rows


def explain_query(conn: sqlite3.Connection, query: Query, values: dict[str, object]) -> list[str]:
    """Return the EXPLAIN QUERY PLAN detail lines, indented by nesting depth."""
    try:
        plan = conn.execute("EXPLAIN QUERY PLAN " + query.sql, values).fetchall()
    except sqlite3.Error as exc:
        raise DatabaseError(f"{query.name}: {exc}") from exc
    depth: dict[int, int] = {0: -1}
    lines: list[str] = []
    for node_id, parent, _unused, detail in plan:
        level = depth.get(parent, -1) + 1
        depth[node_id] = level
        lines.append("  " * level + detail)
    return lines
