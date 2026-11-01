"""Command line: report list | show | run | explain | init-db | info."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .backends import connect, parse_target
from .dialect import MacroError
from .errors import DatabaseError, TargetError
from .generate import build_sample_db
from .load import load_sample
from .params import ParamError, parse_param_args, resolve_params
from .queries import Query, QueryFileError, load_queries
from .render import render

EXIT_OK, EXIT_RUNTIME, EXIT_USAGE = 0, 1, 2
DEFAULT_DB = "sample.db"
DB_HELP = (
    f"SQLite file (default {DEFAULT_DB}) or a postgresql://user@host/dbname or mariadb://user@host/dbname URL "
    "(password in the URL or in SQLREPORT_DB_PASSWORD)"
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="report", description="Run parameterized SQL reports on SQLite, PostgreSQL or MariaDB.")
    parser.add_argument("--queries-dir", type=Path, default=None, help="folder of .sql report files (default: ./queries)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list the available reports")

    show = sub.add_parser("show", help="show a report's description and parameters")
    show.add_argument("name")

    run = sub.add_parser("run", help="run a report")
    run.add_argument("name")
    run.add_argument("--param", "-p", action="append", default=[], metavar="KEY=VALUE", help="a report parameter (repeatable)")
    run.add_argument("--format", "-f", choices=["csv", "markdown", "html"], default="csv")
    run.add_argument("--db", default=DEFAULT_DB, help=DB_HELP)
    run.add_argument("--out", "-o", type=Path, default=None, help="write to this file instead of stdout")

    explain = sub.add_parser("explain", help="print the database's query plan for a report")
    explain.add_argument("name")
    explain.add_argument("--param", "-p", action="append", default=[], metavar="KEY=VALUE")
    explain.add_argument("--db", default=DEFAULT_DB, help=DB_HELP)

    init = sub.add_parser("init-db", help="create the fictional sample database")
    init.add_argument("--db", default=DEFAULT_DB, help=DB_HELP + ". For PostgreSQL and MariaDB the database must already exist")
    init.add_argument("--seed", type=int, default=42)
    init.add_argument("--force", action="store_true", help="replace an existing file (server databases: drop and recreate the five sample tables)")

    info = sub.add_parser("info", help="show which engine and version --db points at")
    info.add_argument("--db", default=DEFAULT_DB, help=DB_HELP)
    return parser


def _find(queries: dict[str, Query], name: str) -> Query:
    if name not in queries:
        raise ParamError(f"no report named {name!r}. Available: {', '.join(sorted(queries)) or 'none'}")
    return queries[name]


def _describe(query: Query) -> str:
    lines = [f"{query.name}: {query.title}", f"  {query.description}"]
    if query.params:
        lines.append("  parameters:")
        for p in query.params:
            default = "required" if p.required else f"default {p.default!r}"
            lines.append(f"    {p.name} ({p.type}, {default}): {p.help}")
    else:
        lines.append("  parameters: none")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse exits with 2 on a usage error and 0 for --help
        return int(exc.code or 0)

    try:
        if args.command == "init-db":
            target = parse_target(args.db)
            if target.engine == "sqlite":
                counts = build_sample_db(args.db, seed=args.seed, force=args.force)
            else:
                with connect(args.db, read_only=False) as writer:
                    counts = load_sample(writer, seed=args.seed, replace=args.force)
            print(f"created {target.describe()} (seed {args.seed}): " + ", ".join(f"{k} {v}" for k, v in counts.items()))
            return EXIT_OK

        if args.command == "info":
            with connect(args.db) as backend:
                print(f"{parse_target(args.db).describe()}: {backend.version()}")
            return EXIT_OK

        queries = load_queries(args.queries_dir)

        if args.command == "list":
            for query in queries.values():
                print(f"{query.name:<24} {query.title}")
            return EXIT_OK

        query = _find(queries, args.name)
        if args.command == "show":
            print(_describe(query))
            return EXIT_OK

        values = resolve_params(query, parse_param_args(args.param))
        with connect(args.db) as backend:
            if args.command == "explain":
                print("\n".join(backend.explain(query, values)))
                return EXIT_OK
            columns, rows = backend.run(query, values)

        text = render(args.format, query, columns, rows, values)
        if args.out:
            args.out.write_text(text, encoding="utf-8")
            print(f"{query.name}: {len(rows)} rows written to {args.out}", file=sys.stderr)
        else:
            sys.stdout.write(text)
            print(f"{query.name}: {len(rows)} rows", file=sys.stderr)
        return EXIT_OK
    except (ParamError, QueryFileError, TargetError, MacroError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except (DatabaseError, FileExistsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_RUNTIME


if __name__ == "__main__":
    sys.exit(main())
