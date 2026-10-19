"""score: apply a saved model to the input rows. The parameters were resolved from the workspace
when the run started (Ctx.models), so the block never touches the database."""

from __future__ import annotations

import pandas as pd

from app.flows.blocks._common import BlockError, BlockOutput, Ctx
from app.flows.schemas import ScoreConfig, ScoreView
from app.flows.scoring import ModelSnapshot, ScoringError, score_frame

NOT_VERIFIED = (
    "scores from a model that did not beat its baseline on held-out data are not verified"
)


def run(cfg: ScoreConfig, inputs: dict[str, pd.DataFrame], ctx: Ctx) -> BlockOutput:
    df = inputs["in"]
    model = ctx.models.get(str(cfg.model_id))
    if not isinstance(model, ModelSnapshot):
        raise BlockError("the saved model does not exist in this workspace (deleted?)")
    try:
        res = score_frame(model, df)
    except ScoringError as e:
        raise BlockError(str(e)) from e
    clash = [c for c in res.columns.columns if c in df.columns]
    if clash:
        raise BlockError(f"the input already has a column named '{clash[0]}'")
    out = pd.concat([df, res.columns], axis=1)
    notes = list(res.notes)
    if model.status == "not_verified":
        notes.append(NOT_VERIFIED)
    elif model.status == "exploratory":
        notes.append("exploratory model: clusters describe the data, they do not prove anything")
    view = ScoreView(
        model_name=model.name,
        model_kind=model.kind,
        status=model.status,  # type: ignore[arg-type]
        n_rows=len(df),
        n_scored=len(df) - res.n_unscored,
        n_imputed=res.n_imputed,
        notes=notes,
    )
    return BlockOutput(frames={"out": out}, view=view, warnings=notes)
