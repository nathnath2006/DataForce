"""`dataforce`: command line (entry point: `app.cli:app`).

Each sub-app lives in its own module (`app/cli/<name>.py`) and exposes a Typer called `app`.
M1 foundation ships `db upgrade`; the integration step fills `demo`, `stats` and `crm`."""

from __future__ import annotations

import typer

from app.cli import crm, db, demo, mcp, secrets, serve, stats, ui, users

app = typer.Typer(
    name="dataforce",
    help="DataForce: analysis workspace for sales teams (synthetic demo data, verified stats).",
    no_args_is_help=True,
    add_completion=False,
    # The pretty traceback prints local variables, which would include settings objects.
    pretty_exceptions_show_locals=False,
)

app.add_typer(db.app, name="db")
app.add_typer(demo.app, name="demo")
app.add_typer(stats.app, name="stats")
app.add_typer(crm.app, name="crm")
app.add_typer(secrets.app, name="secrets")
app.add_typer(mcp.app, name="mcp")
app.add_typer(users.app, name="users")
demo.app.command("backfill-logins")(users.backfill_logins_cmd)
app.command("ui")(ui.ui)
app.command("serve")(serve.serve)

__all__ = ["app"]
