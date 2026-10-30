import sqlite3

import pytest

from sql_report_kit.generate import build_sample_db, content_digest


def digest_of(path):
    conn = sqlite3.connect(path)
    try:
        return content_digest(conn)
    finally:
        conn.close()


def test_same_seed_gives_identical_data_and_another_seed_does_not(tmp_path):
    a, b, c = tmp_path / "a.db", tmp_path / "b.db", tmp_path / "c.db"
    build_sample_db(a, seed=7)
    build_sample_db(b, seed=7)
    build_sample_db(c, seed=8)
    assert digest_of(a) == digest_of(b)
    assert digest_of(a) != digest_of(c)


def test_sizes_are_a_few_thousand_rows(tmp_path):
    counts = build_sample_db(tmp_path / "s.db", seed=42)
    assert counts["customers"] == 512 and counts["products"] == 30
    assert 800 <= counts["orders"] <= 1500
    assert counts["order_items"] > counts["orders"]
    assert 20 <= counts["refunds"] <= 150
    assert sum(counts.values()) >= 2500


def test_database_is_consistent(sample_db):
    conn = sqlite3.connect(sample_db)
    conn.execute("PRAGMA foreign_keys = ON")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    # an order never predates its customer's signup, and a refund never predates its sale
    assert conn.execute(
        "SELECT COUNT(*) FROM orders o JOIN customers c ON c.id = o.customer_id WHERE date(o.created_at) < c.created_at"
    ).fetchone() == (0,)
    assert conn.execute(
        "SELECT COUNT(*) FROM refunds r JOIN order_items oi ON oi.id = r.order_item_id "
        "JOIN orders o ON o.id = oi.order_id WHERE r.refunded_at < o.created_at"
    ).fetchone() == (0,)
    # a refund is never larger than what was paid for that line
    assert conn.execute(
        "SELECT COUNT(*) FROM refunds r JOIN order_items oi ON oi.id = r.order_item_id "
        "WHERE r.amount_cents > oi.quantity * oi.unit_price_cents"
    ).fetchone() == (0,)
    conn.close()


def test_the_data_contains_what_the_reports_are_meant_to_find(run, sample_db):
    assert len(run(sample_db, "products_never_sold")[1]) == 4
    dups = run(sample_db, "duplicate_customers")[1]
    assert any(r[0] == "email" for r in dups) and any(r[0] == "name_city" for r in dups)
    statuses = {r[0] for r in sqlite3.connect(sample_db).execute("SELECT DISTINCT status FROM orders")}
    assert statuses == {"completed", "cancelled", "pending"}


def test_nothing_in_the_sample_data_uses_a_real_looking_domain(sample_db):
    conn = sqlite3.connect(sample_db)
    rows = conn.execute("SELECT email FROM customers").fetchall()
    assert all(e.strip().lower().endswith("example.com") or e.strip().lower().endswith(".alt@example.com") for (e,) in rows)


def test_refuses_to_overwrite_without_force(tmp_path):
    path = tmp_path / "x.db"
    build_sample_db(path, seed=1)
    with pytest.raises(FileExistsError):
        build_sample_db(path, seed=2)
    before = digest_of(path)
    build_sample_db(path, seed=2, force=True)
    assert digest_of(path) != before
