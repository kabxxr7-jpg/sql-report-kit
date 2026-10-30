import pytest

from sql_report_kit.params import ParamError, parse_param_args, resolve_params
from sql_report_kit.queries import QueryFileError, parse_query

EXPECTED = {
    "cohort_retention", "duplicate_customers", "monthly_revenue", "orders_in_month_fast", "orders_in_month_slow",
    "products_never_sold", "refunds_by_product", "repeat_purchase_rate", "running_totals", "top_customers",
}


def test_all_ten_reports_load_and_are_documented(queries):
    assert set(queries) == EXPECTED
    for query in queries.values():
        assert query.title and query.description, query.name
        for param in query.params:
            assert param.help, (query.name, param.name)


def test_declared_params_match_placeholders_in_every_file(queries):
    # parse_query raises QueryFileError on any mismatch, so loading already proved it; assert a few facts too.
    assert [p.name for p in queries["top_customers"].params] == ["limit", "city", "from_date", "to_date"]
    assert queries["orders_in_month_slow"].params[0].required


def test_a_placeholder_that_is_not_declared_is_rejected(tmp_path):
    bad = tmp_path / "bad.sql"
    bad.write_text("-- title: Bad\nSELECT :undeclared;\n")
    with pytest.raises(QueryFileError, match="do not match"):
        parse_query(bad)


def test_a_declared_param_that_is_never_used_is_rejected(tmp_path):
    bad = tmp_path / "bad.sql"
    bad.write_text("-- title: Bad\n-- param: x | int | 1 | unused\nSELECT 1;\n")
    with pytest.raises(QueryFileError, match="do not match"):
        parse_query(bad)


def test_colons_inside_strings_and_comments_are_not_placeholders(tmp_path):
    ok = tmp_path / "ok.sql"
    ok.write_text("-- title: Fine\n-- a comment with :not_a_param\nSELECT '10:30:00 :nope' AS t;\n")
    assert parse_query(ok).params == ()


def test_defaults_are_applied(queries):
    values = resolve_params(queries["top_customers"], {})
    assert values == {"limit": 10, "city": "", "from_date": "1900-01-01", "to_date": "2999-12-31"}


@pytest.mark.parametrize("raw, message", [
    ({"from_date": "2024-13-01"}, "not a real calendar date"),
    ({"from_date": "2024-02-30"}, "not a real calendar date"),
    ({"from_date": "20240101"}, "expected a date"),
    ({"from_date": "2024-01-01' OR '1'='1"}, "expected a date"),
    ({"limit": "0"}, "between 1 and 1000"),
    ({"limit": "1001"}, "between 1 and 1000"),
    ({"limit": "ten"}, "whole number"),
    ({"limit": "1; DROP TABLE customers"}, "whole number"),
    ({"city": "x" * 201}, "longer than 200"),
    ({"nonsense": "1"}, "unknown parameter"),
])
def test_bad_values_are_rejected_before_any_sql_runs(queries, raw, message):
    with pytest.raises(ParamError, match=message):
        resolve_params(queries["top_customers"], raw)


@pytest.mark.parametrize("value", ["2025-3", "2025-00", "2025-13", "March", "2025-03-01", "2025-03'; --"])
def test_month_must_be_yyyy_mm(queries, value):
    with pytest.raises(ParamError, match="expected a month"):
        resolve_params(queries["orders_in_month_fast"], {"month": value})


def test_required_param_must_be_given(queries):
    with pytest.raises(ParamError, match="month is required"):
        resolve_params(queries["orders_in_month_fast"], {})


def test_parse_param_args():
    assert parse_param_args(["a=1", "b=x=y"]) == {"a": "1", "b": "x=y"}
    with pytest.raises(ParamError, match="key=value"):
        parse_param_args(["novalue"])
    with pytest.raises(ParamError, match="more than once"):
        parse_param_args(["a=1", "a=2"])
