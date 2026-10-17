"""`tt db ...`: database lifecycle."""

from __future__ import annotations

from typing import Annotated

import typer

from app.cli._common import console, fail, handle_db_errors, make_subapp
from app.services import schema

app = make_subapp("Database schema (Alembic migrations).")


@app.command("upgrade")
@handle_db_errors
def upgrade(
    revision: Annotated[str, typer.Argument(help="Target revision.")] = "head",
) -> None:
    """Apply migrations to DATABASE_URL (from backend/.env or the environment)."""
    before = schema.current_revision()
    try:
        schema.upgrade(revision=revision)
    except Exception as exc:
        # Alembic raises CommandError for a bad revision; anything else is a real failure.
        if type(exc).__name__ == "CommandError":
            raise fail(str(exc)) from None
        raise
    after = schema.current_revision()
    if before == after:
        console.print(f"Database already at revision [bold]{after}[/bold].")
    else:
        console.print(f"Upgraded [bold]{before or 'empty'}[/bold] -> [bold]{after}[/bold].")
