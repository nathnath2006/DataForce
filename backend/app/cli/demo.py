"""`dataforce demo ...`: generate synthetic data, load it, check the scan against the truth."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from app.cli._common import cli_command, console, fail, print_json, session_factory
from app.demo.activities import backfill_workspace
from app.demo.check import check_against_truth
from app.demo.generator import generate
from app.demo.loader import load_dataset
from app.domain.enums import RunKind, RunStatus
from app.services import analytics, runs, workspaces
from app.services.errors import InvalidInputError

app = typer.Typer(
    help="Synthetic demo data (generate, load, check).",
    no_args_is_help=True,
    add_completion=False,
)

# Repo root = backend/app/cli/demo.py -> parents[3]. data/demo/*.json is gitignored.
DEMO_DIR = Path(__file__).resolve().parents[3] / "data" / "demo"


class Variant(StrEnum):
    PLANTED = "planted"
    NOISE = "noise"


def slug_for(variant: Variant, seed: int) -> str:
    return f"demo-{variant.value}-{seed}"


def truth_path(variant: Variant, seed: int) -> Path:
    """Built only from the validated enum and an int: no user-controlled path pieces."""
    return DEMO_DIR / f"ground_truth_{variant.value}_{int(seed)}.json"


VariantOpt = Annotated[Variant, typer.Option("--variant", help="planted (real effects) or noise.")]
SeedOpt = Annotated[int, typer.Option("--seed", min=0, help="Random seed.")]
NDealsOpt = Annotated[int, typer.Option("--n-deals", min=20, max=20000, help="Number of deals.")]


@app.command("generate")
@cli_command
def generate_cmd(
    variant: VariantOpt = Variant.PLANTED,
    seed: SeedOpt = 42,
    n_deals: NDealsOpt = 350,
    replace: Annotated[
        bool, typer.Option("--replace", help="Replace an existing workspace.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Machine output.")] = False,
) -> None:
    """Generate a SYNTHETIC dataset, load it as workspace demo-<variant>-<seed>, save its truth."""
    ds = generate(variant.value, seed, n_deals)
    slug = slug_for(variant, seed)
    factory = session_factory()
    with factory() as s:
        counts = load_dataset(s, ds, workspace_slug=slug, replace=replace)
        run = runs.start_run(
            s,
            kind=RunKind.DEMO_GENERATE,
            workspace_id=counts["workspace_id"],
            params={"variant": variant.value, "seed": seed, "n_deals": n_deals},
        )
        runs.finish_run(
            s,
            run,
            RunStatus.SUCCEEDED,
            result={k: v for k, v in counts.items() if k != "workspace_id"},
        )
        s.commit()
    path = truth_path(variant, seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ds.ground_truth.model_dump_json(indent=2), encoding="utf-8")
    out = {k: (str(v) if k == "workspace_id" else v) for k, v in counts.items()}
    out["ground_truth_file"] = str(path)
    if as_json:
        print_json(out)
        return
    console.print(f"Loaded synthetic workspace [bold]{slug}[/bold] (data is SYNTHETIC).")
    for k, v in out.items():
        if k not in ("workspace_id", "workspace_slug"):
            console.print(f"  {k}: {v}")


# The one synthetic workspace people use in the app ("Test data"). It is the planted dataset of
# the automated checks (seed 42), shown without any seed or variant wording.
TEST_SLUG = "test-data"
TEST_NAME = "Test data (synthetic)"
TEST_SEED = 42


@app.command("testdata")
@cli_command
def testdata_cmd(
    replace: Annotated[
        bool, typer.Option("--replace", help="Replace the existing test workspace.")
    ] = False,
    drop_seed_workspaces: Annotated[
        bool,
        typer.Option(
            "--drop-seed-workspaces",
            help="Also delete the old demo-<variant>-<seed> workspaces (synthetic only).",
        ),
    ] = False,
) -> None:
    """Load the SYNTHETIC "Test data" workspace (companies, contacts, deals, notes, meetings)."""
    ds = generate("planted", TEST_SEED)
    factory = session_factory()
    with factory() as s:
        if drop_seed_workspaces:
            old = [w.slug for w in workspaces.list_workspaces(s) if w.is_demo]
            for slug in (x for x in old if x.startswith("demo-")):
                workspaces.delete_workspace(s, slug)  # expires the session: use the saved slugs
                console.print(f"Deleted synthetic workspace {slug}.")
        counts = load_dataset(
            s, ds, workspace_slug=TEST_SLUG, workspace_name=TEST_NAME, replace=replace
        )
        s.commit()
    path = DEMO_DIR / "ground_truth_test_data.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ds.ground_truth.model_dump_json(indent=2), encoding="utf-8")
    console.print(f"Loaded [bold]{TEST_NAME}[/bold] as workspace {TEST_SLUG}.")
    for k, v in counts.items():
        if k not in ("workspace_id", "workspace_slug"):
            console.print(f"  {k}: {v}")


@app.command("reset")
@cli_command
def reset_cmd(
    workspace: Annotated[
        str, typer.Option("--workspace", help="Slug of the public demo workspace.")
    ] = "",
) -> None:
    """Rebuild the public demo workspace from the planted seed-42 data (run it nightly).

    Safe while the app is serving: the new copy is built aside, then swapped in one short step.
    Every demo session, and the AI keys on them, ends. Refuses a workspace that is not a test
    workspace."""
    from app.config import get_settings
    from app.demo.reset import reset_demo

    slug = workspace or get_settings().demo_workspace
    try:
        done = reset_demo(session_factory(), slug, lambda m: console.print(f"  {m}", markup=False))
    except InvalidInputError as exc:
        raise fail(str(exc)) from exc
    if not done:
        console.print("Another demo reset is already running: nothing to do.", markup=False)
        return
    console.print(f"Demo workspace {slug} rebuilt (data is SYNTHETIC).", markup=False)


@app.command("check")
@cli_command
def check_cmd(
    variant: VariantOpt = Variant.PLANTED,
    seed: SeedOpt = 42,
    n_deals: NDealsOpt = 350,
    as_json: Annotated[bool, typer.Option("--json", help="Machine output.")] = False,
) -> None:
    """Scan the demo workspace and compare the findings with the planted ground truth."""
    slug = slug_for(variant, seed)
    truth = generate(variant.value, seed, n_deals).ground_truth
    with session_factory()() as s:
        ws = workspaces.get_workspace_by_slug(s, slug)
        if ws is None:
            raise fail(
                f"workspace {slug!r} not found. Run `dataforce demo generate --variant "
                f"{variant.value} --seed {seed}` first."
            )
        report = analytics.run_scan(s, ws.id)
        s.commit()
    result = check_against_truth(report, truth)
    if as_json:
        print_json(result.model_dump(mode="json"))
    else:
        n_ver = sum(1 for f in report.findings if f.status.value == "verified")
        console.print(f"[bold]{slug}[/bold]: {n_ver} verified findings of {len(report.findings)}")
        console.print(result.summary())
        for e in result.missed:
            console.print(f"  [red]missed[/red] {e.dimension}={e.group} {e.metric} {e.direction}")
        for f in result.false_positives:
            console.print(f"  [red]false positive[/red] {f.dimension}={f.group} {f.metric}")
    if not result.passed:
        raise typer.Exit(1)


@app.command("backfill-activities")
@cli_command
def backfill_activities_cmd(
    workspace: Annotated[
        str, typer.Option("--workspace", help="Slug of an existing demo workspace.")
    ],
) -> None:
    """Add SYNTHETIC stage histories, activities and tasks to an existing demo workspace.

    Idempotent: deals that already have stage events are skipped. Nothing else is touched."""
    with session_factory()() as s:
        try:
            counts = backfill_workspace(s, workspace)
        except ValueError as exc:
            raise fail(str(exc)) from exc
        s.commit()
    console.print(f"Backfilled [bold]{workspace}[/bold] (data is SYNTHETIC).")
    for k, v in counts.items():
        console.print(f"  {k}: {v}")
