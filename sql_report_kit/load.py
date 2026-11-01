"""Load the fictional dataset (or any INSERT script) into SQLite, PostgreSQL or MariaDB.

The same generated rows go into every engine. SQLite keeps dates as ISO text; PostgreSQL and MariaDB get
real DATE and timestamp values, because that is what their schemas declare.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime

from .backends import Backend
from .generate import TABLES, ROOT, generate_dataset

SCHEMA_FILES = {"sqlite": "schema.sql", "postgres": "schema.postgres.sql", "mariadb": "schema.mariadb.sql"}
# (table, column index) -> how to convert the ISO text for engines that have native date types
DATE_COLUMNS = {("customers", 4): "date", ("orders", 3): "datetime", ("refunds", 3): "datetime"}


def schema_sql(engine: str) -> str:
    return (ROOT / SCHEMA_FILES[engine]).read_text(encoding="utf-8")


def native_rows(engine: str, table: str, rows: list[tuple]) -> list[tuple]:
    if engine == "sqlite":
        return rows
    converted = []
    for row in rows:
        values = list(row)
        for (name, index), kind in DATE_COLUMNS.items():
            if name == table:
                values[index] = date.fromisoformat(values[index]) if kind == "date" else datetime.fromisoformat(values[index])
        converted.append(tuple(values))
    return converted


def existing_tables(backend: Backend) -> list[str]:
    return [t for t in TABLES if t in set(backend.table_names())]


def drop_sample_tables(backend: Backend) -> None:
    """Drop exactly the five tables this kit creates (children first). Nothing else is touched."""
    for table in reversed(TABLES):
        backend.execute_script(f"DROP TABLE IF EXISTS {backend.dialect.quote_identifier(table)}")
    backend.commit()


def create_schema(backend: Backend, replace: bool = False) -> None:
    present = existing_tables(backend)
    if present and not replace:
        raise FileExistsError(f"table(s) {', '.join(present)} already exist (use --force to drop and recreate them)")
    if present:
        drop_sample_tables(backend)
    backend.execute_script(schema_sql(backend.engine))
    backend.commit()


def load_dataset(backend: Backend, dataset: dict[str, list[tuple]], replace: bool = False) -> dict[str, int]:
    """Create the schema and insert every row. Returns the row count of each table."""
    create_schema(backend, replace)
    for table in TABLES:
        backend.insert_many(table, native_rows(backend.engine, table, dataset[table]))
    backend.after_bulk_load(TABLES)
    backend.commit()
    return {table: len(dataset[table]) for table in TABLES}


def load_sample(backend: Backend, seed: int = 42, replace: bool = False) -> dict[str, int]:
    return load_dataset(backend, generate_dataset(seed), replace)


def load_sql_script(backend: Backend, script: str, replace: bool = True) -> None:
    """Create the schema, then run an INSERT script (like tests/tiny_data.sql)."""
    create_schema(backend, replace)
    backend.execute_script(script)
    backend.after_bulk_load(TABLES)
    backend.commit()


def backend_digest(backend: Backend) -> str:
    """SHA-256 over every row of every table in a fixed order, after normalising types.

    Equals generate.content_digest() for a SQLite database, so the three engines can be compared."""
    digest = hashlib.sha256()
    for table in TABLES:
        for row in backend.select(f"SELECT * FROM {backend.dialect.quote_identifier(table)} ORDER BY id"):
            digest.update(repr(row).encode())
    return digest.hexdigest()


__all__ = ["backend_digest", "create_schema", "drop_sample_tables", "load_dataset", "load_sample", "load_sql_script", "schema_sql"]
