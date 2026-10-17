"""Helpers shared by the CLI sub-apps."""

from __future__ import annotations

import functools
import json
from collections.abc import Callable
from typing import Any

import typer
from rich.console import Console
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.db import session as db_session
from app.services.errors import ServiceError

console = Console()
err_console = Console(stderr=True)


def fail(message: str, code: int = 1) -> typer.Exit:
    """Print a one-line error (no traceback) and return the Exit to `raise`."""
    err_console.print(f"[red]error:[/red] {message}")
    return typer.Exit(code)


def handle_db_errors[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Turn "database unreachable" into a hint instead of a stack trace. The exception text is
    not printed: SQLAlchemy can include the connection URL."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except OperationalError as exc:
            raise fail(
                "cannot connect to the database (not running, wrong credentials or TLS refused). "
                "Try `docker compose up -d db`, and check DATABASE_URL in backend/.env "
                f"({type(exc.orig).__name__ if exc.orig else 'OperationalError'})."
            ) from None
        except SQLAlchemyError as exc:
            # Statement and parameters can hold personal text: print the class name only.
            orig = getattr(exc, "orig", None)
            raise fail(
                f"database error ({type(orig or exc).__name__}); details are hidden because they "
                "can contain your data."
            ) from None

    return wrapper


def make_subapp(help_text: str) -> typer.Typer:
    """A sub-app that already shows `--help` before it has any command; the integration step
    adds commands with `@app.command()`."""
    sub = typer.Typer(help=help_text, no_args_is_help=True, add_completion=False)

    @sub.callback()
    def _group() -> None:
        """(group callback: gives Typer a group to render for sub-apps without commands)"""

    return sub


def handle_errors[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Errors the services raise on purpose (bad input, unknown record) become one `error:`
    line and exit code 1, never a traceback. Their messages are safe to print."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except ServiceError as exc:
            raise fail(str(exc)) from None

    return wrapper


def cli_command[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Decorator for every command: unreachable database and expected service errors both turn
    into a clean message."""
    return handle_db_errors(handle_errors(func))


def session_factory() -> sessionmaker[Session]:
    """The factory commands use. Looked up at call time (not imported) so tests can point the
    whole CLI at their own transaction."""
    return db_session.SessionLocal


def print_json(data: Any) -> None:
    """Machine output: plain stdout, no colors, no line wrapping."""
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))
