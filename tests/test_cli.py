import re
import subprocess
import sys

from sql_report_kit.cli import main
from tests.conftest import ROOT


def run_cli(capsys, *args):
    code = main(list(args))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_list_shows_all_ten_reports(capsys):
    code, out, _ = run_cli(capsys, "list")
    assert code == 0 and len(out.strip().splitlines()) == 10
    assert "monthly_revenue" in out and "orders_in_month_fast" in out


def test_show_prints_description_and_parameters(capsys):
    code, out, _ = run_cli(capsys, "show", "top_customers")
    assert code == 0
    assert "limit (int:1..1000, default '10')" in out and "city (text" in out


def test_run_csv_to_stdout_with_row_count_on_stderr(capsys, tiny_db):
    code, out, err = run_cli(capsys, "run", "monthly_revenue", "--db", str(tiny_db))
    assert code == 0
    assert out.splitlines()[0] == "month,orders,gross_usd,refunds_usd,net_usd"
    assert "2024-05,0,0.00,10.00,-10.00" in out
    assert "5 rows" in err


def test_run_markdown_and_html_to_files(capsys, tiny_db, tmp_path):
    md, html = tmp_path / "r.md", tmp_path / "r.html"
    assert run_cli(capsys, "run", "monthly_revenue", "--db", str(tiny_db), "-f", "markdown", "-o", str(md))[0] == 0
    assert run_cli(capsys, "run", "monthly_revenue", "--db", str(tiny_db), "-f", "html", "-o", str(html))[0] == 0
    assert md.read_text().startswith("| month | orders | gross_usd")
    page = html.read_text()
    assert "<svg" in page and "Monthly revenue" in page and "to_date=2999-12-31" in page


def test_run_with_parameters(capsys, tiny_db):
    code, out, _ = run_cli(capsys, "run", "top_customers", "--db", str(tiny_db), "-p", "limit=1", "-p", "city=Austin")
    assert code == 0 and out.splitlines()[1].startswith("1,Ann Lee,Austin,3,80.00,10.00,70.00")


def test_empty_result_exits_zero_with_a_header(capsys, tiny_db):
    code, out, err = run_cli(capsys, "run", "monthly_revenue", "--db", str(tiny_db), "-p", "from_date=2030-01-01")
    assert code == 0 and out == "month,orders,gross_usd,refunds_usd,net_usd\n" and "0 rows" in err


def test_usage_errors_exit_2(capsys, tiny_db):
    assert run_cli(capsys, "run", "no_such_report", "--db", str(tiny_db))[0] == 2
    assert run_cli(capsys, "run", "orders_in_month_fast", "--db", str(tiny_db))[0] == 2          # month is required
    assert run_cli(capsys, "run", "monthly_revenue", "--db", str(tiny_db), "-p", "bogus=1")[0] == 2
    assert run_cli(capsys, "run", "monthly_revenue", "--db", str(tiny_db), "-f", "xml")[0] == 2   # argparse error


def test_explain_prints_the_plan(capsys, tiny_db):
    code, out, _ = run_cli(capsys, "explain", "orders_in_month_fast", "--db", str(tiny_db), "-p", "month=2024-03")
    assert code == 0 and "idx_orders_created_at (created_at>? AND created_at<?)" in out


def test_init_db_then_run(capsys, tmp_path):
    db = tmp_path / "new.db"
    code, out, _ = run_cli(capsys, "init-db", "--db", str(db))
    assert code == 0 and "customers 512" in out
    assert run_cli(capsys, "init-db", "--db", str(db))[0] == 1               # refuses to overwrite
    assert run_cli(capsys, "init-db", "--db", str(db), "--force")[0] == 0
    code, out, _ = run_cli(capsys, "run", "cohort_retention", "--db", str(db), "-f", "markdown")
    assert code == 0 and re.search(r"\| 2024-01 \| \d+ \|", out)


def test_the_report_script_and_module_entry_points_work(tiny_db):
    for command in ([sys.executable, str(ROOT / "report")], [sys.executable, "-m", "sql_report_kit"]):
        result = subprocess.run(command + ["list"], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 0 and "monthly_revenue" in result.stdout
