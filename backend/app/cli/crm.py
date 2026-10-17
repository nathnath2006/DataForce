"""`dataforce crm ...`: accounts, org charts and append-only notes."""

from __future__ import annotations

import uuid
from typing import Annotated

import typer
from rich.table import Table
from rich.tree import Tree

from app.cli._common import cli_command, console, fail, make_subapp, print_json, session_factory
from app.cli.stats import JsonOpt, WorkspaceOpt, require_ws
from app.services import accounts, contacts, notes

app = make_subapp("Minimal CRM: accounts, org charts, append-only notes.")
notes_app = make_subapp("Notes on contacts. Append-only: corrections and deletes keep history.")
app.add_typer(notes_app, name="notes")

AuthorOpt = Annotated[uuid.UUID | None, typer.Option("--author", help="Author user UUID.")]


@app.command("accounts")
@cli_command
def accounts_cmd(workspace: WorkspaceOpt, as_json: JsonOpt = False) -> None:
    """List the accounts of a workspace."""
    with session_factory()() as s:
        ws = require_ws(s, workspace)
        rows = [
            {
                "id": str(a.id),
                "name": a.name,
                "segment": a.segment,
                "industry": a.industry,
                "region": a.region,
            }
            for a in accounts.list_accounts(s, ws.id)
        ]
    if as_json:
        print_json(rows)
        return
    table = Table(title=f"Accounts of {workspace} ({len(rows)})")
    for col in ("id", "name", "segment", "industry", "region"):
        table.add_column(col)
    for r in rows:
        table.add_row(*(str(r[c] or "-") for c in ("id", "name", "segment", "industry", "region")))
    console.print(table)


@app.command("org-chart")
@cli_command
def org_chart_cmd(
    workspace: WorkspaceOpt,
    account: Annotated[str, typer.Option("--account", help="Account name (exact).")],
) -> None:
    """Show who reports to whom at an account."""
    with session_factory()() as s:
        ws = require_ws(s, workspace)
        matches = [a for a in accounts.list_accounts(s, ws.id) if a.name == account]
        if not matches:
            raise fail(f"account {account!r} not found in {workspace!r}")
        chart = contacts.org_chart(s, ws.id, matches[0].id)
    by_id = {c.id: c for c, _ in chart}
    children: dict[uuid.UUID | None, list] = {}
    for c, mgr in chart:
        children.setdefault(mgr if mgr in by_id else None, []).append(c)

    def label(c) -> str:
        return f"{c.full_name}" + (f" ({c.title})" if c.title else "")

    def grow(node: Tree, parent: uuid.UUID | None) -> None:
        for c in children.get(parent, []):
            grow(node.add(label(c)), c.id)

    tree = Tree(f"[bold]{account}[/bold]")
    grow(tree, None)
    console.print(tree)


@notes_app.command("add")
@cli_command
def notes_add(
    workspace: WorkspaceOpt,
    contact: Annotated[uuid.UUID, typer.Option("--contact", help="Contact UUID.")],
    body: Annotated[str, typer.Option("--body")],
    author: AuthorOpt = None,
) -> None:
    """Add a note to a contact."""
    with session_factory()() as s:
        ws = require_ws(s, workspace)
        n = notes.add_note(s, ws.id, contact, author, body)
        s.commit()
        console.print(f"Added note {n.id}")


@notes_app.command("correct")
@cli_command
def notes_correct(
    workspace: WorkspaceOpt,
    note: Annotated[uuid.UUID, typer.Option("--note", help="Note UUID to correct.")],
    body: Annotated[str, typer.Option("--body")],
    author: AuthorOpt = None,
) -> None:
    """Correct a note: a NEW row is written, the original stays in the history."""
    with session_factory()() as s:
        ws = require_ws(s, workspace)
        n = notes.correct_note(s, ws.id, note, author, body)
        s.commit()
        console.print(f"Wrote correction {n.id} (corrects {note})")


@notes_app.command("delete")
@cli_command
def notes_delete(
    workspace: WorkspaceOpt,
    note: Annotated[uuid.UUID, typer.Option("--note")],
    by: Annotated[uuid.UUID | None, typer.Option("--by", help="User UUID.")] = None,
) -> None:
    """Soft-delete a note (marked deleted, never removed)."""
    with session_factory()() as s:
        ws = require_ws(s, workspace)
        n = notes.delete_note(s, ws.id, note, by)
        s.commit()
        console.print(f"Marked note {n.id} deleted (row kept)")


@notes_app.command("history")
@cli_command
def notes_history(
    workspace: WorkspaceOpt,
    note: Annotated[uuid.UUID, typer.Option("--note")],
    as_json: JsonOpt = False,
) -> None:
    """Show every version of a note, oldest first."""
    with session_factory()() as s:
        ws = require_ws(s, workspace)
        rows = [
            {
                "id": str(n.id),
                "corrects_id": str(n.corrects_id) if n.corrects_id else None,
                "created_at": n.created_at.isoformat(),
                "deleted_at": n.deleted_at.isoformat() if n.deleted_at else None,
                "body": n.body,
            }
            for n in notes.note_history(s, ws.id, note)
        ]
    if as_json:
        print_json(rows)
        return
    table = Table(title="Note history")
    for col in ("id", "corrects", "created", "deleted", "body"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            r["id"], r["corrects_id"] or "-", r["created_at"], r["deleted_at"] or "-", r["body"]
        )
    console.print(table)
