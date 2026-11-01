"""Turn the --db value into a Target: a SQLite file path, or a postgresql:// or mariadb:// URL.

    report.db                                    a SQLite file
    postgresql://user:pass@host:5432/dbname      PostgreSQL (TCP)
    postgresql://user@/dbname?host=/tmp          PostgreSQL over a unix socket
    mariadb://user:pass@127.0.0.1:3306/dbname    MariaDB or MySQL (TCP); mysql:// is accepted too
    mariadb://user@/dbname?unix_socket=/x.sock   MariaDB over a unix socket

Special characters in a user name or password must be percent-encoded. If the URL has no password, the
SQLREPORT_DB_PASSWORD environment variable is used (PostgreSQL also reads PGPASSWORD on its own).
A Target never prints its password.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, unquote, urlsplit

from ..errors import TargetError

SCHEMES = {"postgresql": "postgres", "postgres": "postgres", "mariadb": "mariadb", "mysql": "mariadb"}
DEFAULT_PORTS = {"postgres": 5432, "mariadb": 3306}
KNOWN_OPTIONS = {"postgres": {"host", "sslmode"}, "mariadb": {"unix_socket"}}


@dataclass(frozen=True)
class Target:
    engine: str                      # sqlite, postgres or mariadb
    path: str = ""                   # sqlite only
    host: str = ""
    port: int | None = None
    user: str = ""
    password: str = field(default="", repr=False)
    database: str = ""
    options: tuple[tuple[str, str], ...] = ()

    def option(self, name: str, default: str = "") -> str:
        return dict(self.options).get(name, default)

    def describe(self) -> str:
        """A string that is safe to print: the password is never included."""
        if self.engine == "sqlite":
            return self.path
        where = self.option("host") or self.option("unix_socket") or f"{self.host or 'localhost'}:{self.port or DEFAULT_PORTS[self.engine]}"
        return f"{self.engine} {self.database or '(no database)'} at {where} as {self.user or '(default user)'}"


def parse_target(text: str) -> Target:
    if "://" not in text:
        return Target("sqlite", path=text)
    parts = urlsplit(text)
    engine = SCHEMES.get(parts.scheme.lower())
    if engine is None:
        raise TargetError(
            f"unsupported database URL scheme {parts.scheme!r} (use postgresql://, mariadb://, mysql:// or a file path)"
        )
    try:
        port = parts.port
    except ValueError:
        raise TargetError("the port in the database URL is not a number") from None
    options = tuple(parse_qsl(parts.query, keep_blank_values=True))
    unknown = sorted({k for k, _ in options} - KNOWN_OPTIONS[engine])
    if unknown:
        raise TargetError(
            f"unsupported option(s) in the database URL: {', '.join(unknown)} (valid: {', '.join(sorted(KNOWN_OPTIONS[engine]))})"
        )
    password = unquote(parts.password) if parts.password is not None else os.environ.get("SQLREPORT_DB_PASSWORD", "")
    return Target(
        engine=engine,
        host=unquote(parts.hostname or ""),
        port=port,
        user=unquote(parts.username or ""),
        password=password,
        database=unquote(parts.path.lstrip("/")),
        options=options,
    )
