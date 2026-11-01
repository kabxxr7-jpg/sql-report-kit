# sql-report-kit

> **Status:** a proof project, run locally only. The same ten reports ran, with identical results, on **SQLite 3.54.1, PostgreSQL 16.15 and MariaDB 13.0.2** (Python 3.11.14, psycopg 3.3.6, PyMySQL 1.2.3) against a generated fictional database: **400 tests**, all passing with both servers running (242 pass and 158 are skipped when no PostgreSQL or MariaDB server can be reached). Not used in production or by any client, and never run against a client's database. The GitHub Actions file has **not run**. See Limits and "What this does not prove".

Ten documented, parameterized SQL reports for a small online shop, a command line that runs them safely on SQLite, PostgreSQL or MariaDB, and output as CSV, Markdown or one self-contained HTML page with an inline bar chart. It is a starting point for "write me some SQL reports" and "a small dashboard from our data" jobs: the reports are plain `.sql` files you can read, change and re-test, and the same file runs on all three databases.

## Quick start

Python 3.11. SQLite needs nothing extra; PostgreSQL and MariaDB need two pure-Python drivers (`requirements-backends.txt`).

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python report init-db                       # creates sample.db (fictional data, seed 42)
.venv/bin/python report list
.venv/bin/python report run monthly_revenue --format html --out revenue.html
.venv/bin/python report run top_customers -p limit=5 -p city=Austin -f markdown
.venv/bin/python report explain orders_in_month_fast -p month=2025-03
.venv/bin/python -m pytest
```

`report show <name>` prints a report's description and parameters. `python -m sql_report_kit ...` is the same command.

### Pointing it at PostgreSQL or MariaDB

`--db` takes a SQLite file or a URL. The database must already exist; `init-db` fills it with the same fictional data.

```bash
.venv/bin/python report init-db --db postgresql://shop_user@/shopdb?host=/tmp          # unix socket
.venv/bin/python report run monthly_revenue --db postgresql://shop_user:secret@db.internal:5432/shopdb
.venv/bin/python report run top_customers -p limit=3 --db mariadb://shop_user:secret@127.0.0.1:3306/shopdb
.venv/bin/python report info --db mariadb://shop_user:secret@127.0.0.1:3306/shopdb      # engine and server version
```

Percent-encode special characters in a user name or password, or leave the password out of the URL and set `SQLREPORT_DB_PASSWORD`. Error messages never print the password. `mysql://` is accepted as a spelling of `mariadb://`, but only MariaDB was ever run (see below). `init-db --force` on a server drops and recreates exactly the five sample tables and nothing else; on SQLite it replaces the file.

## The sample data

`init-db` builds a fictional shop: customers 512, products 30, orders 1086, order_items 2051, refunds 53. Names are random first and last name combinations (not real people), emails use `example.com`, dates run from 2024-01-01 to 2025-06-30, and money is stored as integer cents. The same seed gives identical rows every time (a test compares a hash of every table), and the same rows go into all three engines (a test compares that hash across SQLite, PostgreSQL and MariaDB after the rows are read back). The generator plants things the reports should find: a few duplicate customers, four products that never sell, cancelled and pending orders, and partial and full refunds.

## The reports

| Report | Answers | Parameters |
|---|---|---|
| `monthly_revenue` | Gross, refunds and net by month | `from_date`, `to_date` |
| `top_customers` | Best customers by net spend | `limit`, `city`, `from_date`, `to_date` |
| `repeat_purchase_rate` | Share of each signup month's customers who ordered again | `min_orders` |
| `refunds_by_product` | Refund count, amount and share of revenue per product | `from_date`, `to_date` |
| `products_never_sold` | Products with no completed sale in the window | `from_date`, `to_date` |
| `cohort_retention` | Share of each signup cohort ordering 0 to 3 months later | none |
| `running_totals` | Monthly net, cumulative net and a 3-month average (window functions) | `from_date`, `to_date` |
| `duplicate_customers` | Customers sharing a normalized email, or name plus city | none |
| `orders_in_month_slow` | Orders in a month, written so SQLite cannot use the date index | `month` (required) |
| `orders_in_month_fast` | The same rows, rewritten to use the index | `month` (required) |

Each file in `queries/` starts with a comment header (title, description, `-- param:` lines, optional `-- chart:`) and is one SQL statement. Dates are inclusive. Columns ending in `_cents` are shown as dollars in a column renamed `_usd`.

## One report file, three databases

Most of each report is plain SQL that all three engines accept (CTEs, window functions, `COALESCE`, `ROUND`, `CASE`). Where they disagree, the report file uses a `{{macro(...)}}` and `sql_report_kit/dialect.py`, the only place engine SQL lives, turns it into the right text for the engine in use. Every macro and what it becomes is spelled out in `tests/test_dialect.py`.

| Difference | Report file says | SQLite | PostgreSQL | MariaDB |
|---|---|---|---|---|
| Month as `YYYY-MM` text | `{{month_key(x)}}` | `strftime('%Y-%m', x)` | `to_char(x, 'YYYY-MM')` | `DATE_FORMAT(x, '%Y-%m')` |
| Year or month as a number | `{{year_of(x)}}`, `{{month_of(x)}}` | `CAST(strftime('%Y', x) AS INTEGER)` | `CAST(EXTRACT(YEAR FROM x) AS INTEGER)` | `YEAR(x)` |
| Date from a parameter, and the day after (inclusive end dates) | `{{day_start(:p)}}`, `{{day_after(:p)}}` | `date(:p)`, `date(:p, '+1 day')` | `CAST(:p AS date)`, `+ INTERVAL '1 day'` | `CAST(:p AS DATE)`, `DATE_ADD(..., INTERVAL 1 DAY)` |
| First day of a `YYYY-MM` parameter, and of the next month | `{{month_start(:m)}}`, `{{month_after(:m)}}` | `date(:m \|\| '-01')` | `CAST(:m \|\| '-01' AS date)` | `STR_TO_DATE(CONCAT(:m, '-01'), ...)` |
| String concatenation | `{{concat(a, b)}}` | `a \|\| b` | `a \|\| b` | `CONCAT(a, b)` (`\|\|` means OR there) |
| Ordered string aggregation | `{{string_agg(x, ',', order)}}` | `group_concat(x, ',' ORDER BY ...)` | `string_agg(CAST(x AS TEXT), ',' ORDER BY ...)` | `GROUP_CONCAT(x ORDER BY ... SEPARATOR ',')` |
| 64-bit integer cast | `{{cast_int(x)}}` | `CAST(x AS INTEGER)` | `CAST(x AS BIGINT)` | `CAST(x AS SIGNED)` |
| `LIMIT` | `{{limit(:n)}}` | `LIMIT :n` | `LIMIT :n` | `LIMIT :n` |
| Boolean literal | `{{true}}`, `{{false}}` | `1`, `0` | `TRUE`, `FALSE` | `TRUE`, `FALSE` |
| Parameter style | `:name` | `:name` | `%(name)s` (and `%` doubled) | `%(name)s` (and `%` doubled) |
| Quoting an identifier | (not used in reports) | `"name"` | `"name"` | `` `name` `` |

`LIMIT n` happens to be identical on the three engines; it is a macro so the one place that would have to change (an offset, or "no limit", which differ) is already there. No report returns a boolean column, so booleans are only tested through the macro and through value normalising. Result values are normalised the same way for every engine, so the renderers never see a driver type: `Decimal` becomes an `int` (whole) or a `float` (with decimals), a timestamp becomes `YYYY-MM-DD HH:MM:SS` text, a `bool` becomes `1`/`0`, and `bytes` becomes text.

Two changes were made to the original SQLite reports so they run everywhere: the derived table in `duplicate_customers` got an alias (PostgreSQL and MariaDB require one) and a column alias `offset` in `cohort_retention` became `month_offset` (`OFFSET` is reserved in PostgreSQL). SQLite results are unchanged: the existing 106 tests pass as they were.

The server schemas are `schema.postgres.sql` and `schema.mariadb.sql`, next to the SQLite `schema.sql`. They use real `DATE` and timestamp types, `BIGINT` for cents (a 32-bit column would overflow on a line over about $21 million; a test with 12 billion cents checks all three engines agree), and table-level foreign keys. MariaDB tables are `utf8mb4_bin` and the PostgreSQL test database is created with `LC_COLLATE 'C'`, so text equality and sort order are byte-wise as in SQLite.

## Example output

All of this is real output from the seed-42 sample data. The full files are in `examples/`.

CSV, `report run monthly_revenue`:

```
month,orders,gross_usd,refunds_usd,net_usd
2024-01,5,319.00,0.00,319.00
2024-02,11,656.00,0.00,656.00
2024-03,12,1376.00,0.00,1376.00
2024-04,12,1032.00,96.00,936.00
```

Markdown, `report run top_customers -f markdown -p limit=3`:

```
| customer_id | name | city | orders | spend_usd | refunded_usd | net_usd |
| ---: | --- | --- | ---: | ---: | ---: | ---: |
| 207 | Cleo Oakes | Houston | 6 | 760.00 | 0.00 | 760.00 |
| 117 | Avery Frost | Galveston | 6 | 685.00 | 0.00 | 685.00 |
| 479 | Zion Thorn | Evanston | 4 | 679.00 | 0.00 | 679.00 |
```

Markdown, `report run cohort_retention` (first rows):

```
| cohort_month | customers | m0_pct | m1_pct | m2_pct | m3_pct |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2024-01 | 22 | 22.7 | 31.8 | 13.6 | 9.1 |
| 2024-02 | 29 | 13.8 | 13.8 | 0.0 | 10.3 |
| 2024-03 | 32 | 12.5 | 18.8 | 18.8 | 9.4 |
```

Markdown, `report run duplicate_customers` (first rows; the list includes chance matches among the random names, not only the planted ones):

```
| match_type | match_key | customer_ids | customers |
| --- | --- | --- | ---: |
| email | cleo.joyce315@example.com | 315,507 | 2 |
| email | finley.oakes96@example.com | 96,511 | 2 |
| email | kai.ives124@example.com | 124,501 | 2 |
```

HTML, `report run monthly_revenue -f html -o revenue.html`. The file has no scripts, links, images or fonts; the chart is inline SVG. A short excerpt of `examples/monthly_revenue.html`:

```
<h1>Monthly revenue</h1>
<p class="meta">18 rows &middot; from_date=1900-01-01, to_date=2999-12-31</p>
<svg viewBox="0 0 720 280" width="100%" role="img" aria-label="Bar chart of net_usd by month">
<rect x="69.4" y="205.6" width="25.0" height="4.4" fill="#2f6f8f"><title>2024-01: 319.00</title></rect>
<rect x="105.1" y="201.0" width="25.0" height="9.0" fill="#2f6f8f"><title>2024-02: 656.00</title></rect>
<tr><td>2024-01</td><td class="num">5</td><td class="num">319.00</td><td class="num">0.00</td><td class="num">319.00</td></tr>
```

## The slow query and its rewrite

`orders_in_month_slow` filters with `strftime('%Y-%m', o.created_at) = :month`. `orders_in_month_fast` filters with a range on the bare column. They return the same rows (the tests check every month of the sample data, plus month boundaries and date-only timestamps). SQLite's own query plan, `report explain ... -p month=2025-03`, before:

```
SCAN o USING INDEX idx_orders_created_at
SEARCH c USING INTEGER PRIMARY KEY (rowid=?)
CORRELATED SCALAR SUBQUERY 1
  SEARCH oi USING INDEX idx_order_items_order_id (order_id=?)
```

and after:

```
SEARCH o USING INDEX idx_orders_created_at (created_at>? AND created_at<?)
SEARCH c USING INTEGER PRIMARY KEY (rowid=?)
CORRELATED SCALAR SUBQUERY 1
  SEARCH oi USING INDEX idx_order_items_order_id (order_id=?)
```

Before, SQLite walks every order (`SCAN`; it reads them in index order only because of the `ORDER BY`) and applies the month test to each. After, it does a range `SEARCH` on `idx_orders_created_at`, so it only visits that month's orders. The tests assert exactly this difference in the plan.

The same pair on the other two engines (the sample database, `-p month=2025-03`; full files in `examples/plan_*_postgres.txt` and `examples/plan_*_mariadb.txt`). PostgreSQL 16.15, slow then fast:

```
->  Seq Scan on orders o
      Filter: (to_char(created_at, 'YYYY-MM'::text) = '2025-03'::text)

->  Index Scan using idx_orders_created_at on orders o
      Index Cond: ((created_at >= ('2025-03-01'::cstring)::date) AND (created_at < (('2025-03-01'::cstring)::date + '1 mon'::interval)))
```

MariaDB 13.0.2, slow then fast (`report explain` prints one line per table):

```
o: type=ALL key=None rows=1086 (Using where; Using filesort)
o: type=range key=idx_orders_created_at rows=99 (Using index condition)
```

Each engine has its own plan assertion in `tests/test_engine_slow_fast.py`. The PostgreSQL planner may show an `Index Scan` or a `Bitmap Index Scan` for the fast version depending on its statistics (the loader runs `ANALYZE` first); the test accepts the plain index scan and checks the index range condition. No timing numbers are claimed: the sample database is too small for them to mean anything.

## How parameters are kept safe

- Parameters are validated by type first (a date must be a real `YYYY-MM-DD`, a month `YYYY-MM`, an int within its bounds, text at most 200 characters), then passed to the driver as bound values (`:name` for SQLite, `%(name)s` for psycopg and PyMySQL). They are never pasted into the SQL. The only SQL text the program builds besides macro expansion is the fixed `EXPLAIN` prefix. Injection strings were run against all three engines and the tables were counted before and after.
- Read-only by default, in layers, per engine:
  - SQLite: the file is opened with `mode=ro` and the session sets `PRAGMA query_only`.
  - PostgreSQL: the session default is `default_transaction_read_only = on` and every transaction is started as `BEGIN READ ONLY` (psycopg `read_only`). Each report ends with a rollback.
  - MariaDB: the session is `SET SESSION TRANSACTION READ ONLY` and every report runs inside `START TRANSACTION READ ONLY`, then a rollback.
  - A report file that tries to write (`UPDATE`, `INSERT`, `DELETE`, `DROP`, `CREATE`, `ALTER`) is refused by the database itself on all three, and the tests show the data unchanged. A test also switches the session default back to read-write and shows the write is still refused, and another checks each layer on its own, so removing one is noticed.
  - A report must be exactly one statement. SQLite refuses a second one by itself; PostgreSQL only does so when parameters are bound, so the program checks it for every engine.
  - These are safety nets for the report files in this folder, not a security boundary. For a real database give the program a SELECT-only database user as well; the MariaDB tests include such a user and show a write is refused by its privileges too. The PostgreSQL tests use one role (the owner of the test database), so a SELECT-only PostgreSQL role was not tried.
- Every `:name` in a report file must be declared in its header and vice versa, or the file is refused. An unknown macro or one with the wrong number of arguments is refused when the file loads, checked for all three engines.

## Tests

`python -m pytest` runs 400 tests. The 106 original tests are unchanged and run on SQLite. The rest:

| Group | Count | Runs on |
|---|---|---|
| Original 106 (reports by hand-computed values, injection, read-only, render, CLI, generator, slow/fast) | 106 | SQLite |
| Dialect and URL tests: every macro per engine, placeholders, `%` escaping, quoting, value normalising, URL parsing, missing driver | 72 | no database |
| Per-engine tests (same test, once per engine): hand-computed values for all ten reports, edge dates, empty database, read-only layers and refused writes, injection, slow/fast plans, CLI, `init-db`, the shipped examples | 63 on SQLite, 64 on PostgreSQL, 64 on MariaDB | each engine |
| Cross-engine tests (one test, all three engines): every report with 1 to 22 parameter sets on the 1086-order sample must be identical to the digit, type and order; rendered CSV, Markdown and HTML byte-identical; the loaded data hashes to the same digest; a MariaDB SELECT-only user | 31 | all three together |

Five tests pin down where the engines intentionally differ (they are named `test_difference_*`): a date-only timestamp is kept as text by SQLite and becomes midnight in PostgreSQL and MariaDB; `lower()` folds `ÉLISE` only in PostgreSQL and MariaDB; PostgreSQL refuses a NUL byte in a text parameter; an invalid date is stored by SQLite and refused by the others; and MariaDB's usual default collation ignores case, which the schema pins away.

The two servers are not assumed: the suite creates ONE throwaway database per server with its own users, and drops them when the run ends, also when tests fail (see below). A server that cannot be reached skips its tests; set `SQLREPORT_REQUIRE_BACKENDS=postgres,mariadb` to make that a failure instead (that is how the counts above were produced).

### Running the PostgreSQL and MariaDB tests locally

```bash
.venv/bin/python scripts/local-mariadb.py start     # own MariaDB in .local-db/ (git-ignored), 127.0.0.1:3308, own socket
export SQLREPORT_REQUIRE_BACKENDS=postgres,mariadb
.venv/bin/python -m pytest -v                       # header shows the engine versions
.venv/bin/python scripts/local-mariadb.py stop
```

PostgreSQL is expected at a unix socket in `/tmp` as your own role, which must be allowed to `CREATE ROLE` and `CREATE DATABASE`. Everything is configurable with `SQLREPORT_PG_ADMIN_URL`, `SQLREPORT_MARIADB_ADMIN_URL`, `SQLREPORT_MARIADB_HOST` and `SQLREPORT_MARIADB_PORT` (`tests/engines.py` documents them). Test databases and users are named `sqlreport_kit_test_*`, `sqlreport_kit_role_*`, `sqlreport_kit_rw_*` and `sqlreport_kit_ro_*`, and every `DROP` checks the name first. If a run is killed hard, `python -m tests.engines cleanup` drops what it left. `scripts/local-mariadb.py` never reads the system `my.cnf`, never installs anything and `destroy` deletes its data folder.

### Continuous integration (not run)

`.github/workflows/tests.yml` starts `postgres:16` and `mariadb:11.4` service containers on a GitHub Actions runner and runs the same suite with `SQLREPORT_REQUIRE_BACKENDS=postgres,mariadb`, so a missing server fails the job instead of skipping tests. **That file has never run.** Nothing was pushed, no GitHub repository was created, and the container versions are not the ones used locally (PostgreSQL 16.15, MariaDB 13.0.2). Treat it as an untested draft until it has a green run.

### Mutation check

`scripts/mutation-check.py` breaks the code on purpose, one change at a time (59 changes, in the dialect, the three backends, the URL parser, the loader and the command line), and runs the suite against the real servers. Phase 1 runs only the engine tests; a mutant that survives is run against the whole suite. Each phase has a hard time limit; on timeout the whole process group is killed, and a timeout counts as not killed. Result of the last run: **57 of 59 killed, 2 survived, 0 timeouts, 0 errors.** 44 were killed by the engine tests on the real PostgreSQL and MariaDB servers (and SQLite); 13 were killed only by tests that need no database (macro text, `%` escaping, value normalising, URL parsing). One of the 57 (`split-args-nesting`) was killed by a start-up error (the reports could not be loaded) rather than by an assertion. The two survivors:

- `quote-escape-ignored` is an equivalent mutant: in `dialect.py` a doubled quote inside a string literal is read as two adjacent strings instead of one, which gives the same output. It does not show a gap in the tests.
- `pg-ignores-password` (PostgreSQL connections never send the password) survived because the local PostgreSQL trusts its unix socket, so a missing password is invisible. This is a real gap: PostgreSQL password handling was not verified.

An earlier run of the same script ended 56 killed, 2 survived and 1 error; the error was a typo in one mutant (fixed), and the mutant it hid was killed in the next run. Between the two runs I added tests for the doubled-quote case; the mutant still survives because it is equivalent. Run it yourself with `.venv/bin/python scripts/mutation-check.py` (about 25 minutes; `--list`, `--only ID` and `--timeout SECONDS` exist).

## Limits

- Three engines, each tried in one version only: SQLite 3.54.1, PostgreSQL 16.15 (Homebrew) and MariaDB 13.0.2 (Homebrew), with Python 3.11.14, psycopg 3.3.6 and PyMySQL 1.2.3. By SQLite's documentation the window-function reports need 3.25 or newer and `duplicate_customers` needs 3.44 or newer; older SQLite, PostgreSQL and MariaDB versions were not tried. `mysql://` URLs are accepted but MySQL itself was never run.
- Text handling is pinned, not general: the PostgreSQL test database uses `LC_COLLATE 'C'` and the MariaDB tables `utf8mb4_bin`. With a case-insensitive or locale collation (MariaDB's usual default, or `en_US.UTF-8` in PostgreSQL) the city filter, `GROUP BY` on text and sort order can differ from SQLite; that was not tested. `lower()` is ASCII-only in SQLite and Unicode-aware elsewhere (a test pins this).
- Dates: PostgreSQL and MariaDB use `TIMESTAMP`/`DATETIME` without time zone, SQLite stores text. No time zone conversion is tested. A SQLite file with date text in other formats gives different answers from the server engines, which refuse such values.
- Fictional data. The reports were never run against a client's database, schema or data volume, and no performance claims are made.
- Money is integer cents in one currency. Revenue counts completed orders only; refunds count in the month they are paid out, not the month of the sale. Cohort retention is not adjusted for cohorts younger than three months.
- The CSV output is not escaped against spreadsheet formula injection (a text cell starting with `=` is written as is). Do not open CSVs of untrusted text in a spreadsheet without checking.
- Not production code: no authentication layer of its own, no scheduling, no caching, no statement timeout, whole results are held in memory. The read-only layers are safety nets, not a security boundary (see "How parameters are kept safe").
- One connection at a time, no connection pool, no concurrent writers while a report runs.

## What this does not prove

- **No client data.** Everything ran on the fictional online shop generated by `init-db`. Nothing here shows the reports fit anyone's real tables, names, null patterns or dirty data.
- **No managed cloud databases.** Not run on Amazon RDS or Aurora, Google Cloud SQL, Azure, Supabase, Neon or any other hosted service. Their TLS, connection poolers (pgBouncer, Supavisor), restricted roles and default settings can change behaviour; none of that was exercised.
- **Only local, trusting connections.** PostgreSQL was reached over a unix socket whose local setup trusts the user, so password and SCRAM authentication and TLS were not exercised on PostgreSQL (a wrong password was tested on MariaDB only). MariaDB was reached over TCP on 127.0.0.1 without TLS.
- **No large tables and no performance tuning.** About 3,700 rows in total (512 customers, 30 products, 1086 orders, 2051 order lines, 53 refunds). The query plans show which index is used on a 1086-order table; they say nothing about timing, cost on millions of rows, partitioning or index choice at scale.
- **No replication, clustering or failover.** One server of each kind, one connection.
- **No engine versions other than the local ones** listed under Limits. In particular nothing older than PostgreSQL 16 or newer than 16.15, and MariaDB 10.x or 11.x LTS releases were not run, even though the GitHub Actions file names `mariadb:11.4`.
- **The GitHub Actions file has not run.** `.github/workflows/tests.yml` starts `postgres:16` and `mariadb:11.4` service containers and runs the same suite with `SQLREPORT_REQUIRE_BACKENDS` set. It was never executed on GitHub, so its service settings, health checks and connection strings are unchecked, and the container versions differ from the ones the suite ran against here.
- **Not a security review.** No penetration test, no check of what a hostile report *file* could do beyond the write attempts listed above.

## License

MIT, see `LICENSE`.
