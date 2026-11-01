#!/usr/bin/env python3
"""Mutation check: break the new backend code on purpose, one way at a time, and see whether the tests notice.

For each mutant this copies the project into .mutation-work/ (inside this folder, git-ignored), applies ONE textual
change to one source file there and runs the test suite against the real PostgreSQL and MariaDB servers:

  phase 1  only the engine tests (tests/test_engine_*.py), which run every report on SQLite, PostgreSQL and MariaDB
  phase 2  only if phase 1 passed: the whole suite, including the tests that need no database

A mutant is KILLED if some test fails. It SURVIVED if the whole suite passed. A TIMEOUT is not a kill: the process
group is killed hard when the per-mutant limit runs out, and the mutant is counted separately (and fails the check).
A crash that is not a test failure (a collection error, a usage error) is reported as ERROR, also not a kill.
Each mutant gets its own SQLREPORT_RUN_TAG so databases and users left behind by a killed run can be dropped by name.
The working tree you are editing is never modified.

Needs the servers up (python scripts/local-mariadb.py start; the PostgreSQL from the README) and is run with the
project's virtualenv:   .venv/bin/python scripts/mutation-check.py [--only ID] [--list] [--timeout SECONDS]
Exit code: 0 if every mutant was killed, 1 if any survived or timed out, 2 if the script is stale or the baseline fails.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / ".mutation-work"
IGNORE = shutil.ignore_patterns(
    ".git", ".venv", ".local-db", ".mutation-work", "__pycache__", ".pytest_cache", "*.pyc", "*.db", "*.log"
)

# id, file, find (must occur exactly once), replace, what breaks
M = [
    # ---- dialect.py: SQL per engine -------------------------------------------------------------------------
    ("sqlite-month-key", "sql_report_kit/dialect.py", """return f"strftime('%Y-%m', {x})\"""", """return f"strftime('%Y', {x})\"""", "SQLite month key loses the month"),
    ("sqlite-month-of", "sql_report_kit/dialect.py", """return f"CAST(strftime('%m', {x}) AS INTEGER)\"""", """return f"CAST(strftime('%d', {x}) AS INTEGER)\"""", "SQLite month_of returns the day"),
    ("sqlite-day-after", "sql_report_kit/dialect.py", """return f"date({p}, '+1 day')\"""", """return f"date({p}, '+2 day')\"""", "SQLite inclusive end date runs one day too long"),
    ("sqlite-month-after", "sql_report_kit/dialect.py", """return f"date({p} || '-01', '+1 month')\"""", """return f"date({p} || '-01', '+2 month')\"""", "SQLite month range is two months wide"),
    ("sqlite-string-agg-order", "sql_report_kit/dialect.py", """return f"group_concat({x}, {sep} ORDER BY {order_by})\"""", """return f"group_concat({x}, {sep} ORDER BY {order_by} DESC)\"""", "SQLite id list in descending order"),
    ("sqlite-true", "sql_report_kit/dialect.py", """return "1\"""", """return "0\"""", "SQLite TRUE literal is 0"),
    ("pg-month-key", "sql_report_kit/dialect.py", """return f"to_char({x}, 'YYYY-MM')\"""", """return f"to_char({x}, 'YYYY-Q')\"""", "PostgreSQL month key shows the quarter"),
    ("pg-year-of", "sql_report_kit/dialect.py", """return f"CAST(EXTRACT(YEAR FROM {x}) AS INTEGER)\"""", """return f"CAST(EXTRACT(MONTH FROM {x}) AS INTEGER)\"""", "PostgreSQL year_of returns the month"),
    ("pg-day-after", "sql_report_kit/dialect.py", """return f"(CAST({p} AS date) + INTERVAL '1 day')\"""", """return f"(CAST({p} AS date) + INTERVAL '0 day')\"""", "PostgreSQL inclusive end date drops its last day"),
    ("pg-month-after", "sql_report_kit/dialect.py", """INTERVAL '1 month')\"""", """INTERVAL '2 month')\"""", "PostgreSQL month range is two months wide"),
    ("pg-string-agg-cast", "sql_report_kit/dialect.py", """return f"string_agg(CAST({x} AS TEXT), {sep} ORDER BY {order_by})\"""", """return f"string_agg({x}, {sep} ORDER BY {order_by})\"""", "PostgreSQL string_agg of integers has no cast"),
    ("pg-string-agg-order", "sql_report_kit/dialect.py", """return f"string_agg(CAST({x} AS TEXT), {sep} ORDER BY {order_by})\"""", """return f"string_agg(CAST({x} AS TEXT), {sep} ORDER BY {order_by} DESC)\"""", "PostgreSQL id list in descending order"),
    ("pg-cast-int-32bit", "sql_report_kit/dialect.py", """return f"CAST({x} AS BIGINT)\"""", """return f"CAST({x} AS INTEGER)\"""", "PostgreSQL cast_int overflows past 2^31"),
    ("pg-explain-prefix", "sql_report_kit/dialect.py", """explain_prefix = "EXPLAIN (COSTS OFF) \"""", """explain_prefix = "EXPLAIN \"""", "PostgreSQL plans print costs"),
    ("maria-month-key", "sql_report_kit/dialect.py", """return f"DATE_FORMAT({x}, '%Y-%m')\"""", """return f"DATE_FORMAT({x}, '%Y-%c')\"""", "MariaDB month key has no leading zero"),
    ("maria-year-of", "sql_report_kit/dialect.py", """return f"YEAR({x})\"""", """return f"MONTH({x})\"""", "MariaDB year_of returns the month"),
    ("maria-day-after", "sql_report_kit/dialect.py", """INTERVAL 1 DAY)\"""", """INTERVAL 0 DAY)\"""", "MariaDB inclusive end date drops its last day"),
    ("maria-month-after", "sql_report_kit/dialect.py", """INTERVAL 1 MONTH)\"""", """INTERVAL 2 MONTH)\"""", "MariaDB month range is two months wide"),
    ("maria-concat-pipes", "sql_report_kit/dialect.py", """return "CONCAT(" + ", ".join(parts) + ")\"""", """return "(" + " || ".join(parts) + ")\"""", "MariaDB concatenation uses || (which means OR there)"),
    ("maria-string-agg-no-order", "sql_report_kit/dialect.py", """return f"GROUP_CONCAT({x} ORDER BY {order_by} SEPARATOR {sep})\"""", """return f"GROUP_CONCAT({x} SEPARATOR {sep})\"""", "MariaDB id list has no ORDER BY"),
    ("maria-string-agg-order", "sql_report_kit/dialect.py", """return f"GROUP_CONCAT({x} ORDER BY {order_by} SEPARATOR {sep})\"""", """return f"GROUP_CONCAT({x} ORDER BY {order_by} DESC SEPARATOR {sep})\"""", "MariaDB id list in descending order"),
    ("maria-cast-int", "sql_report_kit/dialect.py", """return f"CAST({x} AS SIGNED)\"""", """return f"CAST({x} AS UNSIGNED)\"""", "MariaDB cast_int is unsigned (negative averages break)"),
    ("maria-read-only-session", "sql_report_kit/dialect.py", """session_read_only_sql = ("SET SESSION TRANSACTION READ ONLY",)""", """session_read_only_sql = ("SET SESSION TRANSACTION READ WRITE",)""", "MariaDB session default is read-write"),
    ("maria-read-only-begin", "sql_report_kit/dialect.py", """begin_read_only_sql = "START TRANSACTION READ ONLY\"""", """begin_read_only_sql = "START TRANSACTION\"""", "MariaDB reports no longer start READ ONLY transactions"),
    ("month-index-factor", "sql_report_kit/dialect.py", """return f"({self.macro_year_of(x)} * 12 + {self.macro_month_of(x)})\"""", """return f"({self.macro_year_of(x)} * 11 + {self.macro_month_of(x)})\"""", "cohort month arithmetic is wrong"),
    ("limit-offset-dropped", "sql_report_kit/dialect.py", """+ (f" OFFSET {offset}" if offset is not None else "")""", """+ \"\"""", "limit() ignores its offset"),
    # ---- dialect.py: placeholders, % escaping, value normalising -------------------------------------------
    ("string-percent-not-doubled", "sql_report_kit/dialect.py", """out.append(chunk.replace("%", "%%") if dialect.escape_percent else chunk)""", """out.append(chunk)""", "a % inside a string literal is not doubled for pyformat drivers"),
    ("bare-percent-not-doubled", "sql_report_kit/dialect.py", """if ch == "%" and dialect.escape_percent:""", """if ch == "%" and False:""", "a bare % (modulo) is not doubled for pyformat drivers"),
    ("params-not-trimmed", "sql_report_kit/dialect.py", """CompiledQuery(bound, {n: values[n] for n in used})""", """CompiledQuery(bound, dict(values))""", "unused parameters are passed to the driver"),
    ("quote-not-doubled", "sql_report_kit/dialect.py", """return quote + name.replace(quote, quote * 2) + quote""", """return quote + name + quote""", "identifier quoting does not double an embedded quote"),
    ("normalize-decimal-int", "sql_report_kit/dialect.py", """exponent >= 0 else float(value)""", """exponent > 0 else float(value)""", "whole Decimals (SUM results) come back as floats"),
    ("normalize-datetime", "sql_report_kit/dialect.py", """return value.isoformat(sep=" ")""", """return value.isoformat()""", "timestamps come back with a T instead of a space"),
    ("normalize-bool", "sql_report_kit/dialect.py", """        if isinstance(value, bool):
            return int(value)""", """        if isinstance(value, bool):
            return value""", "booleans stay True/False instead of 1/0"),
    ("normalize-bytes", "sql_report_kit/dialect.py", """return bytes(value).decode("utf-8", errors="replace")""", """return str(value)""", "bytes come back as b'...'"),
    ("split-args-nesting", "sql_report_kit/dialect.py", """if ch == "," and depth == 0:""", """if ch == ",":""", "macro arguments split inside parentheses"),
    ("quote-escape-ignored", "sql_report_kit/dialect.py", """if j + 1 < len(text) and text[j + 1] == quote:""", """if False:""", "EQUIVALENT mutant, expected to survive: a doubled quote is read as two adjacent strings, which gives the same result"),
    # ---- backends -----------------------------------------------------------------------------------------
    ("one-statement-check", "sql_report_kit/backends/base.py", """if len(split_statements(compiled.sql)) != 1:""", """if len(split_statements(compiled.sql)) < 1:""", "a second statement in a report is allowed"),
    ("rows-not-normalised", "sql_report_kit/backends/base.py", """return columns, [self.dialect.normalize_row(tuple(r)) for r in rows]""", """return columns, [tuple(r) for r in rows]""", "driver types leak into results"),
    ("pg-not-read-only-transactions", "sql_report_kit/backends/postgres.py", """conn.read_only = read_only""", """conn.read_only = False""", "PostgreSQL transactions no longer start READ ONLY"),
    ("pg-no-session-default", "sql_report_kit/backends/postgres.py", """for statement in cls.dialect.session_read_only_sql:""", """for statement in ():""", "PostgreSQL session default is not set read-only"),
    ("pg-no-rollback", "sql_report_kit/backends/postgres.py", """self.conn.rollback()           # end the read-only transaction""", """pass           # end the read-only transaction""", "PostgreSQL leaves the transaction open after a report"),
    ("pg-setval-off-by-two", "sql_report_kit/backends/postgres.py", """COALESCE((SELECT MAX(id) FROM {q}), 0) + 1, false)""", """COALESCE((SELECT MAX(id) FROM {q}), 0) - 1, false)""", "PostgreSQL identity sequences restart inside the loaded ids"),
    ("pg-ignores-password", "sql_report_kit/backends/postgres.py", """"password": target.password or None,""", """"password": None,""", "PostgreSQL connections never send the password (the local server trusts its socket, so this is expected to survive)"),
    ("maria-wrong-charset", "sql_report_kit/backends/mariadb.py", """"charset": "utf8mb4",""", """"charset": "latin1",""", "MariaDB connection cannot carry non-Latin text"),
    ("maria-no-rollback", "sql_report_kit/backends/mariadb.py", """            if began:
                try:
                    self.conn.rollback()""", """            if False:
                try:
                    self.conn.rollback()""", "MariaDB leaves the READ ONLY transaction open"),
    ("maria-no-session-readonly", "sql_report_kit/backends/mariadb.py", """for statement in backend.dialect.session_read_only_sql:""", """for statement in ():""", "MariaDB session is not made read-only on connect"),
    ("maria-explain-key", "sql_report_kit/backends/mariadb.py", """key={row[index['key']]}""", """key={row[index['ref']]}""", "MariaDB plan lines show the wrong column for the index"),
    ("maria-ignores-password", "sql_report_kit/backends/mariadb.py", """"password": target.password or None,""", """"password": None,""", "MariaDB connections never send the password"),
    ("sqlite-not-mode-ro", "sql_report_kit/backends/sqlite.py", """+ "?mode=ro\"""", """+ "?mode=rw\"""", "SQLite file is opened read-write"),
    # ---- target URLs -------------------------------------------------------------------------------------
    ("target-no-mysql-scheme", "sql_report_kit/backends/target.py", """, "mysql": "mariadb\"""", "", "mysql:// URLs are no longer accepted"),
    ("target-env-password", "sql_report_kit/backends/target.py", """else os.environ.get("SQLREPORT_DB_PASSWORD", "")""", """else \"\"""", "SQLREPORT_DB_PASSWORD is ignored"),
    ("target-options-unchecked", "sql_report_kit/backends/target.py", """    if unknown:""", """    if False:""", "unknown URL options are accepted"),
    ("target-describe-leaks", "sql_report_kit/backends/target.py", """as {self.user or '(default user)'}\"""", """as {self.user or '(default user)'}:{self.password}\"""", "describe() prints the password"),
    ("target-repr-leaks", "sql_report_kit/backends/target.py", """password: str = field(default="", repr=False)""", """password: str = field(default="")""", "repr() prints the password"),
    # ---- loader and command line --------------------------------------------------------------------------
    ("load-no-guard", "sql_report_kit/load.py", """if present and not replace:""", """if present and False:""", "loading over existing tables is not refused"),
    ("load-drop-order", "sql_report_kit/load.py", """for table in reversed(TABLES):""", """for table in TABLES:""", "tables are dropped parents first"),
    ("load-date-column", "sql_report_kit/load.py", """("refunds", 3): "datetime\"""", """("refunds", 2): "datetime\"""", "the wrong refunds column is converted to a timestamp"),
    ("cli-force-always", "sql_report_kit/cli.py", """replace=args.force)""", """replace=True)""", "init-db on a server always drops the tables"),
    ("cli-target-error-exit", "sql_report_kit/cli.py", """except (ParamError, QueryFileError, TargetError, MacroError) as exc:""", """except (ParamError, QueryFileError, MacroError) as exc:""", "a bad --db URL is a crash, not exit code 2"),
]


def run_pytest(directory: Path, paths: list[str], tag: str, timeout: int) -> tuple[str, str, float]:
    """Run pytest in `directory`. Returns (status, first failing test or detail, seconds).
    status is passed, failed, error or timeout. On timeout the whole process group is killed."""
    env = dict(os.environ, SQLREPORT_RUN_TAG=tag, SQLREPORT_REQUIRE_BACKENDS="postgres,mariadb", PYTHONDONTWRITEBYTECODE="1")
    # the copy has no .local-db folder, so point it at the real server's socket
    env.setdefault("SQLREPORT_MARIADB_ADMIN_URL", f"mariadb://{getpass.getuser()}@/?unix_socket={quote(str(ROOT / '.local-db' / 'mariadb' / 'mariadb.sock'), safe='/')}")
    cmd = [sys.executable, "-m", "pytest", "-x", "-p", "no:cacheprovider", "--tb=no", "-rfE", *paths]
    started = time.time()
    proc = subprocess.Popen(cmd, cwd=directory, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.communicate()
        return "timeout", f"no result after {timeout}s", time.time() - started
    elapsed = time.time() - started
    if proc.returncode == 0:
        return "passed", "", elapsed
    if proc.returncode == 1:
        m = re.search(r"^(FAILED|ERROR) (\S+)", out, re.M)
        if m and m.group(1) == "ERROR":
            return "failed", f"[error before the test body] {m.group(2)}", elapsed
        return "failed", m.group(2) if m else "(failure not parsed)", elapsed
    return "error", f"pytest exit {proc.returncode}: " + " | ".join(out.strip().splitlines()[-3:]), elapsed


def cleanup(tag: str) -> list[str]:
    result = subprocess.run([sys.executable, "-m", "tests.engines", "cleanup", "--tag", tag], cwd=ROOT, capture_output=True, text=True, timeout=120)
    lines = [ln for ln in result.stdout.splitlines() if ln and ln != "nothing to clean up"]
    return lines


def make_copy() -> Path:
    if WORK.exists():
        shutil.rmtree(WORK)
    shutil.copytree(ROOT, WORK, ignore=IGNORE)
    return WORK


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help="run just this mutant id")
    parser.add_argument("--list", action="store_true", help="list the mutants and exit")
    parser.add_argument("--timeout", type=int, default=300, help="hard limit per pytest phase, in seconds (default 300)")
    args = parser.parse_args()

    ids = [m[0] for m in M]
    if len(set(ids)) != len(ids):
        print("duplicate mutant ids", file=sys.stderr)
        return 2
    if args.list:
        for mid, file, _, _, why in M:
            print(f"{mid:34} {file:38} {why}")
        return 0
    chosen = [m for m in M if not args.only or m[0] == args.only]
    if not chosen:
        print(f"no mutant {args.only!r}", file=sys.stderr)
        return 2

    engine_tests = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("test_engine_*.py"))

    # a stale mutant (its text no longer occurs exactly once) is a bug in this script, found before any test runs
    for mid, file, find, _, _ in chosen:
        count = (ROOT / file).read_text(encoding="utf-8").count(find)
        if count != 1:
            print(f"STALE: {mid}: the text to replace occurs {count} times in {file} (needs exactly 1)", file=sys.stderr)
            return 2

    work = make_copy()
    status, detail, secs = run_pytest(work, [], "mutbase", args.timeout)
    leaked = cleanup("mutbase")
    print(f"baseline (unmodified copy, full suite): {status} in {secs:.0f}s" + (f" - {detail}" if detail else ""))
    if status != "passed" or leaked:
        print("the unmodified code must pass, and leave no database behind; fix that first", leaked, file=sys.stderr)
        return 2

    results = []
    for n, (mid, file, find, replace, why) in enumerate(chosen, start=1):
        work = make_copy()
        target = work / file
        target.write_text(target.read_text(encoding="utf-8").replace(find, replace), encoding="utf-8")
        tag = f"mut{n}"
        status, detail, secs = run_pytest(work, engine_tests, tag, args.timeout)
        how = "engine tests"
        if status == "passed":
            status, detail, more = run_pytest(work, [], tag, args.timeout)
            secs += more
            how = "unit tests only" if status == "failed" else "no test"
        leftovers = cleanup(tag)
        verdict = {"failed": "KILLED", "passed": "SURVIVED", "timeout": "TIMEOUT", "error": "ERROR"}[status]
        results.append((mid, verdict, how if verdict == "KILLED" else "", detail, why, leftovers))
        short = detail.split("::", 1)[-1][:70] if detail else ""
        print(f"[{n:2}/{len(chosen)}] {verdict:8} {mid:34} {secs:5.0f}s  {('by ' + how + ': ' + short) if verdict == 'KILLED' else detail}", flush=True)
        if leftovers:
            print(f"        databases or users left by this run were dropped by tag: {leftovers}", flush=True)

    shutil.rmtree(WORK, ignore_errors=True)
    killed = [r for r in results if r[1] == "KILLED"]
    by_engine = [r for r in killed if r[2] == "engine tests"]
    print()
    print(f"killed {len(killed)}/{len(results)}  (by the engine tests on real PostgreSQL/MariaDB: {len(by_engine)}; "
          f"only by tests that need no database: {len(killed) - len(by_engine)})")
    for verdict in ("SURVIVED", "TIMEOUT", "ERROR"):
        for mid, v, _, detail, why, _ in results:
            if v == verdict:
                print(f"{verdict}: {mid}: {why}" + (f" [{detail}]" if detail else ""))
    for mid, v, how, _, why, _ in results:
        if v == "KILLED" and how != "engine tests":
            print(f"killed without the engine tests: {mid}: {why}")
    return 0 if len(killed) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
