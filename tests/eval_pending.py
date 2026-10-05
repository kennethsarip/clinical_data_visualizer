"""Eval questions written ahead of the step that makes them pass (CLAUDE.md §14 Phase 6 step 0).

The live tests mark them strict-xfail with the step that fixes each one, so a run stays readable
and an early pass is noticed. A step removes its entries when it lands.
"""

import pytest
from _pytest.mark import ParameterSet

from eval.questions import EvalQuestion

# question id -> the step that makes it pass. Empty: every Phase 6 step 0 question now passes.
PENDING: dict[str, str] = {}


def eval_params(questions: list[EvalQuestion]) -> list[ParameterSet]:
    return [
        pytest.param(
            q,
            id=q.id,
            marks=[pytest.mark.xfail(strict=True, reason=PENDING[q.id])] if q.id in PENDING else [],
        )
        for q in questions
    ]
