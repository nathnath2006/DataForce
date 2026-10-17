"""`dataforce stats ...`: pipeline facts and the verified / not-verified scan."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table
from sqlalchemy.orm import Session

from app.cli._common import cli_command, console, fail, make_subapp, print_json, session_factory
from app.domain.enums import StatStatus
from app.services import analytics, workspaces

app = make_subapp("Statistics: pipeline summary and the effect scan.")

WorkspaceOpt = Annotated[str, typer.Option("--workspace", "-w", help="Workspace slug.")]
JsonOpt = Annotated[bool, typer.Option("--json", help="Machine output.")]


def require_ws(s: Session, slug: str):
    ws = workspaces.get_workspace_by_slug(s, slug)
    if ws is None:
        raise fail(f"workspace {slug!r} not found")
    return ws


def _pts(x: float | None) -> str:
    return "-" if x is None else f"{x * 100:.1f}%"


def _fmt(metric: str, x: float | None) -> str:
    if x is None:
        return "-"
    return _pts(x) if metric == "win_rate" else f"{x:,.0f}"


def _diff(metric: str, f) -> str:
    if f.diff is None:
        return "-"
    if metric == "win_rate":
        lo, hi = (f.diff_ci_low or 0) * 100, (f.diff_ci_high or 0) * 100
        return f"{f.diff * 100:+.1f} pts [{lo:+.1f}, {hi:+.1f}]"
    unit = "d" if metric == "cycle_days" else "EUR"
    return f"{f.diff:+,.0f} {unit} [{f.diff_ci_low or 0:+,.0f}, {f.diff_ci_high or 0:+,.0f}]"


@app.command("scan")
@cli_command
def scan_cmd(workspace: WorkspaceOpt, as_json: JsonOpt = False) -> None:
    """Scan every dimension x group x metric. Only verified findings are facts."""
    with session_factory()() as s:
        ws = require_ws(s, workspace)
        report = analytics.run_scan(s, ws.id)
        s.commit()
    if as_json:
        print_json(report.model_dump(mode="json"))
        return
    findings = sorted(
        report.findings,
        key=lambda f: (f.status != StatStatus.VERIFIED, f.q_value if f.q_value is not None else 2),
    )
    table = Table(title=f"Scan of {workspace}: {report.n_deals} deals ({report.n_closed} closed)")
    for col in (
        "dimension",
        "group",
        "metric",
        "group vs rest",
        "diff [CI]",
        "q",
        "status",
        "reasons",
    ):
        table.add_column(col)
    for f in findings:
        m = f.metric.value
        ok = f.status == StatStatus.VERIFIED
        table.add_row(
            f.dimension.value,
            f.group,
            m,
            f"{_fmt(m, f.group_value)} vs {_fmt(m, f.rest_value)}",
            _diff(m, f),
            "-" if f.q_value is None else f"{f.q_value:.3f}",
            "[green]verified[/green]" if ok else "[yellow]not verified[/yellow]",
            "; ".join(f.reasons),
        )
    console.print(table)
    n_ver = sum(1 for f in findings if f.status == StatStatus.VERIFIED)
    console.print(
        f"{n_ver} verified of {len(findings)} comparisons. Synthetic demo data stays synthetic."
    )


@app.command("pipeline")
@cli_command
def pipeline_cmd(workspace: WorkspaceOpt, as_json: JsonOpt = False) -> None:
    """Exact pipeline totals by stage (SQL aggregates, no estimation)."""
    with session_factory()() as s:
        ws = require_ws(s, workspace)
        summary = analytics.pipeline_summary(s, ws.id)
    if as_json:
        print_json(summary)
        return
    table = Table(title=f"Pipeline of {workspace}: {summary['n_deals']} deals")
    table.add_column("stage")
    table.add_column("deals", justify="right")
    table.add_column("amount EUR", justify="right")
    for stage, v in summary["by_stage"].items():
        table.add_row(stage, str(v["count"]), f"{v['amount_eur']:,.0f}")
    console.print(table)
    console.print(
        f"open {summary['n_open']}, won {summary['n_won']}, lost {summary['n_lost']}, "
        f"total {summary['total_amount_eur']:,.0f} EUR"
    )
