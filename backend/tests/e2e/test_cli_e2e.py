"""End to end: the `dataforce` CLI against the TEST database (rolled back after each test)."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from app.cli import app
from app.cli import demo as demo_cli
from app.config import get_settings
from app.db import session as db_session_module
from app.db.models import Contact, Workspace
from app.demo.generator import generate
from app.demo.inmemory import deal_rows
from app.domain.enums import StatStatus
from app.domain.schemas import ScanReport
from app.stats.engine import gate_config_from_settings, scan

runner = CliRunner()


@pytest.fixture
def cli_env(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    tmp_path,
):
    """Point the whole CLI at the test transaction and the truth files at a temp dir."""
    monkeypatch.setattr(db_session_module, "SessionLocal", session_factory)
    monkeypatch.setattr(demo_cli, "DEMO_DIR", tmp_path)
    return tmp_path


def _run(*args: str):
    return runner.invoke(app, list(args))


@pytest.mark.integration
# Noise seed 42 is one of the ~4% of noise datasets (at 350 deals) where one chance finding
# survives the gates (docs/DECISIONS.md section E); it is pinned as a failing check below.
@pytest.mark.parametrize(("variant", "seed"), [("planted", 42), ("noise", 1)])
def test_generate_then_check(cli_env, variant: str, seed: int) -> None:
    res = _run("demo", "generate", "--variant", variant, "--seed", str(seed), "--replace")
    assert res.exit_code == 0, res.output
    assert (cli_env / f"ground_truth_{variant}_{seed}.json").exists()
    res = _run("demo", "check", "--variant", variant, "--seed", str(seed))
    assert res.exit_code == 0, res.output
    assert "passed=True" in res.output


@pytest.mark.integration
def test_check_reports_the_known_noise_false_alarm(cli_env) -> None:
    assert _run("demo", "generate", "--variant", "noise", "--seed", "42").exit_code == 0
    res = _run("demo", "check", "--variant", "noise", "--seed", "42")
    assert res.exit_code == 1  # the check fails loudly instead of hiding it
    assert "false positive" in res.output


@pytest.mark.integration
def test_noise_has_no_verified_findings_and_scan_json_parses(cli_env) -> None:
    assert _run("demo", "generate", "--variant", "noise", "--seed", "1").exit_code == 0
    res = _run("stats", "scan", "--workspace", "demo-noise-1", "--json")
    assert res.exit_code == 0, res.output
    report = ScanReport.model_validate(json.loads(res.stdout))
    assert report.findings
    assert not [f for f in report.findings if f.status == StatStatus.VERIFIED]


@pytest.mark.integration
def test_planted_scan_json_and_pipeline(cli_env) -> None:
    assert _run("demo", "generate", "--variant", "planted", "--seed", "42").exit_code == 0
    res = _run("stats", "scan", "--workspace", "demo-planted-42", "--json")
    report = ScanReport.model_validate(json.loads(res.stdout))
    assert any(f.status == StatStatus.VERIFIED for f in report.findings)
    res = _run("stats", "pipeline", "--workspace", "demo-planted-42", "--json")
    assert json.loads(res.stdout)["n_deals"] == 350
    res = _run("crm", "accounts", "--workspace", "demo-planted-42", "--json")
    accounts = json.loads(res.stdout)
    assert accounts
    res = _run(
        "crm", "org-chart", "--workspace", "demo-planted-42", "--account", accounts[0]["name"]
    )
    assert res.exit_code == 0, res.output


@pytest.mark.integration
def test_generate_twice_needs_replace(cli_env) -> None:
    assert _run("demo", "generate", "--variant", "noise", "--seed", "7").exit_code == 0
    res = _run("demo", "generate", "--variant", "noise", "--seed", "7")
    assert res.exit_code == 1
    assert "Traceback" not in res.output


@pytest.mark.integration
def test_unknown_workspace_is_one_line_error(cli_env) -> None:
    res = _run("stats", "scan", "--workspace", "does-not-exist")
    assert res.exit_code == 1
    assert "not found" in res.output


@pytest.mark.integration
def test_notes_round_trip(cli_env, db_session: Session) -> None:
    assert _run("demo", "generate", "--variant", "noise", "--seed", "42").exit_code == 0
    contact_id = db_session.scalars(
        select(Contact.id)
        .join(Workspace, Workspace.id == Contact.workspace_id)
        .where(Workspace.slug == "demo-noise-42")
        .limit(1)
    ).one()
    ws = ("--workspace", "demo-noise-42")

    res = _run("crm", "notes", "add", *ws, "--contact", str(contact_id), "--body", "first")
    assert res.exit_code == 0, res.output
    first = res.output.split("Added note ")[1].split()[0]

    res = _run("crm", "notes", "correct", *ws, "--note", first, "--body", "second")
    assert res.exit_code == 0, res.output

    res = _run("crm", "notes", "history", *ws, "--note", first, "--json")
    rows = json.loads(res.stdout)
    assert [r["body"] for r in rows] == ["first", "second"]  # original kept

    res = _run("crm", "notes", "delete", *ws, "--note", first)
    assert res.exit_code == 0, res.output
    rows = json.loads(_run("crm", "notes", "history", *ws, "--note", first, "--json").stdout)
    assert len(rows) == 2 and any(r["deleted_at"] for r in rows)  # soft delete, rows kept


def test_bad_variant_is_rejected() -> None:
    res = _run("demo", "generate", "--variant", "../etc/passwd")
    assert res.exit_code != 0
    res = _run("demo", "check", "--variant", "bogus")
    assert res.exit_code != 0


def test_noise_false_positives_over_10_seeds() -> None:
    """In memory (no DB): at most one of 10 noise seeds may show any verified finding."""
    cfg = gate_config_from_settings(get_settings())
    bad = 0
    for seed in range(10):
        ds = generate("noise", seed)
        report = scan(deal_rows(ds), cfg)
        bad += any(f.status == StatStatus.VERIFIED for f in report.findings)
    assert bad <= 1


def test_unexpected_db_error_prints_no_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy.exc import DataError

    from app.cli._common import cli_command

    @cli_command
    def boom() -> None:
        raise DataError("INSERT ...", {"body": "SECRET-NOTE-BODY"}, ValueError("bad"))

    import typer

    cli = typer.Typer()
    cli.command()(boom)
    res = runner.invoke(cli, [])
    assert res.exit_code == 1
    assert "SECRET-NOTE-BODY" not in res.output and "INSERT" not in res.output
    assert "database error" in res.output and "ValueError" in res.output
