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
