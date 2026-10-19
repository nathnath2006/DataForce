"""Request / response models of the viz and workbook routes (M4, agent D)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.flows.schemas import ColumnInfo, CrmTable

COL = Annotated[str, Field(min_length=1, max_length=200)]
Name = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=200, pattern=r"^[^\x00-\x1f\x7f]+$"
    ),
]
Scalar = str | int | float | bool | None
VIZ_ID = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")]

MAX_CANVASES = 12
MAX_VIZ = 30
MAX_QUERY_LIMIT = 5_000
MAX_FILTER_VALUES = 500
MAX_FILTER_TEXT = 1_000
MAX_SPEC_BYTES = 1_000_000


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CrmRef(_In):
    kind: Literal["crm"] = "crm"
    table: CrmTable


class FlowRef(_In):
    kind: Literal["flow"] = "flow"
    flow_id: uuid.UUID
    node_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")]


Source = Annotated[CrmRef | FlowRef, Field(discriminator="kind")]

Agg = Literal["count", "sum", "mean", "median", "min", "max", "count_distinct"]
FilterOp = Literal["eq", "ne", "lt", "le", "gt", "ge", "contains", "in", "is_null", "not_null"]


class Measure(_In):
    column: COL  # "*" only with count
    agg: Agg

    @model_validator(mode="after")
    def _star(self) -> Measure:
        if self.column == "*" and self.agg != "count":
            raise ValueError('"*" can only be counted')
        return self


class Filter(_In):
    column: COL
    op: FilterOp
    value: Scalar | list[Scalar] = None

    @model_validator(mode="after")
    def _bounded(self) -> Filter:
        items = self.value if isinstance(self.value, list) else [self.value]
        if len(items) > MAX_FILTER_VALUES:
            raise ValueError(f"a filter takes at most {MAX_FILTER_VALUES} values")
        if any(isinstance(v, str) and len(v) > MAX_FILTER_TEXT for v in items):
            raise ValueError(f"a filter value is longer than {MAX_FILTER_TEXT} characters")
        return self


class SortKey(_In):
    by: COL  # an output column name
    descending: bool = False


class QueryRequest(_In):
    source: Source
    dimensions: list[COL] = Field(default_factory=list, max_length=6)
    measures: list[Measure] = Field(default_factory=list, max_length=8)
    filters: list[Filter] = Field(default_factory=list, max_length=30)
    sort: list[SortKey] = Field(default_factory=list, max_length=4)
    limit: int = Field(default=1000, ge=1, le=MAX_QUERY_LIMIT)


class QueryResponse(BaseModel):
    columns: list[ColumnInfo]
    rows: list[list[Any]]
    n_source_rows: int  # rows loaded from the source (before the filters)
    n_filtered_rows: int
    n_groups: int
    truncated_source: bool
    notes: list[str]


class FieldsRequest(_In):
    source: Source


class FieldsResponse(BaseModel):
    columns: list[ColumnInfo]
    n_source_rows: int
    truncated_source: bool
    notes: list[str]


class ExplainMeasure(_In):
    """A numeric column compared by median, or the share of rows where `column` equals
    `success_value` (the win rate of a closed-deals outcome such as is_won)."""

    column: COL
    kind: Literal["rate", "median"]
    success_value: Scalar = True


class ExplainRequest(_In):
    source: Source
    measure: ExplainMeasure
    attributes: list[COL] = Field(min_length=1, max_length=5)
    filters: list[Filter] = Field(default_factory=list, max_length=30)


class ExplainFinding(BaseModel):
    attribute: str
    group: str
    n: int
    value: float | None
    rest_value: float | None
    diff: float | None
    diff_ci_low: float | None
    diff_ci_high: float | None
    p_value: float | None
    q_value: float | None
    direction: Literal["higher", "lower", "none"]
    status: Literal["verified", "not_verified"]
    reasons: list[str]


class ExplainResponse(BaseModel):
    measure: ExplainMeasure
    method: str
    n_rows: int
    truncated_source: bool
    verified: list[ExplainFinding]
    not_verified: list[ExplainFinding]
    notes: list[str]


# --- workbooks ------------------------------------------------------------------------------------
VizType = Literal[
    "bar", "line", "area", "scatter", "pie", "donut", "heatmap", "treemap", "funnel", "kpi",
    "table", "pivot",
]  # fmt: skip


class Slots(_In):
    category: COL | None = None
    values: list[Measure] = Field(default_factory=list, max_length=8)
    color: COL | None = None
    size: Measure | None = None
    rows: list[COL] = Field(default_factory=list, max_length=3)
    columns: list[COL] = Field(default_factory=list, max_length=3)


class VizOptions(_In):
    stacked: bool = False
    smooth: bool = False
    show_labels: bool = False
    horizontal: bool = False
    limit: int = Field(default=200, ge=1, le=MAX_QUERY_LIMIT)
    sort_by: COL | None = None
    descending: bool = True


class Visualization(_In):
    id: VIZ_ID
    type: VizType
    title: Annotated[str, Field(max_length=200)] = ""
    source: Source
    slots: Slots = Field(default_factory=Slots)
    options: VizOptions = Field(default_factory=VizOptions)


class LayoutItem(_In):
    viz_id: VIZ_ID
    x: int = Field(ge=0, le=11)
    y: int = Field(ge=0, le=1000)
    w: int = Field(ge=1, le=12)
    h: int = Field(ge=1, le=40)

    @model_validator(mode="after")
    def _fits(self) -> LayoutItem:
        if self.x + self.w > 12:
            raise ValueError("a tile must fit in the 12-column grid")
        return self


class Canvas(_In):
    name: Name
    filters: list[Filter] = Field(default_factory=list, max_length=20)
    layout: list[LayoutItem] = Field(default_factory=list, max_length=MAX_VIZ)
    visualizations: list[Visualization] = Field(default_factory=list, max_length=MAX_VIZ)

    @model_validator(mode="after")
    def _consistent(self) -> Canvas:
        ids = [v.id for v in self.visualizations]
        if len(ids) != len(set(ids)):
            raise ValueError("visualization ids must be unique within a canvas")
        placed = [i.viz_id for i in self.layout]
        if len(placed) != len(set(placed)) or not set(placed) <= set(ids):
            raise ValueError("the layout must place existing visualizations once each")
        return self


class WorkbookSpec(_In):
    version: Literal[1] = 1
    canvases: list[Canvas] = Field(default_factory=list, max_length=MAX_CANVASES)

    @model_validator(mode="after")
    def _small_enough(self) -> WorkbookSpec:
        if len(self.model_dump_json().encode()) > MAX_SPEC_BYTES:
            raise ValueError(f"the workbook is larger than {MAX_SPEC_BYTES // 1_000_000} MB")
        return self


class WorkbookCreate(_In):
    name: Name
    spec: WorkbookSpec = Field(default_factory=WorkbookSpec)


class WorkbookUpdate(_In):
    name: Name | None = None
    spec: WorkbookSpec | None = None


class WorkbookSummary(BaseModel):
    id: uuid.UUID
    name: str
    n_canvases: int
    updated_at: datetime


class WorkbookOut(BaseModel):
    id: uuid.UUID
    name: str
    spec: WorkbookSpec
    created_at: datetime
    updated_at: datetime
