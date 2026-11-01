"""What every database backend offers: run a report, explain it, and (for loading sample data) write."""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from ..dialect import CompiledQuery, Dialect, MacroError, split_statements
from ..errors import DatabaseError

if TYPE_CHECKING:
    from ..queries import Query


class Backend:
    engine = "base"
    dialect: Dialect
    read_only: bool = True

    # --- reading ----------------------------------------------------------------------------
    def run(self, query: "Query", values: dict[str, object]) -> tuple[list[str], list[tuple]]:
        """Run one report with bound parameters. Rows come back with normalised Python types."""
        compiled = self._compile(query, values)
        columns, rows = self._execute(query.name, compiled.sql, compiled.params)
        return columns, [self.dialect.normalize_row(tuple(r)) for r in rows]

    def explain(self, query: "Query", values: dict[str, object]) -> list[str]:
        compiled = self._compile(query, values)
        return self._explain(query.name, self.dialect.explain_prefix + compiled.sql, compiled.params)

    def _compile(self, query: "Query", values: dict[str, object]) -> CompiledQuery:
        """Expand macros and bind placeholders. A report is exactly one statement on every engine: SQLite refuses a
        second one itself, PostgreSQL only does when parameters are bound, so this is checked here instead."""
        try:
            compiled = self.dialect.compile(query.sql, values)
        except MacroError as exc:
            raise DatabaseError(f"{query.name}: {exc}") from None
        if len(split_statements(compiled.sql)) != 1:
            raise DatabaseError(f"{query.name}: a report must be exactly one SQL statement")
        return compiled

    def select(self, sql: str) -> list[tuple]:
        """Run a fixed, parameter-free SELECT written by this program (never user text) and normalise the rows."""
        _, rows = self._execute("select", sql, {})
        return [self.dialect.normalize_row(tuple(r)) for r in rows]

    def version(self) -> str:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def _execute(self, name: str, sql: str, params: dict[str, object]) -> tuple[list[str], list[tuple]]:
        raise NotImplementedError

    def _explain(self, name: str, sql: str, params: dict[str, object]) -> list[str]:
        raise NotImplementedError

    # --- writing (only on a connection opened with read_only=False) -------------------------
    def _require_writer(self) -> None:
        if self.read_only:
            raise DatabaseError("this connection is read-only")

    def execute_script(self, script: str) -> None:
        raise NotImplementedError

    def insert_many(self, table: str, rows: Sequence[Sequence[object]]) -> None:
        raise NotImplementedError

    def table_names(self) -> list[str]:
        raise NotImplementedError

    def after_bulk_load(self, tables: Sequence[str]) -> None:
        """Hook for engines that need housekeeping after rows were inserted with explicit ids."""

    def commit(self) -> None:
        raise NotImplementedError

    def __enter__(self) -> "Backend":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
