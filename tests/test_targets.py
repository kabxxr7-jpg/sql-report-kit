"""--db values: SQLite paths and postgresql:// / mariadb:// URLs. No server needed."""

import builtins
import sys

import pytest

from sql_report_kit.backends import connect, parse_target
from sql_report_kit.cli import main
from sql_report_kit.errors import DatabaseError, TargetError


def test_a_plain_path_is_sqlite():
    t = parse_target("sample.db")
    assert (t.engine, t.path) == ("sqlite", "sample.db")
    assert parse_target("/tmp/some dir/x.db").engine == "sqlite"
    assert parse_target(r"C:\data\x.db").engine == "sqlite"


def test_postgres_url_parts():
    t = parse_target("postgresql://app:p%40ss@db.example.com:6543/shop")
    assert (t.engine, t.user, t.password, t.host, t.port, t.database) == ("postgres", "app", "p@ss", "db.example.com", 6543, "shop")
    assert parse_target("postgres://u@h/d").engine == "postgres"


def test_postgres_unix_socket_form():
    t = parse_target("postgresql://app@/shop?host=/var/run/postgresql")
    assert (t.host, t.database, t.option("host")) == ("", "shop", "/var/run/postgresql")


def test_mariadb_and_mysql_schemes_are_the_same_backend():
    for scheme in ("mariadb", "mysql"):
        t = parse_target(f"{scheme}://app:pw@127.0.0.1:3308/shop")
        assert (t.engine, t.host, t.port, t.database) == ("mariadb", "127.0.0.1", 3308, "shop")
    assert parse_target("mariadb://app@/shop?unix_socket=/tmp/m.sock").option("unix_socket") == "/tmp/m.sock"


def test_password_falls_back_to_the_environment(monkeypatch):
    monkeypatch.setenv("SQLREPORT_DB_PASSWORD", "from-env")
    assert parse_target("postgresql://app@h/d").password == "from-env"
    assert parse_target("postgresql://app:in-url@h/d").password == "in-url"


@pytest.mark.parametrize("url, message", [
    ("oracle://u@h/d", "unsupported database URL scheme"),
    ("http://example.com/x", "unsupported database URL scheme"),
    ("postgresql://u@h:notaport/d", "port"),
    ("postgresql://u@h/d?unix_socket=/x", "unsupported option"),
    ("mariadb://u@h/d?host=/x", "unsupported option"),
])
def test_bad_urls_are_refused(url, message):
    with pytest.raises(TargetError, match=message):
        parse_target(url)


def test_describe_never_contains_the_password():
    t = parse_target("postgresql://app:hunter2@db.example.com/shop")
    assert "hunter2" not in t.describe() and "hunter2" not in repr(t)
    assert "app" in t.describe() and "shop" in t.describe()


def test_bad_scheme_on_the_command_line_is_a_usage_error(capsys):
    assert main(["run", "monthly_revenue", "--db", "oracle://u:secret@h/d"]) == 2
    err = capsys.readouterr().err
    assert "unsupported database URL scheme" in err and "secret" not in err


@pytest.mark.parametrize("url", ["postgresql://nobody:secret-pw@127.0.0.1:1/nodb", "mariadb://nobody:secret-pw@127.0.0.1:1/nodb"])
def test_an_unreachable_server_is_a_clean_runtime_error_without_the_password(capsys, url):
    pytest.importorskip("psycopg" if url.startswith("postgres") else "pymysql")
    assert main(["run", "monthly_revenue", "--db", url]) == 1
    err = capsys.readouterr().err
    assert "could not connect" in err and "secret-pw" not in err


@pytest.mark.parametrize("url, module, package", [
    ("postgresql://u@h/d", "psycopg", "psycopg"),
    ("mariadb://u@h/d", "pymysql", "PyMySQL"),
])
def test_a_missing_driver_says_what_to_install(monkeypatch, url, module, package):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == module:
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, module, raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(DatabaseError, match="requirements-backends.txt"):
        connect(url)
