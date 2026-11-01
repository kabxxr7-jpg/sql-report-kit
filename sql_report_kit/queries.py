"""Load report definitions from queries/*.sql.

A report file is ONE SQL statement with a documented header made of comment lines:

    -- title: Monthly revenue
    -- description: What the report answers (several description lines are joined).
    -- param: name | type | default | help text        (default REQUIRED means no default)
    -- chart: label_column, value_column               (optional, used by the html output)

Parameters are referenced in the SQL as :name and are always passed as bound values.
Types: text, int (optionally int:MIN..MAX), date (YYYY-MM-DD), month (YYYY-MM).

Where SQLite, PostgreSQL and MariaDB disagree, a file uses a {{macro(...)}} that sql_report_kit/dialect.py
turns into the right SQL for the engine in use. Everything else is plain SQL that all three accept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .dialect import DIALECTS, MACRO_NAMES, MacroError, used_macros

REQUIRED = "REQUIRED"
PLACEHOLDER = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")
KNOWN_TYPES = ("text", "int", "date", "month")


class QueryFileError(Exception):
    """A query file is malformed. This is a bug in the file, not in the user's input."""


@dataclass(frozen=True)
class Param:
    name: str
    type: str
    default: str
    help: str

    @property
    def required(self) -> bool:
        return self.default == REQUIRED


@dataclass(frozen=True)
class Query:
    name: str
    title: str
    description: str
    params: tuple[Param, ...]
    chart: tuple[str, str] | None
    sql: str
    path: Path = field(compare=False, default=Path("."))


def default_queries_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "queries"


def _strip_sql_comments_and_strings(sql: str) -> str:
    """Remove comments and string literals so :names inside them are not mistaken for placeholders."""
    sql = re.sub(r"--[^\n]*", "", sql)
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def parse_query(path: Path) -> Query:
    name = path.stem
    text = path.read_text(encoding="utf-8")
    title = name
    description: list[str] = []
    params: list[Param] = []
    chart: tuple[str, str] | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("--"):
            continue
        body = line[2:].strip()
        key, sep, value = body.partition(":")
        if not sep:
            continue
        key = key.strip().lower()
        value = value.strip()
        if key == "title":
            title = value
        elif key == "description":
            description.append(value)
        elif key == "chart":
            parts = [p.strip() for p in value.split(",")]
            if len(parts) != 2 or not all(parts):
                raise QueryFileError(f"{path.name}: chart must be 'label_column, value_column'")
            chart = (parts[0], parts[1])
        elif key == "param":
            parts = [p.strip() for p in value.split("|")]
            if len(parts) != 4:
                raise QueryFileError(f"{path.name}: param needs 'name | type | default | help'")
            pname, ptype, pdefault, phelp = parts
            if not re.fullmatch(r"[A-Za-z_]\w*", pname):
                raise QueryFileError(f"{path.name}: bad parameter name {pname!r}")
            base_type = ptype.split(":", 1)[0]
            if base_type not in KNOWN_TYPES:
                raise QueryFileError(f"{path.name}: unknown type {ptype!r} for {pname}")
            params.append(Param(pname, ptype, pdefault, phelp))

    declared = {p.name for p in params}
    if len(declared) != len(params):
        raise QueryFileError(f"{path.name}: a parameter is declared twice")
    used = set(PLACEHOLDER.findall(_strip_sql_comments_and_strings(text)))
    if used != declared:
        raise QueryFileError(
            f"{path.name}: placeholders {sorted(used)} do not match declared params {sorted(declared)}"
        )

    unknown_macros = used_macros(text) - MACRO_NAMES
    if unknown_macros:
        raise QueryFileError(f"{path.name}: unknown macro(s) {sorted(unknown_macros)} (known: {sorted(MACRO_NAMES)})")

    for dialect in DIALECTS.values():       # a bad macro (wrong argument count, unclosed bracket) is caught here, for every engine
        try:
            dialect.compile(text, {p.name: None for p in params})
        except MacroError as exc:
            raise QueryFileError(f"{path.name}: {exc}") from None

    return Query(name, title, " ".join(description), tuple(params), chart, text, path)


def load_queries(directory: Path | None = None) -> dict[str, Query]:
    directory = directory or default_queries_dir()
    queries: dict[str, Query] = {}
    for path in sorted(directory.glob("*.sql")):
        query = parse_query(path)
        queries[query.name] = query
    return queries
