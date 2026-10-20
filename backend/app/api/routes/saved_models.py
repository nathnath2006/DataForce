"""Saved models: save a flow model block's fitted parameters, list them, score now (M4 phase 2)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response

from app.api.deps import AppSettings, CurrentViewer, CurrentWorkspace, Db
from app.api.routes.flows import LoaderSessions
from app.api.schemas_models import (
    ModelOut,
    ModelRename,
    ModelSave,
    ScoreRequest,
    ScoreResponse,
)
from app.db.models import SavedModel
from app.services import saved_models as svc

router = APIRouter(tags=["saved_models"])


def _out(row: SavedModel) -> ModelOut:
    return ModelOut.model_validate(row)


@router.get("/w/{ws}/models", response_model=list[ModelOut])
def list_models(db: Db, ws: CurrentWorkspace) -> list[ModelOut]:
    return [_out(r) for r in svc.list_models(db, ws.id)]


@router.post("/w/{ws}/models", response_model=ModelOut, status_code=201)
def save_model(
    body: ModelSave,
    db: Db,
    ws: CurrentWorkspace,
    settings: AppSettings,
    sessions: LoaderSessions,
    viewer: CurrentViewer,
) -> ModelOut:
    row = svc.save_model(
        db, ws.id, body.flow_id, body.node_id, body.name, settings, sessions, viewer
    )
    db.commit()
    return _out(row)


@router.get("/w/{ws}/models/{model_id}", response_model=ModelOut)
def get_model(model_id: uuid.UUID, db: Db, ws: CurrentWorkspace) -> ModelOut:
    return _out(svc.require_model(db, ws.id, model_id))


@router.patch("/w/{ws}/models/{model_id}", response_model=ModelOut)
def rename_model(model_id: uuid.UUID, body: ModelRename, db: Db, ws: CurrentWorkspace) -> ModelOut:
    row = svc.rename_model(db, ws.id, model_id, body.name)
    db.commit()
    return _out(row)


@router.delete("/w/{ws}/models/{model_id}", status_code=204)
def delete_model(
    model_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> Response:
    svc.delete_model(db, ws.id, model_id, viewer)
    db.commit()
    return Response(status_code=204)


@router.post("/w/{ws}/models/{model_id}/score", response_model=ScoreResponse)
def score(
    model_id: uuid.UUID,
    body: ScoreRequest,
    db: Db,
    ws: CurrentWorkspace,
    settings: AppSettings,
    sessions: LoaderSessions,
    viewer: CurrentViewer,
) -> ScoreResponse:
    return ScoreResponse(
        **svc.score_source(db, ws.id, model_id, body.source, settings, sessions, viewer)
    )
