"""`dataforce demo ...`: generate synthetic data, load it, check the scan against the truth."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from app.cli._common import cli_command, console, fail, print_json, session_factory
from app.demo.check import check_against_truth
from app.demo.generator import generate
from app.demo.loader import load_dataset
from app.domain.enums import RunKind, RunStatus
from app.services import analytics, runs, workspaces

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
    n_deals: NDealsOpt = 200,
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


@app.command("check")
@cli_command
def check_cmd(
    variant: VariantOpt = Variant.PLANTED,
    seed: SeedOpt = 42,
    n_deals: NDealsOpt = 200,
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
