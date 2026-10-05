"""Single source of request, plan, LLM-output and response models (CLAUDE.md §8)."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, model_validator

from app.vocab import Phase, Status

# Blank strings are rejected rather than read as "no filter": a client omits a field it doesn't use.
# The cap keeps an arbitrary string out of the API URL; real drug, condition, sponsor and country
# names are far shorter.
FILTER_TEXT_MAX_LENGTH = 200
QUERY_MAX_LENGTH = 1000
FilterText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=FILTER_TEXT_MAX_LENGTH)
]


class _FilterFields(BaseModel):
    """The filters a request may state (SCHEMAS.md §1), shared by the request and the plan."""

    # A misspelled field must fail loudly: ignoring it would silently widen the search (§7.8).
    model_config = ConfigDict(extra="forbid", frozen=True)

    drug_name: FilterText | None = None
    condition: FilterText | None = None
    sponsor: FilterText | None = None
    country: FilterText | None = None
    trial_phase: Phase | None = None
    start_year: int | None = None
    end_year: int | None = None

    @model_validator(mode="after")
    def _year_range_is_ordered(self) -> Self:
        if (
            self.start_year is not None
            and self.end_year is not None
            and self.start_year > self.end_year
        ):
            raise ValueError(f"start_year ({self.start_year}) is after end_year ({self.end_year})")
        return self


class RetrievalFilters(_FilterFields):
    """The filter subset of the plan: everything `ctgov.py` turns into API params.

    Field names match the request fields in SCHEMAS.md §1, so a stated filter appears under the
    same key in `meta.filters`. `overall_status` has no request field; only the planner sets it.
    Phase 3 wraps this model with the LLM-facing plan fields.
    """

    overall_status: Status | None = None


class VisualizeRequest(_FilterFields):
    """The `POST /api/visualize` body (SCHEMAS.md §1). Only `query` is required."""

    # The cap bounds prompt size and cost; a real question is far shorter.
    query: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=QUERY_MAX_LENGTH)
    ]


# --- LLM output (CLAUDE.md §7.2): parsed and validated before any code uses it ---

PlanEntity = Literal["drug_name", "condition", "sponsor"]


class LLMCohort(BaseModel):
    """One side of a comparison: the shared filters with one entity overridden."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: FilterText
    entity: PlanEntity
    value: FilterText


class LLMPlan(BaseModel):
    """The planner call's answer (CLAUDE.md §7.2 plan shape).

    `analysis` is a registered "<intent>.<dimension>" key: `planner.plan_schema` narrows it to an
    enum at runtime and `planner` re-checks it. `filters` holds only values written in the query;
    request fields are merged in by Python. The LLM never labels a filter stated or inferred.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    analysis: str
    filters: RetrievalFilters
    cohorts: list[LLMCohort] | None
    unsupported_reason: str | None  # set when no analysis fits the question


# --- response (SCHEMAS.md §2-§5) ---
# Models check structure only. Rules that compare values (encoding fields exist in rows,
# trial_count == len(nct_ids), excerpts match records, ...) are the §7.6 checks in `checks.py`,
# so each rule has exactly one home.

NctId = Annotated[str, Field(pattern=r"^NCT\d{8}$")]
Count = Annotated[int, Field(ge=0)]

# Every key a filter can appear under in `meta.filters`; a test keeps it equal to the
# RetrievalFilters fields.
FilterKey = Literal[
    "drug_name",
    "condition",
    "sponsor",
    "country",
    "trial_phase",
    "overall_status",
    "start_year",
    "end_year",
]
FilterValues = dict[FilterKey, str | int]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Citation(_Contract):
    nct_id: NctId
    excerpt: str | None  # None: the field is absent, which is why the trial is in this row
    field: str  # record path under protocolSection


class Provenance(_Contract):
    trial_count: Count
    nct_ids: list[NctId]
    citations: list[Citation]


class Row(Provenance):
    """One chart row. Its dimension fields vary by aggregator, so extra fields are allowed."""

    model_config = ConfigDict(extra="allow", frozen=True)


class Node(Provenance):
    id: str
    label: str
    entity_type: Literal["drug", "sponsor", "condition"]
    is_anchor: bool


class Edge(Provenance):
    source: str
    target: str


class NetworkData(_Contract):
    nodes: list[Node]
    edges: list[Edge]


class Channel(_Contract):
    field: str
    type: Literal["quantitative", "nominal", "ordinal", "temporal"]
    scale: Literal["linear", "log"] = "linear"


class NetworkEncoding(_Contract):
    nodes: dict[str, Channel]
    edges: dict[str, Channel]


ChartType = Literal["bar_chart", "grouped_bar_chart", "time_series", "scatter_plot", "histogram"]


class ChartVisualization(_Contract):
    type: ChartType
    title: str
    encoding: dict[str, Channel]
    data: list[Row]


class NetworkVisualization(_Contract):
    type: Literal["network_graph"]
    title: str
    encoding: NetworkEncoding
    data: NetworkData


VisualizationSpec = Annotated[
    ChartVisualization | NetworkVisualization, Field(discriminator="type")
]


class TrialSummary(_Contract):
    brief_title: str
    overall_status: str  # display label
    phase: str  # display label, e.g. "Phase 1/Phase 2"
    start_date: str | None  # as registered


class Filters(_Contract):
    stated: FilterValues
    inferred: FilterValues


class Cohort(_Contract):
    label: str
    filters: FilterValues


class Interpretation(_Contract):
    intent: str
    dimension: str
    cohorts: list[Cohort] | None


class Sort(_Contract):
    field: str
    order: Literal["asc", "desc", "canonical"]


class Grouping(_Contract):
    dimension: str
    series: str | None


class SampleEntry(_Contract):
    cohort: str | None
    fetched: Count
    total: Count
    capped: bool


class Exclusion(_Contract):
    rule: str
    count: Count


class TopN(_Contract):
    limit: Count
    categories_total: Count


class Pruning(_Contract):
    min_edge_weight: Count
    top_n_nodes: Count
    fallback_used: bool
    nodes_removed: Count
    edges_removed: Count


class CheckError(_Contract):
    check: str
    message: str


class _MetaBase(_Contract):
    source: Literal["clinicaltrials.gov"]
    filters: Filters
    assumptions: list[str]
    notes: list[str]


class OkMeta(_MetaBase):
    # Nullable keys are still required, so a renderer can tell "none" from "forgotten".
    interpretation: Interpretation
    units: dict[str, str]
    sort: Sort
    time_granularity: Literal["year"] | None
    grouping: Grouping
    sample: list[SampleEntry]
    citation_cap: Count
    excluded: list[Exclusion]
    top_n: TopN | None
    pruning: Pruning | None


class ClarificationMeta(_MetaBase):
    missing: list[Literal["drug_name", "condition", "sponsor"]]


class NoResultsMeta(_MetaBase):
    not_found: list[str]


class DegradedMeta(_MetaBase):
    errors: list[CheckError]


NoTrials = Annotated[dict[NctId, TrialSummary], Field(max_length=0)]


class OkResponse(_Contract):
    status: Literal["ok"]
    visualization: VisualizationSpec
    trials: dict[NctId, TrialSummary]
    meta: OkMeta


class ClarificationResponse(_Contract):
    status: Literal["clarification_needed"]
    visualization: None
    trials: NoTrials
    meta: ClarificationMeta


class NoResultsResponse(_Contract):
    status: Literal["no_results"]
    visualization: None
    trials: NoTrials
    meta: NoResultsMeta


class DegradedResponse(_Contract):
    status: Literal["degraded"]
    visualization: None
    trials: NoTrials
    meta: DegradedMeta


AnyResponse = OkResponse | ClarificationResponse | NoResultsResponse | DegradedResponse
VisualizeResponse = Annotated[AnyResponse, Field(discriminator="status")]
RESPONSE_ADAPTER: TypeAdapter[AnyResponse] = TypeAdapter(VisualizeResponse)
VISUALIZATION_ADAPTER: TypeAdapter[ChartVisualization | NetworkVisualization] = TypeAdapter(
    VisualizationSpec
)
