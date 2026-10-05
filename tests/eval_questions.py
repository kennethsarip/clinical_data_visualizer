"""Typed loader for `eval/questions.json`: expected plans written before the planner (Phase 3.0).

The planner acceptance tests (stubbed and `-m live`) and the Phase 5 runner both read questions
through here, so the file has one schema.
"""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import FilterKey

QUESTIONS_PATH = Path(__file__).resolve().parent.parent / "eval" / "questions.json"

QuestionClass = Literal[
    "time_trend", "distribution", "comparison", "geographic", "network", "numeric", "edge_case"
]
Entity = Literal["drug_name", "condition", "sponsor"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExpectedCohort(_Strict):
    label: str
    entity: Entity
    value: str


class Expected(_Strict):
    """What a correct system returns. `http` 422 means the request is rejected before planning."""

    http: Literal[200, 422] = 200
    status: Literal["ok", "clarification_needed", "no_results", "degraded"] | None
    analysis: str | None  # "<intent>.<dimension>", a registered key
    viz_type: str | None
    # Stated values match case-insensitively. An inferred filter is ambiguous by definition, so it
    # lists every acceptable value.
    stated: dict[FilterKey, str | int] = Field(default_factory=dict)
    inferred: dict[FilterKey, list[str | int]] = Field(default_factory=dict)
    cohorts: list[ExpectedCohort] | None = None
    missing: list[Entity] = Field(default_factory=list)  # clarification_needed only
    not_found: list[str] = Field(default_factory=list)  # no_results only
    capped: bool | None = None  # None: not asserted
    field_override: bool = False  # a request field overrode the query (meta.notes says so)


class EvalQuestion(_Strict):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    question_class: QuestionClass
    source: Literal["appendix", "extension", "edge_case"]
    request: dict[str, Any]  # raw body: an invalid one is itself a test case (http 422)
    expected: Expected
    why: str  # the reasoning behind the expectation, written before any run


class QuestionSet(_Strict):
    written: str  # ISO date the expectations were fixed
    questions: list[EvalQuestion]


def load_questions(path: Path = QUESTIONS_PATH) -> list[EvalQuestion]:
    return QuestionSet.model_validate_json(path.read_text()).questions
