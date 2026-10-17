"""Read-only access to an external PostgreSQL database (psycopg 3).

Guards: connect timeout 10 s; `default_transaction_read_only=on` and `statement_timeout` sent as
connection options; every query in a READ ONLY transaction; one statement only; the user query
is wrapped as a subquery with a LIMIT; table names go through `sql.Identifier`; server messages
are stripped of the password and of any connection string before they are shown.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import pandas as pd
import psycopg
from psycopg import sql

from app.config import is_loopback_host
from app.flows.ports import SourceError
from app.flows.sources.frame import frame_from_rows

CONNECT_TIMEOUT_S = 10
SSLMODES = ("disable", "allow", "prefer", "require", "verify-ca", "verify-full")
TLS_MODES = frozenset({"require", "verify-ca", "verify-full"})


@dataclass(frozen=True)
class PgTarget:
    host: str
    port: int
    database: str
    username: str
    password: str | None = field(default=None, repr=False)
    sslmode: str = "require"
    timeout_s: float = 30.0


def check_tls_policy(host: str, sslmode: str) -> None:
    """Same policy as `check_database_tls`: a non-loopback host must demand TLS."""
    if sslmode not in SSLMODES:
        raise SourceError("unknown sslmode")
    if not is_loopback_host(host) and sslmode not in TLS_MODES:
        raise SourceError(
            "this host is not local: sslmode must be require, verify-ca or verify-full"
        )


def sanitize_message(text: str, password: str | None = None) -> str:
    """No password, no connection string, one line, bounded."""
    if password:
        text = text.replace(password, "***")
    text = re.sub(r"\b[a-z][a-z0-9+.-]*://\S+", "<url>", text, flags=re.I)
    text = re.sub(r"(?i)\b(password|passfile|sslkey|sslpassword)\s*=\s*\S+", r"\1=***", text)
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return line[:300] or "database error"


def explain(exc: BaseException, target: PgTarget | None) -> str:
    password = target.password if target else None
    if isinstance(exc, psycopg.errors.QueryCanceled):
        seconds = f"{target.timeout_s:g} s" if target else "the limit"
        return f"the query was cancelled: it ran longer than {seconds}"
    if isinstance(exc, psycopg.errors.ReadOnlySqlTransaction):
        return "this connection is read-only: the statement tried to write"
    if isinstance(exc, psycopg.OperationalError):
        diag = getattr(exc, "diag", None)
        detail = getattr(diag, "message_primary", None) or str(exc)
        return "connection failed: " + sanitize_message(detail, password)
    if isinstance(exc, psycopg.Error):
        diag = getattr(exc, "diag", None)
        detail = getattr(diag, "message_primary", None) or str(exc)
        return sanitize_message(detail, password)
    return "database error"


@contextmanager
def connect(target: PgTarget) -> Iterator[psycopg.Connection]:
    check_tls_policy(target.host, target.sslmode)
    timeout_ms = max(1, int(target.timeout_s * 1000))
    try:
        conn = psycopg.connect(
            host=target.host,
            port=target.port,
            dbname=target.database,
            user=target.username,
            password=target.password or None,
            sslmode=target.sslmode,
            connect_timeout=CONNECT_TIMEOUT_S,
            options=f"-c default_transaction_read_only=on -c statement_timeout={timeout_ms}",
            application_name="dataforce",
        )
    except psycopg.Error as exc:
        raise SourceError(explain(exc, target)) from None
    try:
        conn.read_only = True
        yield conn
    except SourceError:
        raise
    except psycopg.Error as exc:
        raise SourceError(explain(exc, target)) from None
    finally:
        try:
            conn.rollback()
        except psycopg.Error:
            pass
        conn.close()


def single_statement(query: str) -> str:
    """The query without its trailing `;`. A `;` anywhere else (outside quotes and comments) is
    refused: one statement only."""
    text = query.strip()
    if not text:
        raise SourceError("the query is empty")
    i, n, semicolons = 0, len(text), []
    while i < n:
        c = text[i]
        if c in "'\"":
            end = text.find(c, i + 1)
            while end != -1 and text[end + 1 : end + 2] == c:  # doubled quote = escaped
                end = text.find(c, end + 2)
            i = n if end == -1 else end + 1
        elif text.startswith("--", i):
            end = text.find("\n", i)
            i = n if end == -1 else end + 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
        else:
            if c == ";":
                semicolons.append(i)
            i += 1
    if semicolons and not (len(semicolons) == 1 and text[semicolons[0] + 1 :].strip() == ""):
        raise SourceError("only one statement is allowed")
    return text[: semicolons[0]].rstrip() if semicolons else text


def wrap_query(query: str, max_rows: int) -> sql.Composed:
    body = single_statement(query)
    # newline before ")" so a trailing `-- comment` cannot swallow the parenthesis
    return sql.SQL("SELECT * FROM ({}\n) AS q LIMIT {}").format(
        sql.SQL(body), sql.Literal(max_rows + 1)
    )


def table_query(table: str, max_rows: int) -> sql.Composed:
    parts = [p for p in table.strip().split(".")]
    if not 1 <= len(parts) <= 2 or any(not p.strip() for p in parts):
        raise SourceError("the table must be 'table' or 'schema.table'")
    return sql.SQL("SELECT * FROM {} LIMIT {}").format(
        sql.Identifier(*[p.strip() for p in parts]), sql.Literal(max_rows + 1)
    )


def fetch_frame(target: PgTarget, statement: sql.Composed, max_rows: int) -> pd.DataFrame:
    with connect(target) as conn, conn.cursor() as cur:
        cur.execute(statement)
        names = [d.name for d in cur.description or []]
        rows = cur.fetchmany(max_rows + 1)
    capped = len(rows) > max_rows
    df = frame_from_rows(rows[:max_rows], names)
    if capped:
        df.attrs["capped"] = True
    return df


def load_query(target: PgTarget, query: str, max_rows: int) -> pd.DataFrame:
    return fetch_frame(target, wrap_query(query, max_rows), max_rows)


def load_table(target: PgTarget, table: str, max_rows: int) -> pd.DataFrame:
    return fetch_frame(target, table_query(table, max_rows), max_rows)


def check_connection(target: PgTarget) -> None:
    with connect(target) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1", ())
        cur.fetchone()


def list_tables(target: PgTarget, limit: int = 2000) -> list[dict[str, str]]:
    with connect(target) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
            "AND table_schema NOT LIKE 'pg\\_%%' "
            "ORDER BY table_schema, table_name LIMIT %s",
            (limit,),
        )
        return [{"schema": s, "name": n} for s, n in cur.fetchall()]
