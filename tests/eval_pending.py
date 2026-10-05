"""Eval questions written ahead of the step that makes them pass (CLAUDE.md §14 Phase 6 step 0).

The live tests mark them strict-xfail with the step that fixes each one, so a run stays readable
and an early pass is noticed. A step removes its entries when it lands.
"""

import pytest
from _pytest.mark import ParameterSet

from eval.questions import EvalQuestion

PENDING = {
    "tt_condition_country_variant": "Phase 6 step 2: 'Korea' maps to the registry's 'South Korea'",
    "edge_two_values_one_filter": "Phase 6 step 3: two places for one filter ask which one",
    "edge_unexpressible_constraint": "Phase 6 step 3: an age group no filter expresses asks first",
}


def eval_params(questions: list[EvalQuestion]) -> list[ParameterSet]:
    return [
        pytest.param(
            q,
            id=q.id,
            marks=[pytest.mark.xfail(strict=True, reason=PENDING[q.id])] if q.id in PENDING else [],
        )
        for q in questions
    ]
