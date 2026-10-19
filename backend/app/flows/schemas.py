"""Analysis flows: the graph format, every block's configuration, and run results.

Contract (owned by the tech lead): the engine (`app/flows/engine.py`), the API
(`app/api/routes/flows.py`) and the frontend editor all speak these types. See
docs/M2A-CONTRACT.md section 3 for the semantics of each block.

Rules that hold for every block:
* numbers are computed by code (pandas / numpy / scipy / scikit-learn), never by an LLM;
* a block that compares groups or evaluates a model reports confidence intervals and a
  `verified` / `not_verified` status with reasons, using the workspace's gates;
* configurations are structured data: there is no expression language and nothing is ever
  evaluated as code.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

NODE_ID = r"^[A-Za-z0-9_-]{1,64}$"
COLUMN = Annotated[str, Field(min_length=1, max_length=200)]
Scalar = str | int | float | bool | None

MAX_NODES = 100
MAX_EDGES = 200
PREVIEW_ROWS = 100


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- dataset sources ------------------------------------------------------------------------------
CrmTable = Literal[
    "deals",
    "accounts",
    "contacts",
    "companies",
    "meetings",
    "meeting_themes",
    "deal_theme_flags",
    "activities",
    "stage_events",
    "tasks",
]


class CrmSource(_Cfg):
    source: Literal["crm"] = "crm"
    table: CrmTable


class FileSource(_Cfg):
    source: Literal["file"] = "file"
    file_id: UUID


class PostgresSource(_Cfg):
    """Exactly one of `table` ("schema.table" or "table") and `query` (one SELECT statement)."""

    source: Literal["postgres"] = "postgres"
    connection_id: UUID
    table: str | None = Field(default=None, max_length=300)
    query: str | None = Field(default=None, max_length=20_000)

    @model_validator(mode="after")
    def _one_of(self) -> PostgresSource:
        if (self.table is None) == (self.query is None):
            raise ValueError("set exactly one of table and query")
        return self


DatasetSource = Annotated[CrmSource | FileSource | PostgresSource, Field(discriminator="source")]


# --- block configurations -------------------------------------------------------------------------
class DatasetConfig(_Cfg):
    type: Literal["dataset"] = "dataset"
    dataset: DatasetSource


FilterOp = Literal[
    "eq", "ne", "lt", "le", "gt", "ge", "contains", "not_contains", "is_null", "not_null", "in"
]


class Condition(_Cfg):
    column: COLUMN
    op: FilterOp
    value: Scalar | list[Scalar] = None  # a list only for "in"; ignored for is_null / not_null


class FilterConfig(_Cfg):
    type: Literal["filter"] = "filter"
    mode: Literal["all", "any"] = "all"
    conditions: list[Condition] = Field(default_factory=list, max_length=50)


class SortKey(_Cfg):
    column: COLUMN
    descending: bool = False


class SortConfig(_Cfg):
    type: Literal["sort"] = "sort"
    keys: list[SortKey] = Field(min_length=1, max_length=10)
    limit: int | None = Field(default=None, ge=1)


class Operand(_Cfg):
    """A column or a constant (exactly one)."""

    column: COLUMN | None = None
    value: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode="after")
    def _one_of(self) -> Operand:
        if (self.column is None) == (self.value is None):
            raise ValueError("an operand is either a column or a value")
        return self


class Computed(_Cfg):
    """A computed column. add/sub/mul/div: left op right (division by zero gives null).
    days_between: right - left in days (both date columns). bucket: cut `left` (a column) at
    `edges` (ascending) into `labels` (len(edges) + 1)."""

    name: COLUMN
    op: Literal["add", "sub", "mul", "div", "days_between", "bucket"]
    left: Operand
    right: Operand | None = None
    edges: list[float] | None = Field(default=None, max_length=50)
    labels: list[str] | None = Field(default=None, max_length=51)


class ColumnsConfig(_Cfg):
    type: Literal["columns"] = "columns"
    keep: list[COLUMN] | None = Field(default=None, max_length=500)  # None = all, in order
    rename: dict[str, str] = Field(default_factory=dict)
    computed: list[Computed] = Field(default_factory=list, max_length=20)


AggFn = Literal["count", "count_distinct", "sum", "mean", "median", "min", "max"]


class Aggregation(_Cfg):
    column: COLUMN | None = None  # None only with fn == "count" (count rows)
    fn: AggFn
    alias: COLUMN = Field(alias="as")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class GroupConfig(_Cfg):
    type: Literal["group"] = "group"
    by: list[COLUMN] = Field(min_length=1, max_length=10)
    aggregations: list[Aggregation] = Field(min_length=1, max_length=20)


class JoinKey(_Cfg):
    left: COLUMN
    right: COLUMN


class JoinConfig(_Cfg):
    type: Literal["join"] = "join"
    how: Literal["inner", "left"] = "left"
    on: list[JoinKey] = Field(min_length=1, max_length=5)
    suffix: str = Field(default="_right", min_length=1, max_length=20)


class PivotConfig(_Cfg):
    type: Literal["pivot"] = "pivot"
    rows: list[COLUMN] = Field(min_length=1, max_length=5)
    columns: COLUMN | None = None  # None: one value column per row group
    values: COLUMN | None = None  # None only with fn == "count"
    fn: AggFn = "count"
    totals: bool = True
    max_columns: int = Field(default=50, ge=1, le=200)  # distinct values of `columns` kept


class StatsConfig(_Cfg):
    """Compare each group of `group_by` with the rest of the rows on `outcome`.
    rate: share of rows where outcome == success_value (default True); median: numeric outcome.
    Uses the workspace's gates (Wilson / Newcombe / Fisher or bootstrap / Mann-Whitney, BH)."""

    type: Literal["stats"] = "stats"
    group_by: COLUMN
    outcome: COLUMN
    outcome_kind: Literal["rate", "median"]
    success_value: Scalar = True


class ChartConfig(_Cfg):
    """The backend aggregates the points (numbers come from code); the browser only draws."""

    type: Literal["chart"] = "chart"
    kind: Literal["bar", "line", "scatter"]
    x: COLUMN
    y: COLUMN | None = None  # None only with agg == "count"
    series: COLUMN | None = None
    agg: Literal["count", "sum", "mean", "median", "none"] = "count"  # "none": raw points
    max_points: int = Field(default=2000, ge=10, le=10_000)


class SplitConfig(_Cfg):
    type: Literal["split"] = "split"
    test_fraction: float = Field(default=0.25, ge=0.1, le=0.5, allow_inf_nan=False)
    seed: int = 42
    stratify: COLUMN | None = None
    mode: Literal["random", "chronological"] = "random"
    # chronological: the test set is the latest `test_fraction` of rows by this date column
    date_column: COLUMN | None = None

    @model_validator(mode="after")
    def _chrono(self) -> SplitConfig:
        if self.mode == "chronological":
            if self.date_column is None:
                raise ValueError("a chronological split needs a date column")
            if self.stratify is not None:
                raise ValueError("a chronological split cannot be stratified")
        return self


class ModelConfig(_Cfg):
    """Fit on `train`, evaluate on `test`. Features: numeric columns are standardised, other
    columns one-hot encoded (top 30 values, the rest grouped as "other")."""

    type: Literal["model"] = "model"
    kind: Literal["linear_regression", "logistic_regression", "svm", "svr"]
    target: COLUMN
    features: list[COLUMN] = Field(min_length=1, max_length=50)
    positive_value: Scalar = True  # logistic and svm: which target value is the positive class
    # svm / svr only
    kernel: Literal["rbf", "linear"] = "rbf"
    C: float = Field(default=1.0, gt=0, le=1000, allow_inf_nan=False)
    gamma: float | None = Field(default=None, gt=0, allow_inf_nan=False)  # None: "scale"


class ClusterConfig(_Cfg):
    type: Literal["cluster"] = "cluster"
    kind: Literal["kmeans"] = "kmeans"
    k: int = Field(default=3, ge=2, le=20)
    features: list[COLUMN] = Field(min_length=1, max_length=50)
    seed: int = 42


class DedupConfig(_Cfg):
    """Fuzzy deduplication on one text column. Adds `dedup_group` and `is_master`. Never merges
    CRM records."""

    type: Literal["dedup"] = "dedup"
    column: COLUMN
    method: Literal["jaro_winkler", "levenshtein"] = "jaro_winkler"
    threshold: float = Field(default=0.92, ge=0.5, le=1.0, allow_inf_nan=False)
    block_prefix: int = Field(default=1, ge=1, le=4)  # leading characters that must match


class AgingConfig(_Cfg):
    """days_since = run date - a date column; `stagnant` when days_since > N on matching rows."""

    type: Literal["aging"] = "aging"
    column: COLUMN
    alias: COLUMN = "days_since"
    stagnant_after_days: int = Field(default=30, ge=0, le=36_500)
    where: list[Condition] = Field(default_factory=list, max_length=20)
    where_mode: Literal["all", "any"] = "all"


DEFAULT_PROBABILITIES: dict[str, float] = {
    "prospecting": 10,
    "qualification": 20,
    "proposal": 40,
    "negotiation": 60,
    "closed_won": 100,
    "closed_lost": 0,
}


class ForecastConfig(_Cfg):
    """amount x stage probability (percent). The probabilities are the user's assumptions."""

    type: Literal["forecast"] = "forecast"
    amount: COLUMN
    stage: COLUMN
    probabilities: dict[str, float] = Field(
        default_factory=lambda: dict(DEFAULT_PROBABILITIES), max_length=50
    )
    group_by: COLUMN | None = None

    @model_validator(mode="after")
    def _range(self) -> ForecastConfig:
        for k, v in self.probabilities.items():
            if not (0 <= v <= 100) or v != v:
                raise ValueError(f"probability of {k!r} must be between 0 and 100")
        return self


WindowFn = Literal[
    "lag",
    "lead",
    "rolling_mean",
    "rolling_sum",
    "rolling_count",
    "rank",
    "row_number",
    "pct_change",
]


class WindowConfig(_Cfg):
    """A window function over partitions, ordered by one column. `period` first sums `column`
    per partition and period (month, quarter or year of the order column)."""

    type: Literal["window"] = "window"
    fn: WindowFn
    column: COLUMN | None = None  # not needed for row_number
    partition_by: list[COLUMN] = Field(default_factory=list, max_length=10)
    order_by: COLUMN
    descending: bool = False
    k: int = Field(default=1, ge=1, le=1000)  # lag / lead offset, or rolling window size
    alias: COLUMN = "window_value"
    period: Literal["month", "quarter", "year"] | None = None


class DomainConfig(_Cfg):
    """Extract the domain of an email or URL and flag free webmail. No DNS lookup."""

    type: Literal["domain"] = "domain"
    column: COLUMN
    alias: COLUMN = "domain"


class ScoreConfig(_Cfg):
    """Apply a saved model's parameters to the input rows. Adds `score` (and `score_class` for a
    classifier). The parameters are resolved from the workspace when the run starts."""

    type: Literal["score"] = "score"
    model_id: UUID


class VelocityConfig(_Cfg):
    """Deal velocity index on stage-change events (deal_id, from_stage, to_stage, changed_at).
    The benchmark of a stage is the median days spent in it over the input rows."""

    type: Literal["velocity"] = "velocity"
    deal_column: COLUMN = "deal_id"
    to_stage_column: COLUMN = "to_stage"
    date_column: COLUMN = "changed_at"
    fast_track_at: float = Field(default=1.25, gt=0, le=100, allow_inf_nan=False)
    stagnant_below: float = Field(default=0.75, gt=0, le=100, allow_inf_nan=False)
    terminal_stages: list[str] = Field(
        default_factory=lambda: ["closed_won", "closed_lost"], max_length=20
    )
    include_open_stage: bool = True  # the stage a deal is in now counts up to the run date

    @model_validator(mode="after")
    def _order(self) -> VelocityConfig:
        if self.stagnant_below >= self.fast_track_at:
            raise ValueError("stagnant_below must be lower than fast_track_at")
        return self


DEFAULT_ENGAGEMENT_WEIGHTS: dict[str, float] = {"meeting": 3, "call": 2, "email": 1, "other": 1}


class EngagementConfig(_Cfg):
    """Engagement per account: weighted activity counts in the last `window_days` days, times
    (1 - penalty) when the latest touchpoint is more than `quiet_days` days old."""

    type: Literal["engagement"] = "engagement"
    by: COLUMN = "account_id"
    kind_column: COLUMN = "kind"
    date_column: COLUMN = "occurred_at"
    window_days: int = Field(default=90, ge=1, le=3650)
    quiet_days: int = Field(default=30, ge=1, le=3650)
    penalty: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)
    weights: dict[str, float] = Field(
        default_factory=lambda: dict(DEFAULT_ENGAGEMENT_WEIGHTS), max_length=20
    )

    @model_validator(mode="after")
    def _w(self) -> EngagementConfig:
        for k, v in self.weights.items():
            if not (0 <= v <= 1000) or v != v:
                raise ValueError(f"weight of {k!r} must be between 0 and 1000")
        return self


class TouchpointConfig(_Cfg):
    """Rep touchpoint ratio = meetings x meeting_weight / outreach (outbound calls and emails)."""

    type: Literal["touchpoint"] = "touchpoint"
    by: COLUMN = "author"
    kind_column: COLUMN = "kind"
    direction_column: COLUMN = "direction"
    meeting_weight: float = Field(default=3, gt=0, le=1000, allow_inf_nan=False)


BlockConfig = Annotated[
    DatasetConfig
    | FilterConfig
    | SortConfig
    | ColumnsConfig
    | GroupConfig
    | JoinConfig
    | PivotConfig
    | StatsConfig
    | ChartConfig
    | SplitConfig
    | ModelConfig
    | ClusterConfig
    | DedupConfig
    | AgingConfig
    | ForecastConfig
    | WindowConfig
    | DomainConfig
    | ScoreConfig
    | VelocityConfig
    | EngagementConfig
    | TouchpointConfig,
    Field(discriminator="type"),
]
BlockType = Literal[
    "dataset",
    "filter",
    "sort",
    "columns",
    "group",
    "join",
    "pivot",
    "stats",
    "chart",
    "split",
    "model",
    "cluster",
    "dedup",
    "aging",
    "forecast",
    "window",
    "domain",
    "score",
    "velocity",
    "engagement",
    "touchpoint",
]

# Input and output ports of each block type (edges connect an output port to an input port;
# an input port takes exactly one edge).
PORTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "dataset": ((), ("out",)),
    "filter": (("in",), ("out",)),
    "sort": (("in",), ("out",)),
    "columns": (("in",), ("out",)),
    "group": (("in",), ("out",)),
    "join": (("left", "right"), ("out",)),
    "pivot": (("in",), ("out",)),
    "stats": (("in",), ("out",)),
    "chart": (("in",), ()),
    "split": (("in",), ("train", "test")),
    "model": (("train", "test"), ("out",)),
    "cluster": (("in",), ("out",)),
    "dedup": (("in",), ("out",)),
    "aging": (("in",), ("out",)),
    "forecast": (("in",), ("out",)),
    "window": (("in",), ("out",)),
    "domain": (("in",), ("out",)),
    "score": (("in",), ("out",)),
    "velocity": (("in",), ("out",)),
    "engagement": (("in",), ("out",)),
    "touchpoint": (("in",), ("out",)),
}


# --- graph ----------------------------------------------------------------------------------------
class Position(BaseModel):
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)


class Node(_Cfg):
    id: str = Field(pattern=NODE_ID)
    label: str | None = Field(default=None, max_length=100)
    position: Position
    config: BlockConfig


class Edge(_Cfg):
    id: str = Field(pattern=NODE_ID)
    source: str = Field(pattern=NODE_ID)
    source_port: str = Field(default="out", max_length=20)
    target: str = Field(pattern=NODE_ID)
    target_port: str = Field(default="in", max_length=20)


class FlowGraph(_Cfg):
    """Validated structurally here (ids unique, edges reference existing nodes and real ports,
    one edge per input port, no cycle) so a stored graph is always runnable or explainable."""

    version: Literal[1] = 1
    nodes: list[Node] = Field(default_factory=list, max_length=MAX_NODES)
    edges: list[Edge] = Field(default_factory=list, max_length=MAX_EDGES)

    @model_validator(mode="after")
    def _structure(self) -> FlowGraph:
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("node ids must be unique")
        types = {n.id: n.config.type for n in self.nodes}
        edge_ids: set[str] = set()
        taken: set[tuple[str, str]] = set()
        children: dict[str, list[str]] = {i: [] for i in ids}
        for e in self.edges:
            if e.id in edge_ids:
                raise ValueError("edge ids must be unique")
            edge_ids.add(e.id)
            if e.source not in types or e.target not in types:
                raise ValueError(f"edge {e.id} references a missing node")
            if e.source_port not in PORTS[types[e.source]][1]:
                raise ValueError(f"edge {e.id}: {types[e.source]} has no output {e.source_port!r}")
            if e.target_port not in PORTS[types[e.target]][0]:
                raise ValueError(f"edge {e.id}: {types[e.target]} has no input {e.target_port!r}")
            if (e.target, e.target_port) in taken:
                raise ValueError(f"input {e.target_port!r} of {e.target} has two edges")
            taken.add((e.target, e.target_port))
            children[e.source].append(e.target)
        state: dict[str, int] = {}

        def visit(node: str) -> None:  # iterative DFS would be overkill at 100 nodes
            state[node] = 1
            for child in children[node]:
                if state.get(child) == 1:
                    raise ValueError("the flow has a cycle")
                if child not in state:
                    visit(child)
            state[node] = 2

        for node_id in ids:
            if node_id not in state:
                visit(node_id)
        return self


# --- results --------------------------------------------------------------------------------------
class ColumnInfo(BaseModel):
    name: str
    dtype: Literal["number", "integer", "text", "boolean", "date", "datetime", "other"]


class Histogram(BaseModel):
    min: float
    max: float
    counts: list[int]  # 8 equal-width bins between min and max


class TopValue(BaseModel):
    value: str  # at most 60 characters
    count: int


class ColumnProfile(BaseModel):
    name: str
    dtype: Literal["number", "integer", "text", "boolean", "date", "datetime", "other"]
    n: int
    non_null: int
    n_unique: int  # capped at 10,000
    n_unique_capped: bool = False
    hist: Histogram | None = None  # numeric columns
    top: list[TopValue] | None = None  # text and boolean columns


class PivotView(BaseModel):
    kind: Literal["pivot"] = "pivot"
    row_headers: list[str]  # names of the row dimensions
    column_values: list[str]  # pivoted column labels (stringified), plus "Total" if totals
    rows: list[dict[str, Any]]  # {"keys": [row key values...], "cells": [values...]}
    truncated_columns: int = 0  # distinct values dropped by max_columns


class ChartSeries(BaseModel):
    name: str
    points: list[tuple[Any, float | None]]  # (x, y)


class ChartView(BaseModel):
    kind: Literal["chart"] = "chart"
    chart: Literal["bar", "line", "scatter"]
    x_label: str
    y_label: str
    series: list[ChartSeries]
    truncated: bool = False


class StatsRow(BaseModel):
    group: str
    n: int
    value: float | None
    ci_low: float | None
    ci_high: float | None
    rest_value: float | None
    diff: float | None
    diff_ci_low: float | None
    diff_ci_high: float | None
    p_value: float | None
    q_value: float | None
    status: Literal["verified", "not_verified"]
    reasons: list[str] = []


class StatsView(BaseModel):
    kind: Literal["stats"] = "stats"
    outcome: str
    outcome_kind: Literal["rate", "median"]
    method: str  # e.g. "wilson + newcombe + fisher, BH" / "bootstrap median + mann-whitney, BH"
    overall: StatsRow  # the whole input, as a group "(all)"
    rows: list[StatsRow]
    excluded_missing: int  # rows with a missing group or outcome
    gates: dict[str, Any]  # the GateConfig used


class Metric(BaseModel):
    name: str  # "r2", "mae", "rmse", "accuracy", "auc", "silhouette"
    value: float | None
    ci_low: float | None = None
    ci_high: float | None = None
    baseline: float | None = None  # what a model that learnt nothing scores


class ModelView(BaseModel):
    kind: Literal["model"] = "model"
    model: Literal["linear_regression", "logistic_regression", "svm", "svr"]
    n_train: int
    n_test: int
    dropped_missing: int
    metrics: list[Metric]
    coefficients: list[dict[str, Any]]  # {"feature", "coef"}: associations, not causes
    confusion: list[list[int]] | None = None  # logistic: [[tn, fp], [fn, tp]]
    status: Literal["verified", "not_verified"]
    reasons: list[str] = []  # e.g. "test set too small (n = 18 < 30)", "AUC CI includes 0.5"


class ClusterView(BaseModel):
    kind: Literal["cluster"] = "cluster"
    k: int
    sizes: list[int]
    centroids: list[dict[str, Any]]  # feature -> value, in original units
    metrics: list[Metric]  # silhouette
    dropped_missing: int
    status: Literal["exploratory"] = "exploratory"  # clusters describe, they do not prove


class ScoreView(BaseModel):
    kind: Literal["score"] = "score"
    model_name: str
    model_kind: str
    status: Literal["verified", "not_verified", "exploratory"]  # inherited from the saved model
    n_rows: int
    n_scored: int
    n_imputed: int = 0  # rows with a missing numeric feature, filled with the training mean
    notes: list[str] = []


class VelocityStage(BaseModel):
    stage: str
    median_days: float | None
    n: int


class VelocityView(BaseModel):
    kind: Literal["velocity"] = "velocity"
    benchmark_note: str  # states that the benchmark is a median over the input rows
    benchmarks: list[VelocityStage]
    fast_track_at: float
    stagnant_below: float
    counts: dict[str, int]  # flag -> deals


class EngagementView(BaseModel):
    kind: Literal["engagement"] = "engagement"
    today: str
    window_days: int
    quiet_days: int
    penalty: float
    weights: dict[str, float]
    n_accounts: int
    n_penalised: int
    formula: str


class TouchpointView(BaseModel):
    kind: Literal["touchpoint"] = "touchpoint"
    formula: str
    n_groups: int
    n_no_outreach: int


View = Annotated[
    PivotView
    | ChartView
    | StatsView
    | ModelView
    | ClusterView
    | ScoreView
    | VelocityView
    | EngagementView
    | TouchpointView,
    Field(discriminator="kind"),
]


class NodeResult(BaseModel):
    node_id: str
    status: Literal["ok", "error", "skipped"]  # skipped: an upstream block failed
    error: str | None = None  # human readable, never a stack trace or a password
    n_rows: int | None = None
    columns: list[ColumnInfo] = []
    profile: list[ColumnProfile] | None = None  # first 60 columns, exact; absent in older results
    preview: list[dict[str, Any]] = []  # first PREVIEW_ROWS rows, JSON-safe (dates ISO, NaN null)
    view: View | None = None
    model_params: dict[str, Any] | None = None  # JSON-safe fitted parameters (no pickle)
    warnings: list[str] = []  # e.g. "rows capped at 200000", "12 rows with a missing target"
    elapsed_ms: int = 0


class RunRequest(_Cfg):
    graph: FlowGraph
    target: str | None = Field(default=None, pattern=NODE_ID)  # None: run every sink


class RunResponse(BaseModel):
    run_id: UUID | None  # the `run` row recording this execution (summary only, no data)
    started_at: datetime
    results: dict[str, NodeResult]
