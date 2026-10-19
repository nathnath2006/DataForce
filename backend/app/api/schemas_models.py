"""Request / response models of the saved-model routes (M4 phase 2)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.api.schemas_viz import FlowRef, Name, Source, _In
from app.flows.schemas import Metric

Status = Literal["verified", "not_verified", "exploratory"]


class ModelSave(_In):
    flow_id: uuid.UUID
    node_id: str
    name: Name


class ModelRename(_In):
    name: Name


class ModelMetrics(BaseModel):
    """What the block reported on held-out data (server-computed, never sent by the client)."""

    metrics: list[Metric]
    n_train: int | None = None
    n_test: int | None = None
    reasons: list[str] = []
    confusion: list[list[int]] | None = None


class ModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    kind: Literal["linear", "logistic", "svm", "svr", "kmeans"]
    features: list[str]
    metrics: ModelMetrics
    status: Status
    flow_id: uuid.UUID | None
    node_id: str | None
    created_at: datetime


class ScoreRequest(_In):
    source: Source


class ScoreSummary(BaseModel):
    count: int
    mean: float | None = None
    min: float | None = None
    max: float | None = None
    class_counts: dict[str, int] | None = None  # classifiers and k-means


class ScoreResponse(BaseModel):
    model_id: uuid.UUID
    model_kind: str
    status: Status
    status_note: str | None  # set when the scores are not verified
    n_rows: int
    n_scored: int
    summary: ScoreSummary
    columns: list[str]
    rows: list[dict[str, Any]]  # the first 200 rows, input columns then score columns
    truncated_source: bool
    notes: list[str]


__all__ = ["FlowRef", "ModelOut", "ModelRename", "ModelSave", "ScoreRequest", "ScoreResponse"]
