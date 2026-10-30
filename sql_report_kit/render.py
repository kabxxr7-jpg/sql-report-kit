"""Turn query results into CSV, Markdown or one self-contained HTML page (no external assets).

Columns whose name ends in _cents hold integer cents; every output shows them as dollars in a column
renamed _usd (12345 -> 123.45). Everything else is shown as the database returned it.
"""

from __future__ import annotations

import csv
import html
import io
from typing import Iterable, Sequence

from .queries import Query

MAX_BARS = 24


def format_cents(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100}.{cents % 100:02d}"


def display_name(column: str) -> str:
    return column[: -len("_cents")] + "_usd" if column.endswith("_cents") else column


def format_value(column: str, value: object) -> str:
    if value is None:
        return ""
    if column.endswith("_cents") and isinstance(value, (int, float)):
        return format_cents(int(round(value)))
    return str(value)


def _is_numeric_column(rows: Sequence[Sequence[object]], index: int) -> bool:
    values = [row[index] for row in rows if row[index] is not None]
    return bool(values) and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values)


def to_csv(columns: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([display_name(c) for c in columns])
    for row in rows:
        writer.writerow([format_value(c, v) for c, v in zip(columns, row)])
    return buffer.getvalue()


def _md_cell(text: str) -> str:
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def to_markdown(columns: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    header = "| " + " | ".join(_md_cell(display_name(c)) for c in columns) + " |"
    aligns = ["---:" if _is_numeric_column(rows, i) else "---" for i in range(len(columns))]
    lines = [header, "| " + " | ".join(aligns) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(_md_cell(format_value(c, v)) for c, v in zip(columns, row)) + " |")
    if not rows:
        lines.append("")
        lines.append("_No rows._")
    return "\n".join(lines) + "\n"


def _svg_chart(query: Query, columns: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    if not query.chart or not rows:
        return ""
    label_col, value_col = query.chart
    if label_col not in columns or value_col not in columns:
        return ""
    li, vi = columns.index(label_col), columns.index(value_col)
    if not _is_numeric_column(rows, vi):
        return ""

    shown = rows[:MAX_BARS]
    values = [float(r[vi] or 0) for r in shown]
    labels = [str(r[li]) for r in shown]
    n = len(shown)

    width, height = 720, 280
    left, right, top, bottom = 64, 12, 14, 70
    plot_w, plot_h = width - left - right, height - top - bottom
    vmax, vmin = max(0.0, max(values)), min(0.0, min(values))
    span = (vmax - vmin) or 1.0

    def y_of(v: float) -> float:
        return top + (vmax - v) / span * plot_h

    baseline = y_of(0.0)
    band = plot_w / n
    bar_w = band * 0.7
    fmt = (lambda v: format_cents(int(round(v)))) if value_col.endswith("_cents") else (lambda v: f"{v:g}")

    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'aria-label="Bar chart of {html.escape(display_name(value_col))} by {html.escape(label_col)}">',
        f'<line x1="{left}" y1="{baseline:.1f}" x2="{width - right}" y2="{baseline:.1f}" stroke="#888" stroke-width="1"/>',
        f'<text x="{left - 6}" y="{top + 4}" text-anchor="end" font-size="11" fill="#555">{html.escape(fmt(vmax))}</text>',
        f'<text x="{left - 6}" y="{baseline + 4:.1f}" text-anchor="end" font-size="11" fill="#555">0</text>',
    ]
    if vmin < 0:
        parts.append(
            f'<text x="{left - 6}" y="{height - bottom + 4}" text-anchor="end" font-size="11" fill="#555">'
            f"{html.escape(fmt(vmin))}</text>"
        )
    for i, (label, value) in enumerate(zip(labels, values)):
        x = left + i * band + (band - bar_w) / 2
        y_top = min(y_of(value), baseline)
        bar_h = abs(y_of(value) - baseline)
        color = "#2f6f8f" if value >= 0 else "#b5483a"
        tip = html.escape(f"{label}: {fmt(value)}")
        parts.append(
            f'<rect x="{x:.1f}" y="{y_top:.1f}" width="{bar_w:.1f}" height="{max(bar_h, 0.5):.1f}" fill="{color}">'
            f"<title>{tip}</title></rect>"
        )
        cx, cy = x + bar_w / 2, height - bottom + 14
        if n > 10:
            parts.append(
                f'<text x="{cx:.1f}" y="{cy}" text-anchor="end" font-size="10" fill="#333" '
                f'transform="rotate(-45 {cx:.1f} {cy})">{html.escape(label)}</text>'
            )
        else:
            parts.append(
                f'<text x="{cx:.1f}" y="{cy}" text-anchor="middle" font-size="11" fill="#333">{html.escape(label)}</text>'
            )
    parts.append("</svg>")
    note = ""
    if len(rows) > MAX_BARS:
        note = f'<p class="meta">Chart shows the first {MAX_BARS} of {len(rows)} rows.</p>'
    return "\n".join(parts) + "\n" + note


_STYLE = (
    "body{font:15px/1.5 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;margin:2rem auto;max-width:960px;"
    "padding:0 1rem;color:#1d2530;background:#fff}h1{font-size:1.5rem;margin:0 0 .25rem}"
    ".desc{color:#445;margin:.25rem 0 1rem}.meta{color:#667;font-size:.85rem;margin:.25rem 0 1rem}"
    "table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{padding:.35rem .6rem;"
    "border-bottom:1px solid #dde3ea;text-align:left}th{background:#f3f6f9}td.num,th.num{text-align:right;"
    "font-variant-numeric:tabular-nums}.empty{color:#667;font-style:italic}svg{max-width:100%;height:auto;margin:.5rem 0 1rem}"
)


def to_html(
    query: Query,
    columns: Sequence[str],
    rows: Sequence[Sequence[object]],
    params: dict[str, object] | None = None,
) -> str:
    numeric = [_is_numeric_column(rows, i) for i in range(len(columns))]
    head = "".join(
        f'<th class="num">{html.escape(display_name(c))}</th>' if numeric[i] else f"<th>{html.escape(display_name(c))}</th>"
        for i, c in enumerate(columns)
    )
    body_rows = []
    for row in rows:
        cells = "".join(
            (f'<td class="num">{html.escape(format_value(c, v))}</td>' if numeric[i] else f"<td>{html.escape(format_value(c, v))}</td>")
            for i, (c, v) in enumerate(zip(columns, row))
        )
        body_rows.append(f"<tr>{cells}</tr>")
    shown_params = ", ".join(f"{html.escape(k)}={html.escape(str(v))}" for k, v in (params or {}).items())
    meta = f"{len(rows)} row{'s' if len(rows) != 1 else ''}" + (f" &middot; {shown_params}" if shown_params else "")
    empty = "" if rows else '<p class="empty">No rows matched these parameters.</p>'
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{html.escape(query.title)}</title>\n<style>{_STYLE}</style>\n</head>\n<body>\n"
        f"<h1>{html.escape(query.title)}</h1>\n"
        f'<p class="desc">{html.escape(query.description)}</p>\n'
        f'<p class="meta">{meta}</p>\n'
        f"{_svg_chart(query, columns, rows)}"
        f"<table>\n<thead><tr>{head}</tr></thead>\n<tbody>\n" + "\n".join(body_rows) + "\n</tbody>\n</table>\n"
        f"{empty}\n</body>\n</html>\n"
    )


def render(
    fmt: str,
    query: Query,
    columns: Sequence[str],
    rows: Sequence[Sequence[object]],
    params: dict[str, object] | None = None,
) -> str:
    if fmt == "csv":
        return to_csv(columns, rows)
    if fmt == "markdown":
        return to_markdown(columns, rows)
    if fmt == "html":
        return to_html(query, columns, rows, params)
    raise ValueError(f"unknown format {fmt!r}")
