import re

from sql_report_kit.queries import Query
from sql_report_kit.render import format_cents, to_csv, to_html, to_markdown


def make_query(chart=("month", "net_cents"), title="Monthly revenue", description="d"):
    return Query(name="t", title=title, description=description, params=(), chart=chart, sql="")


COLUMNS = ["month", "orders", "net_cents"]
ROWS = [("2024-01", 2, 3500), ("2024-02", 2, 4000), ("2024-05", 0, -1000)]


def test_format_cents():
    assert [format_cents(c) for c in (0, 5, 100, 12345, -1000, -5)] == ["0.00", "0.05", "1.00", "123.45", "-10.00", "-0.05"]


def test_csv_shows_dollars_and_renames_money_columns():
    assert to_csv(COLUMNS, ROWS) == "month,orders,net_usd\n2024-01,2,35.00\n2024-02,2,40.00\n2024-05,0,-10.00\n"


def test_csv_quotes_commas_and_quotes_and_leaves_none_empty():
    text = to_csv(["name", "note"], [('Smith, "Jo"', None)])
    assert text == 'name,note\n"Smith, ""Jo""",\n'


def test_csv_empty_result_is_header_only():
    assert to_csv(COLUMNS, []) == "month,orders,net_usd\n"


def test_markdown_table_aligns_numbers_right():
    text = to_markdown(COLUMNS, ROWS)
    lines = text.splitlines()
    assert lines[0] == "| month | orders | net_usd |"
    assert lines[1] == "| --- | ---: | ---: |"
    assert lines[2] == "| 2024-01 | 2 | 35.00 |"


def test_markdown_escapes_pipes_and_newlines():
    text = to_markdown(["note"], [("a | b\nc",)])
    assert "a \\| b c" in text


def test_markdown_empty_result_says_so():
    text = to_markdown(COLUMNS, [])
    assert text.splitlines()[-1] == "_No rows._"


def test_html_is_self_contained_with_an_inline_svg_bar_chart():
    page = to_html(make_query(), COLUMNS, ROWS, {"from_date": "1900-01-01"})
    assert page.startswith("<!doctype html>")
    assert "<svg" in page and page.count("<rect") == len(ROWS)
    assert "<table>" in page and "35.00" in page
    assert "from_date=1900-01-01" in page and "3 rows" in page
    # no external assets of any kind: no links, scripts, images, fonts, imports or URLs
    for forbidden in ("http://", "https://", "<script", "<link", "src=", "href=", "url(", "@import", "<img"):
        assert forbidden not in page, forbidden


def test_html_bar_colors_and_heights_follow_the_values():
    page = to_html(make_query(), COLUMNS, ROWS)
    rects = re.findall(r'<rect x="[\d.]+" y="([\d.]+)" width="[\d.]+" height="([\d.]+)" fill="(#\w+)"', page)
    assert [fill for *_, fill in rects] == ["#2f6f8f", "#2f6f8f", "#b5483a"]    # the negative month is red
    heights = [float(h) for _, h, _ in rects]
    assert heights[1] > heights[0] > heights[2]      # 4000 > 3500 > |-1000|


def test_html_escapes_everything_that_came_from_the_database():
    evil = '<script>alert("x")</script>&"\''
    page = to_html(make_query(title="<b>T</b>", description=evil), ["month", "net_cents"], [(evil, 100)])
    assert "<script>" not in page and "<b>T</b>" not in page
    assert "&lt;script&gt;" in page and "&lt;b&gt;T&lt;/b&gt;" in page


def test_html_empty_result_has_a_message_and_no_chart():
    page = to_html(make_query(), COLUMNS, [])
    assert "No rows matched" in page and "<svg" not in page and "0 rows" in page


def test_html_without_a_chart_definition_has_no_svg():
    assert "<svg" not in to_html(make_query(chart=None), COLUMNS, ROWS)


def test_html_chart_is_capped_at_24_bars_with_a_note():
    rows = [(f"2024-{i:02d}", 1, i * 100) for i in range(1, 31)]
    page = to_html(make_query(), COLUMNS, rows)
    assert page.count("<rect") == 24
    assert "first 24 of 30 rows" in page
    assert page.count("<tr>") == 31      # all 30 rows are still in the table (+ the header row)


def test_html_chart_skipped_when_the_value_column_is_text():
    page = to_html(make_query(chart=("month", "label")), ["month", "label"], [("a", "x")])
    assert "<svg" not in page


def test_html_escapes_labels_in_the_rotated_label_layout_too():
    evil = '<img src=x onerror=alert(1)>'
    rows = [(f"2024-{i:02d}", 1, i * 100) for i in range(1, 12)] + [(evil, 1, 50)]    # 12 bars: labels are rotated
    page = to_html(make_query(), COLUMNS, rows)
    assert "rotate(-45" in page
    assert "<img" not in page and "&lt;img src=x onerror=alert(1)&gt;" in page
