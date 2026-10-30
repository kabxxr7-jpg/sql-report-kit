# sql-report-kit

> **Status:** a proof project (106 tests, run locally against a tiny fixed dataset and a generated fictional database). Not used in production or by any client, and never run against a client's database. See Limits.

Ten documented, parameterized SQL reports for a small online shop, a command line that runs them safely, and output as CSV, Markdown or one self-contained HTML page with an inline bar chart. It is a starting point for "write me some SQL reports" and "a small dashboard from our data" jobs: the reports are plain `.sql` files you can read, change and re-test.

## Quick start

Python 3.11 and SQLite from the standard library. Only the tests need an extra package.

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

## The sample data

`init-db` builds a fictional shop: customers 512, products 30, orders 1086, order_items 2051, refunds 53. Names are random first and last name combinations (not real people), emails use `example.com`, dates run from 2024-01-01 to 2025-06-30, and money is stored as integer cents. The same seed gives identical rows every time (a test compares a hash of every table). The generator plants things the reports should find: a few duplicate customers, four products that never sell, cancelled and pending orders, and partial and full refunds.

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

Before, SQLite walks every order (`SCAN`; it reads them in index order only because of the `ORDER BY`) and applies the month test to each. After, it does a range `SEARCH` on `idx_orders_created_at`, so it only visits that month's orders. The tests assert exactly this difference in the plan. No timing numbers are claimed: the sample database is too small for them to mean anything.

## How parameters are kept safe

- Parameters are validated by type first (a date must be a real `YYYY-MM-DD`, a month `YYYY-MM`, an int within its bounds, text at most 200 characters), then passed to SQLite as bound values. They are never pasted into the SQL. The only SQL text the program builds is the fixed `EXPLAIN QUERY PLAN` prefix.
- The database is opened read-only twice over: the file is opened with `mode=ro` and the session sets `PRAGMA query_only`. A report file that tries to write, or contains two statements, fails and changes nothing.
- Every `:name` in a report file must be declared in its header and vice versa, or the file is refused.

## Tests

`python -m pytest` runs 106 tests. Every report's output is checked against numbers worked out by hand from a tiny fixed dataset (`tests/tiny_data.sql`); the cohort report has its own dataset where every retention column differs and the month and year boundaries are crossed. The rest cover: injection strings in parameters, read-only enforcement, empty results, CSV, Markdown and HTML rendering (including escaping and "no external assets"), the slow/fast pair, generator determinism and consistency, and the command line (exit codes 0 ok, 1 runtime or database error, 2 bad usage or parameters).

## Limits

- SQLite only. The SQL uses SQLite functions (`strftime`, `date`, `group_concat(... ORDER BY ...)`) and would need porting for another database.
- Tested on SQLite 3.51.0 and Python 3.11.14 only. By SQLite's documentation the window-function reports need 3.25 or newer and `duplicate_customers` needs 3.44 or newer; older versions were not tried.
- Fictional data. The reports were never run against a client's database, schema or data volume, and no performance claims are made.
- Money is integer cents in one currency. Revenue counts completed orders only; refunds count in the month they are paid out, not the month of the sale. Cohort retention is not adjusted for cohorts younger than three months.
- The CSV output is not escaped against spreadsheet formula injection (a text cell starting with `=` is written as is). Do not open CSVs of untrusted text in a spreadsheet without checking.
- Not production code: no authentication, no scheduling, no caching, whole results are held in memory, and it reads a local file.

## License

MIT, see `LICENSE`.
