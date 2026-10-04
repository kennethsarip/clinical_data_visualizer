"""Single source of request, plan, LLM-output and response models (CLAUDE.md §8)."""

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from app.vocab import Phase, Status

# Blank strings are rejected rather than read as "no filter": a client omits a field it doesn't use.
FilterText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class RetrievalFilters(BaseModel):
    """The filter subset of the plan: everything `ctgov.py` turns into API params.

    Field names match the request fields in SCHEMAS.md §1, so a stated filter appears under the
    same key in `meta.filters`. `overall_status` has no request field; only the planner sets it.
    Phase 3 wraps this model with the LLM-facing plan fields.
    """

    # A misspelled field must fail loudly: ignoring it would silently widen the search (§7.8).
    model_config = ConfigDict(extra="forbid", frozen=True)

    drug_name: FilterText | None = None
    condition: FilterText | None = None
    sponsor: FilterText | None = None
    country: FilterText | None = None
    trial_phase: Phase | None = None
    overall_status: Status | None = None
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
