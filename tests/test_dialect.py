"""The dialect layer needs no database: macros, placeholders, quoting, value normalisation, statement splitting."""

import re
from datetime import date, datetime
from decimal import Decimal

import pytest

from sql_report_kit.dialect import (
    DIALECTS, MACRO_NAMES, MacroError, bind_placeholders, split_args, split_statements, strip_comments_and_expand,
    used_macros,
)
from sql_report_kit.queries import QueryFileError, load_queries, parse_query

SQLITE, POSTGRES, MARIADB = DIALECTS["sqlite"], DIALECTS["postgres"], DIALECTS["mariadb"]

# macro call -> what each engine receives. Spelled out so a change to any engine's SQL shows up as a failing line.
MACRO_CASES = [
    ("{{month_key(o.created_at)}}",
     "strftime('%Y-%m', o.created_at)", "to_char(o.created_at, 'YYYY-MM')", "DATE_FORMAT(o.created_at, '%Y-%m')"),
    ("{{year_of(x)}}",
     "CAST(strftime('%Y', x) AS INTEGER)", "CAST(EXTRACT(YEAR FROM x) AS INTEGER)", "YEAR(x)"),
    ("{{month_of(x)}}",
     "CAST(strftime('%m', x) AS INTEGER)", "CAST(EXTRACT(MONTH FROM x) AS INTEGER)", "MONTH(x)"),
    ("{{month_index(x)}}",
     "(CAST(strftime('%Y', x) AS INTEGER) * 12 + CAST(strftime('%m', x) AS INTEGER))",
     "(CAST(EXTRACT(YEAR FROM x) AS INTEGER) * 12 + CAST(EXTRACT(MONTH FROM x) AS INTEGER))",
     "(YEAR(x) * 12 + MONTH(x))"),
    ("{{day_start(:d)}}", "date(:d)", "CAST(:d AS date)", "CAST(:d AS DATE)"),
    ("{{day_after(:d)}}",
     "date(:d, '+1 day')", "(CAST(:d AS date) + INTERVAL '1 day')", "DATE_ADD(CAST(:d AS DATE), INTERVAL 1 DAY)"),
    ("{{month_start(:m)}}",
     "date(:m || '-01')", "CAST(CAST(:m AS text) || '-01' AS date)", "STR_TO_DATE(CONCAT(:m, '-01'), '%Y-%m-%d')"),
    ("{{month_after(:m)}}",
     "date(:m || '-01', '+1 month')",
     "(CAST(CAST(:m AS text) || '-01' AS date) + INTERVAL '1 month')",
     "DATE_ADD(STR_TO_DATE(CONCAT(:m, '-01'), '%Y-%m-%d'), INTERVAL 1 MONTH)"),
    ("{{concat(a, '|', lower(b))}}", "(a || '|' || lower(b))", "(a || '|' || lower(b))", "CONCAT(a, '|', lower(b))"),
    ("{{string_agg(id, ',', id)}}",
     "group_concat(id, ',' ORDER BY id)", "string_agg(CAST(id AS TEXT), ',' ORDER BY id)",
     "GROUP_CONCAT(id ORDER BY id SEPARATOR ',')"),
    ("{{cast_int(ROUND(AVG(v), 0))}}",
     "CAST(ROUND(AVG(v), 0) AS INTEGER)", "CAST(ROUND(AVG(v), 0) AS BIGINT)", "CAST(ROUND(AVG(v), 0) AS SIGNED)"),
    ("{{limit(:n)}}", "LIMIT :n", "LIMIT :n", "LIMIT :n"),
    ("{{limit(10, 20)}}", "LIMIT 10 OFFSET 20", "LIMIT 10 OFFSET 20", "LIMIT 10 OFFSET 20"),
    ("{{true}}", "1", "TRUE", "TRUE"),
    ("{{false}}", "0", "FALSE", "FALSE"),
]


@pytest.mark.parametrize("call, sqlite, postgres, mariadb", MACRO_CASES, ids=[c[0].split("(")[0].strip("{}") for c in MACRO_CASES])
def test_every_macro_expands_to_the_expected_sql_per_engine(call, sqlite, postgres, mariadb):
    assert strip_comments_and_expand(call, SQLITE) == sqlite
    assert strip_comments_and_expand(call, POSTGRES) == postgres
    assert strip_comments_and_expand(call, MARIADB) == mariadb


def test_every_dialect_knows_every_macro_and_every_macro_is_tested():
    for dialect in DIALECTS.values():
        assert dialect.known_macros() == set(MACRO_NAMES), dialect.name
    assert {c[0].split("(")[0].strip("{}") for c in MACRO_CASES} == set(MACRO_NAMES)


def test_macros_nest_and_arguments_may_contain_commas_parentheses_and_quotes():
    sql = "{{cast_int({{month_of(coalesce(a, 'x,y)'))}})}}"
    assert strip_comments_and_expand(sql, POSTGRES) == (
        "CAST(CAST(EXTRACT(MONTH FROM coalesce(a, 'x,y)')) AS INTEGER) AS BIGINT)"
    )
    assert split_args("a, f(b, c), 'd,e', \"g,h\"") == ["a", "f(b, c)", "'d,e'", '"g,h"']
    assert split_args("") == []


@pytest.mark.parametrize("bad, message", [
    ("{{nope(x)}}", "unknown macro"),
    ("{{month_key()}}", "wrong number of arguments"),
    ("{{month_key(a, b)}}", "wrong number of arguments"),
    ("{{month_key(a}}", "closing parenthesis"),
    ("{{month_key(a) ", "expected }}"),
    ("{{ }}", "malformed"),
])
def test_bad_macros_are_rejected(bad, message):
    with pytest.raises(MacroError, match=message):
        strip_comments_and_expand(bad, SQLITE)


def test_macro_text_inside_strings_and_comments_is_left_alone():
    sql = "SELECT '{{not_a_macro}}' -- {{nor_this}}\n, /* {{or_this}} */ 1"
    assert used_macros(sql) == set()
    assert strip_comments_and_expand(sql, SQLITE).replace("\n", " ").split() == ["SELECT", "'{{not_a_macro}}'", ",", "1"]


def test_unknown_macro_in_a_report_file_is_a_file_error(tmp_path):
    bad = tmp_path / "bad.sql"
    bad.write_text("-- title: Bad\nSELECT {{no_such_macro(1)}};\n")
    with pytest.raises(QueryFileError, match="unknown macro"):
        parse_query(bad)


def test_wrong_macro_arguments_in_a_report_file_are_caught_at_load_for_every_engine(tmp_path):
    bad = tmp_path / "bad.sql"
    bad.write_text("-- title: Bad\nSELECT {{month_key(a, b)}};\n")
    with pytest.raises(QueryFileError, match="wrong number of arguments"):
        parse_query(bad)


# --- placeholders and the % character -----------------------------------------------------------------------


def test_named_placeholders_per_driver():
    sql = "SELECT * FROM t WHERE a = :a AND b = :b AND c = :a"
    assert SQLITE.compile(sql, {"a": 1, "b": 2}).sql == sql
    assert POSTGRES.compile(sql, {"a": 1, "b": 2}).sql == "SELECT * FROM t WHERE a = %(a)s AND b = %(b)s AND c = %(a)s"
    assert MARIADB.compile(sql, {"a": 1, "b": 2}).sql == POSTGRES.compile(sql, {"a": 1, "b": 2}).sql
    assert POSTGRES.compile(sql, {"a": 1, "b": 2, "unused": 3}).params == {"a": 1, "b": 2}


def test_a_missing_value_is_an_error_not_a_silent_null():
    for dialect in DIALECTS.values():
        with pytest.raises(MacroError, match="no value for parameter"):
            dialect.compile("SELECT :x", {})


def test_colons_in_strings_comments_and_casts_are_not_placeholders():
    sql = "SELECT '10:30:00 :nope', x::int, \":quoted\" -- :comment\n FROM t WHERE y = :real"
    compiled = POSTGRES.compile(sql, {"real": 1})
    assert compiled.params == {"real": 1}
    assert "'10:30:00 :nope'" in compiled.sql and "x::int" in compiled.sql and '":quoted"' in compiled.sql
    assert "%(real)s" in compiled.sql and ":comment" not in compiled.sql


def test_percent_is_doubled_for_pyformat_drivers_only():
    sql = "SELECT '50%' AS a, 7 % 3 AS b, :p AS c"
    assert SQLITE.compile(sql, {"p": 1}).sql == sql
    assert POSTGRES.compile(sql, {"p": 1}).sql == "SELECT '50%%' AS a, 7 %% 3 AS b, %(p)s AS c"
    assert MARIADB.compile(sql, {"p": 1}).sql == POSTGRES.compile(sql, {"p": 1}).sql


def test_a_value_that_looks_like_sql_stays_a_value():
    payload = "x'; DROP TABLE customers; --"
    for dialect in DIALECTS.values():
        compiled = dialect.compile("SELECT * FROM t WHERE a = :a", {"a": payload})
        assert compiled.params == {"a": payload}
        assert "DROP" not in compiled.sql


# --- quoting, booleans, statements -------------------------------------------------------------------------


def test_identifier_quoting_per_engine_including_embedded_quotes():
    assert SQLITE.quote_identifier("order") == '"order"'
    assert POSTGRES.quote_identifier("order") == '"order"'
    assert MARIADB.quote_identifier("order") == "`order`"
    assert SQLITE.quote_identifier('we"ird') == '"we""ird"'
    assert MARIADB.quote_identifier("we`ird") == "`we``ird`"


def test_split_statements_ignores_semicolons_in_strings_and_comments():
    script = "INSERT INTO t VALUES ('a;b'); -- trailing; comment\nINSERT INTO t VALUES (\"x;y\");\n  ;  SELECT 1"
    assert split_statements(script) == ["INSERT INTO t VALUES ('a;b')", 'INSERT INTO t VALUES ("x;y")', "SELECT 1"]
    assert split_statements("  ;; ") == []


def test_bind_placeholders_reports_names_in_order_of_first_use():
    sql, used = bind_placeholders("SELECT :b, :a, :b", POSTGRES)
    assert used == ["b", "a"] and sql == "SELECT %(b)s, %(a)s, %(b)s"


# --- result values ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw, expected", [
    (Decimal("3500"), 3500),
    (Decimal("-1000"), -1000),
    (Decimal("100.0"), 100.0),
    (Decimal("33.3"), 33.3),
    (Decimal("0.0"), 0.0),
    (True, 1),
    (False, 0),
    (datetime(2024, 3, 2, 15, 0, 0), "2024-03-02 15:00:00"),
    (datetime(2024, 3, 2, 0, 0, 0), "2024-03-02 00:00:00"),
    (date(2024, 1, 31), "2024-01-31"),
    (b"1,4", "1,4"),
    (bytearray(b"x"), "x"),
    (None, None),
    ("text", "text"),
    (7, 7),
    (2.5, 2.5),
])
def test_normalize_value_makes_every_driver_look_like_sqlite(raw, expected):
    got = SQLITE.normalize_value(raw)
    assert got == expected and type(got) is type(expected)


def test_normalising_keeps_int_and_float_apart():
    # a rounded percentage that happens to be whole stays a float; a count that arrives as a Decimal becomes an int
    assert type(MARIADB.normalize_value(Decimal("100.0"))) is float
    assert type(MARIADB.normalize_value(Decimal("12"))) is int
    assert POSTGRES.normalize_row((Decimal("5"), Decimal("5.5"), date(2024, 1, 1))) == (5, 5.5, "2024-01-01")


# --- every shipped report compiles for every engine ----------------------------------------------------------


@pytest.mark.parametrize("engine", list(DIALECTS))
def test_all_ten_reports_compile_cleanly_for_each_engine(engine):
    dialect = DIALECTS[engine]
    for name, query in load_queries().items():
        values = {p.name: "2025-03" if p.name == "month" else 1 for p in query.params}
        compiled = dialect.compile(query.sql, values)
        assert "{{" not in compiled.sql and "}}" not in compiled.sql, name
        assert set(compiled.params) == {p.name for p in query.params}, name
        assert "--" not in compiled.sql, name        # header comments never reach the server
        assert len(split_statements(compiled.sql)) == 1, name


def test_the_engine_specific_functions_appear_only_in_the_dialect_not_in_the_report_files():
    for name, query in load_queries().items():
        for fragment in ("strftime", "to_char", "DATE_FORMAT", "group_concat", "string_agg", "GROUP_CONCAT", "STR_TO_DATE", "INTERVAL"):
            code = "\n".join(line for line in query.sql.splitlines() if not line.strip().startswith("--"))
            code = re.sub(r"\{\{.*?\}\}", "", code)        # what is inside a macro call is the dialect's business
            assert fragment not in code, (name, fragment)
