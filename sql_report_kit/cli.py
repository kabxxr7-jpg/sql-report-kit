"""Command line: report list | show | run | explain | init-db."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .db import DatabaseError, connect_readonly, explain_query, run_query
from .generate import build_sample_db
from .params import ParamError, parse_param_args, resolve_params
from .queries import Query, QueryFileError, load_queries
from .render import render

EXIT_OK, EXIT_RUNTIME, EXIT_USAGE = 0, 1, 2
DEFAULT_DB = "sample.db"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="report", description="Run parameterized SQL reports on a SQLite database.")
    parser.add_argument("--queries-dir", type=Path, default=None, help="folder of .sql report files (default: ./queries)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list the available reports")

    show = sub.add_parser("show", help="show a report's description and parameters")
    show.add_argument("name")

    run = sub.add_parser("run", help="run a report")
    run.add_argument("name")
    run.add_argument("--param", "-p", action="append", default=[], metavar="KEY=VALUE", help="a report parameter (repeatable)")
    run.add_argument("--format", "-f", choices=["csv", "markdown", "html"], default="csv")
    run.add_argument("--db", default=DEFAULT_DB, help=f"SQLite file (default {DEFAULT_DB})")
    run.add_argument("--out", "-o", type=Path, default=None, help="write to this file instead of stdout")

    explain = sub.add_parser("explain", help="print SQLite's EXPLAIN QUERY PLAN for a report")
    explain.add_argument("name")
    explain.add_argument("--param", "-p", action="append", default=[], metavar="KEY=VALUE")
    explain.add_argument("--db", default=DEFAULT_DB)

    init = sub.add_parser("init-db", help="create the fictional sample database")
    init.add_argument("--db", default=DEFAULT_DB)
    init.add_argument("--seed", type=int, default=42)
    init.add_argument("--force", action="store_true", help="replace an existing file")
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
            counts = build_sample_db(args.db, seed=args.seed, force=args.force)
            print(f"created {args.db} (seed {args.seed}): " + ", ".join(f"{k} {v}" for k, v in counts.items()))
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
        conn = connect_readonly(args.db)
        try:
            if args.command == "explain":
                print("\n".join(explain_query(conn, query, values)))
                return EXIT_OK
            columns, rows = run_query(conn, query, values)
        finally:
            conn.close()

        text = render(args.format, query, columns, rows, values)
        if args.out:
            args.out.write_text(text, encoding="utf-8")
            print(f"{query.name}: {len(rows)} rows written to {args.out}", file=sys.stderr)
        else:
            sys.stdout.write(text)
            print(f"{query.name}: {len(rows)} rows", file=sys.stderr)
        return EXIT_OK
    except (ParamError, QueryFileError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except (DatabaseError, FileExistsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_RUNTIME


if __name__ == "__main__":
    sys.exit(main())
