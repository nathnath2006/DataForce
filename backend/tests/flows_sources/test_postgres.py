from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.flows.ports import SourceError
from app.flows.sources import postgres as pg

pytestmark = pytest.mark.integration

TABLE = "df_f_throwaway"


def _target(**kw) -> pg.PgTarget:
    url = make_url(get_settings().test_database_url.get_secret_value())
    assert url.host in ("localhost", "127.0.0.1")
    base = dict(
        host="127.0.0.1",
        port=url.port,
        database=url.database,
        username=url.username,
        password=url.password,
        sslmode="disable",
        timeout_s=2.0,
    )
    return pg.PgTarget(**{**base, **kw})


@pytest.fixture(scope="module")
def table():
    import psycopg

    t = _target()
    with psycopg.connect(
        host=t.host,
        port=t.port,
        dbname=t.database,
        user=t.username,
        password=t.password,
        autocommit=True,
    ) as c:
        c.execute(f"DROP TABLE IF EXISTS {TABLE}")
        c.execute(f"CREATE TABLE {TABLE} (id int, v numeric, d date)")
        c.execute(
            f"INSERT INTO {TABLE} SELECT g, g * 1.5, date '2025-01-01' + g "
            "FROM generate_series(1, 5) g"
        )
        yield
        c.execute(f"DROP TABLE IF EXISTS {TABLE}")


def test_table_and_query(table):
    df = pg.load_table(_target(), TABLE, 100)
    assert len(df) == 5 and df["v"].dtype.kind == "f" and df["d"].dtype.kind == "M"
    df = pg.load_query(_target(), f"SELECT id FROM {TABLE} ORDER BY id; ", 3)
    assert len(df) == 3 and df.attrs["capped"] is True
    assert len(pg.load_query(_target(), f"select ';' as s from {TABLE} -- c", 100)) == 5
    assert {"schema": "public", "name": TABLE} in pg.list_tables(_target())


@pytest.mark.parametrize(
    "q",
    [
        f"DELETE FROM {TABLE}",
        f"INSERT INTO {TABLE} VALUES (9, 9, now())",
        f"WITH x AS (DELETE FROM {TABLE} RETURNING id) SELECT * FROM x",
        f"SELECT 1; DROP TABLE {TABLE}",
        f"SELECT 1;DROP TABLE {TABLE};",
        f"SELECT 1) AS q; DROP TABLE {TABLE}; --",
    ],
)
def test_writes_and_multi_statements_refused(table, q):
    with pytest.raises(SourceError):
        pg.load_query(_target(), q, 10)
    assert len(pg.load_table(_target(), TABLE, 10)) == 5  # still there, untouched


def test_timeout(table):
    with pytest.raises(SourceError, match="longer than"):
        pg.load_query(_target(timeout_s=0.3), "SELECT pg_sleep(5)", 10)


def test_bad_password_never_echoed():
    secret = "S3cr3t-pw-XYZ"
    with pytest.raises(SourceError) as e:
        pg.check_connection(_target(password=secret))
    assert secret not in str(e.value)


def test_tls_policy_and_identifier():
    with pytest.raises(SourceError):
        pg.check_tls_policy("db.example.com", "prefer")
    pg.check_tls_policy("db.example.com", "verify-full")
    pg.check_tls_policy("::1", "disable")
    with pytest.raises(SourceError):
        pg.table_query("a.b.c", 1)
    assert 'x"; DROP' not in pg.table_query('x"; DROP', 1).as_string()


def test_sanitize():
    m = pg.sanitize_message("fail postgresql://u:pw@h/db password=abc", "pw")
    assert "pw" not in m and "abc" not in m


ESCAPE = ") AS q; COMMIT; BEGIN READ WRITE; DELETE FROM {t}; COMMIT; SELECT * FROM (SELECT "
QUOTINGS = ["$$'$$", "$x$'$x$", "1 /* ' */", "E'\\''", "1"]


@pytest.mark.parametrize("lit", QUOTINGS)
def test_protocol_level_single_statement(table, lit):
    """The scanner is bypassed on purpose: the server itself must refuse a second command."""
    q = f"SELECT {lit} AS a" + ESCAPE + f"{lit} AS a"
    stmt = pg.sql.SQL("SELECT * FROM ({}\n) AS q LIMIT 11").format(pg.sql.SQL(q.format(t=TABLE)))
    with pytest.raises(SourceError, match="only one statement"):
        pg.fetch_frame(_target(), stmt, 10)
    assert len(pg.load_table(_target(), TABLE, 10)) == 5


def test_error_messages_are_generic():
    with pytest.raises(SourceError) as e:
        pg.load_query(_target(), "SELECT 'topsecretrow'::int", 10)
    assert "topsecretrow" not in str(e.value)
    with pytest.raises(SourceError) as e:
        pg.check_connection(_target(port=1))
    assert str(e.value) == "could not connect to 127.0.0.1:1"
    with pytest.raises(SourceError) as e:
        pg.check_connection(_target(password="wrong"))
    assert str(e.value) == f"could not connect to 127.0.0.1:{_target().port}"


def test_watchdog_cancels_when_statement_timeout_reset(table, monkeypatch):
    import time

    monkeypatch.setattr(pg, "WATCHDOG_GRACE_S", 0.3)
    t0 = time.perf_counter()
    with pytest.raises(SourceError, match="cancelled"):
        pg.load_query(
            _target(timeout_s=1),
            "SELECT set_config('statement_timeout','0',false), pg_sleep(20)",
            10,
        )
    assert time.perf_counter() - t0 < 6


def test_byte_cap(table, monkeypatch):
    monkeypatch.setattr(pg, "MAX_RESULT_BYTES", 5_000)
    df = pg.load_query(
        _target(), "SELECT repeat('x', 1000) AS v FROM generate_series(1, 1000)", 1000
    )
    assert df.attrs.get("capped") is True and len(df) < 1000
