"""Everything that differs between SQLite, PostgreSQL and MariaDB lives in this file.

Report files are written once. Where the engines disagree, the report uses a macro like
{{month_key(o.created_at)}} and the dialect decides what SQL that becomes. The macros are:

    month_key(x)        'YYYY-MM' text of a date or timestamp
    year_of(x)          the year as an integer
    month_of(x)         the month (1 to 12) as an integer
    month_index(x)      year * 12 + month, for counting months between two dates
    day_start(:p)       the date in a 'YYYY-MM-DD' parameter
    day_after(:p)       the day after that date (use with < to make an inclusive end date)
    month_start(:p)     the first day of a 'YYYY-MM' parameter
    month_after(:p)     the first day of the month after it
    concat(a, b, ...)   string concatenation (|| means OR in MariaDB)
    string_agg(x, sep, order_by)   join values into one string in a stated order
    cast_int(x)         cast to a 64-bit integer
    limit(n[, offset])  LIMIT clause
    true / false        boolean literals

Besides macros, a dialect owns: the placeholder style the driver wants, identifier quoting, the SQL that makes
a session read-only, the EXPLAIN prefix, and how result values are normalised so all engines return the
same Python types (Decimal to int or float, datetime to text, bool to int, bytes to str).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable

PLACEHOLDER = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")
MACRO_START = re.compile(r"\{\{\s*([A-Za-z_]\w*)\s*")


class MacroError(ValueError):
    """A report file uses a macro that does not exist or is malformed."""


# ---------------------------------------------------------------------------------------------
# A small scanner: comments, string literals and quoted identifiers are never touched as code.
# ---------------------------------------------------------------------------------------------


def _skip_quoted(text: str, i: int) -> int:
    """text[i] is a quote character; return the index just after the closing quote (doubled quotes escape)."""
    quote = text[i]
    j = i + 1
    while j < len(text):
        if text[j] == quote:
            if j + 1 < len(text) and text[j + 1] == quote:
                j += 2
                continue
            return j + 1
        j += 1
    return len(text)


def split_args(text: str) -> list[str]:
    """Split macro arguments on top-level commas (not inside parentheses or quotes)."""
    args: list[str] = []
    depth = 0
    current: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in "'\"`":
            end = _skip_quoted(text, i)
            current.append(text[i:end])
            i = end
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    last = "".join(current).strip()
    if last or args:
        args.append(last)
    return args


def used_macros(sql: str) -> set[str]:
    """Names of the {{macros}} used in `sql`, ignoring comments."""
    names: set[str] = set()
    i = 0
    while i < len(sql):
        if sql.startswith("--", i):
            end = sql.find("\n", i)
            i = len(sql) if end == -1 else end
        elif sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = len(sql) if end == -1 else end + 2
        elif sql[i] in "'\"`":
            i = _skip_quoted(sql, i)
        else:
            m = MACRO_START.match(sql, i) if sql.startswith("{{", i) else None
            if m:
                names.add(m.group(1))
                i = m.end()
            else:
                i += 1
    return names


def strip_comments_and_expand(sql: str, dialect: "Dialect") -> str:
    """Pass 1: drop comments and replace every {{macro}} with the dialect's SQL."""
    out: list[str] = []
    i = 0
    while i < len(sql):
        if sql.startswith("--", i):
            end = sql.find("\n", i)
            i = len(sql) if end == -1 else end
        elif sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = len(sql) if end == -1 else end + 2
            out.append(" ")
        elif sql[i] in "'\"`":
            end = _skip_quoted(sql, i)
            out.append(sql[i:end])
            i = end
        elif sql.startswith("{{", i):
            m = MACRO_START.match(sql, i)
            if not m:
                raise MacroError("malformed macro near " + repr(sql[i : i + 30]))
            name, j, args = m.group(1), m.end(), []
            if j < len(sql) and sql[j] == "(":
                depth, k = 0, j
                while k < len(sql):
                    if sql[k] in "'\"`":
                        k = _skip_quoted(sql, k)
                        continue
                    if sql[k] == "(":
                        depth += 1
                    elif sql[k] == ")":
                        depth -= 1
                        if depth == 0:
                            break
                    k += 1
                if depth != 0:
                    raise MacroError(f"macro {name}: missing closing parenthesis")
                args = [strip_comments_and_expand(a, dialect) for a in split_args(sql[j + 1 : k])]
                j = k + 1
            while j < len(sql) and sql[j].isspace():
                j += 1
            if not sql.startswith("}}", j):
                raise MacroError(f"macro {name}: expected }}}} after the arguments")
            out.append(dialect.expand_macro(name, args))
            i = j + 2
        else:
            out.append(sql[i])
            i += 1
    return "".join(out)


def bind_placeholders(sql: str, dialect: "Dialect") -> tuple[str, list[str]]:
    """Pass 2: turn :name into the driver's placeholder; double % where the driver treats it as special.

    Returns the SQL and the parameter names it uses, in order of first appearance."""
    out: list[str] = []
    used: list[str] = []
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch in "'\"`":
            end = _skip_quoted(sql, i)
            chunk = sql[i:end]
            out.append(chunk.replace("%", "%%") if dialect.escape_percent else chunk)
            i = end
            continue
        if ch == ":":
            m = PLACEHOLDER.match(sql, i)
            if m:
                name = m.group(1)
                if name not in used:
                    used.append(name)
                out.append(dialect.placeholder(name))
                i = m.end()
                continue
        if ch == "%" and dialect.escape_percent:
            out.append("%%")
        else:
            out.append(ch)
        i += 1
    return "".join(out), used


def split_statements(script: str) -> list[str]:
    """Split a SQL script on semicolons that are not inside strings or comments."""
    statements: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(script):
        if script.startswith("--", i):
            end = script.find("\n", i)
            i = len(script) if end == -1 else end
        elif script[i] in "'\"`":
            end = _skip_quoted(script, i)
            current.append(script[i:end])
            i = end
        elif script[i] == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            i += 1
        else:
            current.append(script[i])
            i += 1
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    params: dict[str, object]


# ---------------------------------------------------------------------------------------------
# Dialects
# ---------------------------------------------------------------------------------------------


class Dialect:
    name = "base"
    escape_percent = False          # True where the driver uses %(name)s and so treats a bare % as special

    def placeholder(self, name: str) -> str:
        raise NotImplementedError

    def quote_identifier(self, name: str) -> str:
        quote = self.identifier_quote
        return quote + name.replace(quote, quote * 2) + quote

    identifier_quote = '"'

    # --- session and plan SQL ---------------------------------------------------------------
    session_read_only_sql: tuple[str, ...] = ()
    begin_read_only_sql: str | None = None
    explain_prefix = "EXPLAIN "

    # --- macros -----------------------------------------------------------------------------
    def expand_macro(self, name: str, args: list[str]) -> str:
        method: Callable[..., str] | None = getattr(self, "macro_" + name, None)
        if method is None:
            raise MacroError(f"unknown macro {{{{{name}}}}} (known: {', '.join(sorted(self.known_macros()))})")
        try:
            return method(*args)
        except TypeError:
            raise MacroError(f"macro {name}: wrong number of arguments ({len(args)})") from None

    @classmethod
    def known_macros(cls) -> set[str]:
        return {n[len("macro_") :] for n in dir(cls) if n.startswith("macro_")}

    def macro_month_index(self, x: str) -> str:
        return f"({self.macro_year_of(x)} * 12 + {self.macro_month_of(x)})"

    def macro_limit(self, count: str, offset: str | None = None) -> str:
        return f"LIMIT {count}" + (f" OFFSET {offset}" if offset is not None else "")

    # --- result values ----------------------------------------------------------------------
    @staticmethod
    def normalize_value(value: Any) -> Any:
        """Make a driver's Python value look like what SQLite returns, so reports render the same everywhere."""
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, Decimal):
            exponent = value.as_tuple().exponent
            return int(value) if isinstance(exponent, int) and exponent >= 0 else float(value)
        if isinstance(value, datetime):
            return value.isoformat(sep=" ")
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, (bytes, bytearray, memoryview)):
            return bytes(value).decode("utf-8", errors="replace")
        return value

    def normalize_row(self, row: tuple) -> tuple:
        return tuple(self.normalize_value(v) for v in row)

    # --- compile ----------------------------------------------------------------------------
    def compile(self, sql: str, values: dict[str, object]) -> CompiledQuery:
        expanded = strip_comments_and_expand(sql, self).strip()
        bound, used = bind_placeholders(expanded, self)
        missing = [n for n in used if n not in values]
        if missing:
            raise MacroError(f"no value for parameter(s): {', '.join(missing)}")
        return CompiledQuery(bound, {n: values[n] for n in used})


class SQLiteDialect(Dialect):
    name = "sqlite"
    session_read_only_sql = ("PRAGMA query_only = ON",)
    explain_prefix = "EXPLAIN QUERY PLAN "

    def placeholder(self, name: str) -> str:
        return ":" + name

    def macro_month_key(self, x: str) -> str:
        return f"strftime('%Y-%m', {x})"

    def macro_year_of(self, x: str) -> str:
        return f"CAST(strftime('%Y', {x}) AS INTEGER)"

    def macro_month_of(self, x: str) -> str:
        return f"CAST(strftime('%m', {x}) AS INTEGER)"

    def macro_day_start(self, p: str) -> str:
        return f"date({p})"

    def macro_day_after(self, p: str) -> str:
        return f"date({p}, '+1 day')"

    def macro_month_start(self, p: str) -> str:
        return f"date({p} || '-01')"

    def macro_month_after(self, p: str) -> str:
        return f"date({p} || '-01', '+1 month')"

    def macro_concat(self, *parts: str) -> str:
        return "(" + " || ".join(parts) + ")"

    def macro_string_agg(self, x: str, sep: str, order_by: str) -> str:
        return f"group_concat({x}, {sep} ORDER BY {order_by})"      # SQLite 3.44 or newer

    def macro_cast_int(self, x: str) -> str:
        return f"CAST({x} AS INTEGER)"

    def macro_true(self) -> str:
        return "1"

    def macro_false(self) -> str:
        return "0"


class PostgresDialect(Dialect):
    name = "postgres"
    escape_percent = True
    session_read_only_sql = ("SET default_transaction_read_only = on",)
    explain_prefix = "EXPLAIN (COSTS OFF) "

    def placeholder(self, name: str) -> str:
        return f"%({name})s"

    def macro_month_key(self, x: str) -> str:
        return f"to_char({x}, 'YYYY-MM')"

    def macro_year_of(self, x: str) -> str:
        return f"CAST(EXTRACT(YEAR FROM {x}) AS INTEGER)"

    def macro_month_of(self, x: str) -> str:
        return f"CAST(EXTRACT(MONTH FROM {x}) AS INTEGER)"

    def macro_day_start(self, p: str) -> str:
        return f"CAST({p} AS date)"

    def macro_day_after(self, p: str) -> str:
        return f"(CAST({p} AS date) + INTERVAL '1 day')"

    def macro_month_start(self, p: str) -> str:
        return f"CAST(CAST({p} AS text) || '-01' AS date)"

    def macro_month_after(self, p: str) -> str:
        return f"(CAST(CAST({p} AS text) || '-01' AS date) + INTERVAL '1 month')"

    def macro_concat(self, *parts: str) -> str:
        return "(" + " || ".join(parts) + ")"

    def macro_string_agg(self, x: str, sep: str, order_by: str) -> str:
        return f"string_agg(CAST({x} AS TEXT), {sep} ORDER BY {order_by})"

    def macro_cast_int(self, x: str) -> str:
        return f"CAST({x} AS BIGINT)"

    def macro_true(self) -> str:
        return "TRUE"

    def macro_false(self) -> str:
        return "FALSE"


class MariaDBDialect(Dialect):
    name = "mariadb"
    escape_percent = True
    identifier_quote = "`"
    session_read_only_sql = ("SET SESSION TRANSACTION READ ONLY",)
    begin_read_only_sql = "START TRANSACTION READ ONLY"

    def placeholder(self, name: str) -> str:
        return f"%({name})s"

    def macro_month_key(self, x: str) -> str:
        return f"DATE_FORMAT({x}, '%Y-%m')"

    def macro_year_of(self, x: str) -> str:
        return f"YEAR({x})"

    def macro_month_of(self, x: str) -> str:
        return f"MONTH({x})"

    def macro_day_start(self, p: str) -> str:
        return f"CAST({p} AS DATE)"

    def macro_day_after(self, p: str) -> str:
        return f"DATE_ADD(CAST({p} AS DATE), INTERVAL 1 DAY)"

    def macro_month_start(self, p: str) -> str:
        return f"STR_TO_DATE(CONCAT({p}, '-01'), '%Y-%m-%d')"

    def macro_month_after(self, p: str) -> str:
        return f"DATE_ADD(STR_TO_DATE(CONCAT({p}, '-01'), '%Y-%m-%d'), INTERVAL 1 MONTH)"

    def macro_concat(self, *parts: str) -> str:
        return "CONCAT(" + ", ".join(parts) + ")"

    def macro_string_agg(self, x: str, sep: str, order_by: str) -> str:
        return f"GROUP_CONCAT({x} ORDER BY {order_by} SEPARATOR {sep})"

    def macro_cast_int(self, x: str) -> str:
        return f"CAST({x} AS SIGNED)"

    def macro_true(self) -> str:
        return "TRUE"

    def macro_false(self) -> str:
        return "FALSE"


DIALECTS: dict[str, Dialect] = {d.name: d for d in (SQLiteDialect(), PostgresDialect(), MariaDBDialect())}
MACRO_NAMES = frozenset(SQLiteDialect.known_macros() | PostgresDialect.known_macros() | MariaDBDialect.known_macros())
