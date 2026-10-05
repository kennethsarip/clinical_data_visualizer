"""The planner: one LLM call for interpretation, then deterministic rules (CLAUDE.md §7.2-§7.8).

Expected behavior comes from the decisions recorded in CLAUDE.md (plan shape and retry in §7.2,
stated vs inferred and field-vs-query in §7.3, the anchor rule in §7.8, 2-4 cohorts) and from the
expectations in `eval/questions.json`, written before this code.
"""

from datetime import date
from typing import Any

import httpx2
import pytest
from pydantic import ValidationError

import app.aggregators  # noqa: F401  (registers every aggregator)
from app.aggregators.registry import REGISTRY, Dimension, Intent
from app.llm import LLMOutputError, LLMUpstreamError
from app.planner import (
    Clarification,
    PlanError,
    QueryPlan,
    build_plan,
    instructions,
    plan_request,
    plan_schema,
    unaccounted_names,
)
from app.schemas import LLMPlan, RetrievalFilters, VisualizeRequest
from app.vocab import COUNTRIES, Phase, Status
from eval.questions import EvalQuestion, load_questions
from tests.llm_fakes import fake_llm, json_reply, replies, text_reply

TODAY = date(2026, 10, 4)
ANCHORS = ("drug_name", "condition", "sponsor")


def reply(
    analysis: str = "distribution.phase",
    cohorts: list[dict[str, str]] | None = None,
    unsupported: str | None = None,
    constraints: list[dict[str, Any]] | None = None,
    suggested: str | None = None,
    **filters: Any,
) -> dict[str, Any]:
    """An LLM plan as JSON: every filter key present, null unless given."""
    return {
        "analysis": analysis,
        "filters": {key: filters.get(key) for key in RetrievalFilters.model_fields},
        "cohorts": cohorts,
        "unsupported_reason": unsupported,
        "constraints": constraints or [],
        "suggested_query": suggested,
    }


def constraint(quote: str, applied_as: str | None, reason: str | None = None) -> dict[str, Any]:
    return {"quote": quote, "applied_as": applied_as, "reason": reason}


def build(query: str, llm: dict[str, Any], **fields: Any) -> QueryPlan | Clarification:
    request = VisualizeRequest.model_validate({"query": query, **fields})
    return build_plan(request, LLMPlan.model_validate(llm))


def ok(result: QueryPlan | Clarification) -> QueryPlan:
    assert isinstance(result, QueryPlan), result
    return result


def clarify(result: QueryPlan | Clarification) -> Clarification:
    assert isinstance(result, Clarification), result
    return result


def cohort(label: str, entity: str = "drug_name") -> dict[str, str]:
    return {"label": label, "entity": entity, "value": label}


# --- the schema and prompt come from the registry ---


def test_plan_schema_offers_exactly_the_registered_keys() -> None:
    keys = plan_schema()["properties"]["analysis"]["enum"]
    assert keys == [f"{i}.{d}" for i, d in REGISTRY.registered()]
    assert len(keys) == 22


def test_plan_schema_is_strict() -> None:
    schema = plan_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "analysis",
        "filters",
        "cohorts",
        "unsupported_reason",
        "constraints",  # Phase 6 step 3
        "suggested_query",
    }


def test_plan_schema_offers_only_registry_country_names() -> None:
    country = plan_schema()["$defs"]["RetrievalFilters"]["properties"]["country"]
    assert {"type": "string", "enum": list(COUNTRIES)} in country["anyOf"]


def test_prompt_describes_every_registered_key_and_gives_today() -> None:
    text = instructions(TODAY)
    for intent, dimension in REGISTRY.registered():
        assert f"{intent}.{dimension}" in text
    assert "2026-10-04" in text


# --- analysis key ---


def test_unregistered_analysis_is_an_output_error() -> None:
    with pytest.raises(LLMOutputError, match="analysis"):
        build("melanoma trials by phase", reply("distribution.investigator", condition="melanoma"))


def test_analysis_key_becomes_intent_and_dimension() -> None:
    plan = ok(build("Phases of melanoma trials", reply(condition="melanoma")))
    assert (plan.intent, plan.dimension) == (Intent.DISTRIBUTION, Dimension.PHASE)
    assert plan.analysis == "distribution.phase"


# --- request fields and the query (§7.3) ---


def test_field_supplies_a_filter_the_query_omits() -> None:
    plan = ok(build("How has this drug changed over time?", reply(), drug_name="Pembrolizumab"))
    assert plan.filters.drug_name == "Pembrolizumab"
    assert plan.stated == {"drug_name": "Pembrolizumab"} and plan.notes == ()


def test_field_overrides_a_conflicting_query_value_with_a_note() -> None:
    plan = ok(
        build(
            "Phase breakdown for pembrolizumab trials",
            reply(drug_name="pembrolizumab"),
            drug_name="nivolumab",
        )
    )
    assert plan.filters.drug_name == "nivolumab"
    assert plan.stated == {"drug_name": "nivolumab"}
    assert len(plan.notes) == 1
    assert "nivolumab" in plan.notes[0] and "pembrolizumab" in plan.notes[0]


def test_field_agreeing_with_the_query_adds_no_note() -> None:
    plan = ok(
        build("pembrolizumab phases", reply(drug_name="pembrolizumab"), drug_name="Pembrolizumab")
    )
    assert plan.notes == ()


# --- stated vs inferred (§7.3) ---


def test_verbatim_values_are_stated() -> None:
    plan = ok(
        build(
            "How has the number of trials for pembrolizumab changed per year since 2015?",
            reply("time_trend.start_year", drug_name="pembrolizumab", start_year=2015),
        )
    )
    assert plan.stated == {"drug_name": "pembrolizumab", "start_year": 2015}
    assert plan.inferred == {} and plan.assumptions == ()


def test_enum_display_label_in_the_query_is_stated() -> None:
    plan = ok(
        build(
            "Which countries have the most recruiting Phase 3 trials for cystic fibrosis?",
            reply(
                "geographic.country",
                condition="cystic fibrosis",
                overall_status="RECRUITING",
                trial_phase="PHASE3",
            ),
        )
    )
    assert plan.stated == {
        "condition": "cystic fibrosis",
        "overall_status": Status.RECRUITING,
        "trial_phase": Phase.PHASE3,
    }


def test_non_verbatim_value_is_inferred_and_disclosed() -> None:
    plan = ok(
        build(
            "How many lung cancer trials started each year over the last five years?",
            reply("time_trend.start_year", condition="lung cancer", start_year=2021),
        )
    )
    assert plan.stated == {"condition": "lung cancer"}
    assert plan.inferred == {"start_year": 2021}
    assert len(plan.assumptions) == 1 and "2021" in plan.assumptions[0]


def test_a_country_variant_mapped_to_its_registry_name_is_inferred() -> None:
    plan = ok(
        build(
            "Lung cancer trials in Korea per year",
            reply(
                "time_trend.start_year",
                condition="lung cancer",
                country="South Korea",
                constraints=[constraint("Korea", "country")],
            ),
        )
    )
    assert plan.stated == {"condition": "lung cancer"}
    assert plan.inferred == {"country": "South Korea"}
    assert "South Korea" in plan.assumptions[0]


def test_a_country_outside_the_registry_is_an_output_error() -> None:
    with pytest.raises(ValidationError, match="not a ClinicalTrials.gov country name"):
        build("Lung cancer trials in Korea", reply(condition="lung cancer", country="Korea"))


# --- constraint accounting (Phase 6 step 3) ---

PEDIATRIC = "How are pediatric asthma trials distributed across phases?"
ASTHMA = constraint("asthma", "condition")


def test_a_constraint_no_filter_expresses_asks_with_a_rephrase() -> None:
    result = clarify(
        build(
            PEDIATRIC,
            reply(
                condition="asthma",
                constraints=[ASTHMA, constraint("Pediatric", None, "no filter for age group")],
                suggested="How are asthma trials distributed across phases?",
            ),
        )
    )
    assert result.missing == ()
    assert result.unapplied == (("Pediatric", "no filter for age group"),)
    assert result.conflicts == ()
    assert result.suggested_query == "How are asthma trials distributed across phases?"
    assert any("Pediatric" in note and "no filter for age group" in note for note in result.notes)


def test_a_suggested_query_still_holding_the_unapplied_constraint_is_dropped() -> None:
    result = clarify(
        build(
            PEDIATRIC,
            reply(
                condition="asthma",
                constraints=[ASTHMA, constraint("pediatric", None, "no filter for age group")],
                suggested="How are pediatric asthma trials split by phase?",
            ),
        )
    )
    assert result.suggested_query is None


def test_two_values_for_one_filter_ask_naming_both() -> None:
    query = "How are lung cancer trials in Japan and Korea distributed across phases?"
    result = clarify(
        build(
            query,
            reply(
                condition="lung cancer",
                country="Japan",
                constraints=[
                    constraint("lung cancer", "condition"),
                    constraint("Japan", "country"),
                    constraint("Korea", "country"),
                ],
                suggested="How are lung cancer trials in Japan distributed across phases?",
            ),
        )
    )
    assert result.conflicts == (("country", ("Japan", "Korea")),)
    assert result.unapplied == ()
    assert any("Japan" in note and "Korea" in note for note in result.notes)


def test_compared_entities_are_cohorts_not_a_conflict() -> None:
    plan = ok(
        build(
            "Compare phases of pembrolizumab and nivolumab trials",
            reply(
                "comparison.phase",
                [cohort("pembrolizumab"), cohort("nivolumab")],
                constraints=[
                    constraint("pembrolizumab", "drug_name"),
                    constraint("nivolumab", "drug_name"),
                ],
            ),
        )
    )
    assert len(plan.cohorts) == 2


def test_a_compared_item_marked_not_applied_is_applied_by_its_cohort() -> None:
    """Seen live (2 in 20): the LLM quotes each cohort with applied_as null, "used as comparison
    cohort". The cohort's own search applies it, so it is not a constraint left out."""
    plan = ok(
        build(
            "Compare sponsor categories across lung cancer and colorectal cancer trials.",
            reply(
                "comparison.sponsor_class",
                [cohort("lung cancer", "condition"), cohort("colorectal cancer", "condition")],
                constraints=[
                    constraint("lung cancer", None, "used as comparison cohort"),
                    constraint("colorectal cancer", None, "used as comparison cohort"),
                ],
            ),
        )
    )
    assert [c.label for c in plan.cohorts] == ["lung cancer", "colorectal cancer"]


def test_words_that_describe_the_analysis_are_applied_by_it() -> None:
    """Seen live (2 in 15): "combination studies" quoted as not applicable, though co-occurrence
    in one trial is what network.drug_drug charts."""
    plan = ok(
        build(
            "Which drugs frequently co-occur in combination studies for melanoma?",
            reply(
                "network.drug_drug",
                condition="melanoma",
                constraints=[
                    constraint("melanoma", "condition"),
                    constraint("combination studies", None, "no filter for combination studies"),
                ],
            ),
        )
    )
    assert plan.analysis == "network.drug_drug"


def test_analysis_words_do_not_cover_a_real_constraint() -> None:
    result = clarify(
        build(
            "Which drugs co-occur in pediatric combination studies for melanoma?",
            reply(
                "network.drug_drug",
                condition="melanoma",
                constraints=[
                    constraint("melanoma", "condition"),
                    constraint("pediatric combination studies", None, "no filter for age group"),
                ],
            ),
        )
    )
    assert result.unapplied


def test_every_applied_constraint_keeps_the_plan() -> None:
    plan = ok(
        build(
            "Phases of melanoma trials",
            reply(condition="melanoma", constraints=[constraint("Melanoma", "condition")]),
        )
    )
    assert plan.stated == {"condition": "melanoma"}


@pytest.mark.parametrize(
    "bad,error",
    [
        (constraint("pediatric melanoma", "condition"), "not in the question"),
        (constraint("melanoma", "country"), "country"),  # applied as a filter left unset
        (constraint("phases", None), "reason"),  # not applied, but no reason given
    ],
)
def test_an_inconsistent_constraint_is_an_output_error(bad: dict[str, Any], error: str) -> None:
    with pytest.raises(LLMOutputError, match=error):
        build("Phases of melanoma trials", reply(condition="melanoma", constraints=[bad]))


# --- name coverage: no name in the question is silently dropped (hallucination guard) ---

BEIJING_JAPAN = "How are lung cancer trials in Beijing, Japan distributed across phases?"
JAPAN_ONLY = reply(
    condition="lung cancer",
    country="Japan",
    constraints=[constraint("lung cancer", "condition"), constraint("Japan", "country")],
)


def test_a_name_no_constraint_quotes_is_an_output_error_naming_it() -> None:
    with pytest.raises(LLMOutputError, match="Beijing"):
        build(BEIJING_JAPAN, JAPAN_ONLY)


def test_a_name_still_unquoted_after_the_retry_asks_instead_of_charting() -> None:
    """The LLM drops "Beijing" twice: Python, not the LLM, refuses to chart Japan alone."""
    llm, bodies = fake_llm(replies(json_reply(JAPAN_ONLY), json_reply(JAPAN_ONLY)))
    result = clarify(plan_request(VisualizeRequest(query=BEIJING_JAPAN), llm, TODAY))
    assert result.unapplied == (("Beijing", "the plan did not account for it"),)
    assert any("Beijing" in note for note in result.notes)
    assert "no constraint quotes" in bodies[1]["input"] and "Beijing" in bodies[1]["input"]


def test_a_lowercase_country_name_must_be_quoted_too() -> None:
    with pytest.raises(LLMOutputError, match="japan"):
        build(
            "lung cancer trials in beijing and japan by phase",
            reply(
                condition="lung cancer",
                constraints=[
                    constraint("lung cancer", "condition"),
                    constraint("beijing", None, "a city"),
                ],
            ),
        )


def test_an_age_or_sex_word_no_constraint_quotes_is_an_output_error() -> None:
    """Seen live (1 in 10): "pediatric" left out and asthma charted for every age. Lowercase, so
    the name rule misses it; no filter expresses age or sex, so such words must be quoted."""
    with pytest.raises(LLMOutputError, match="pediatric"):
        build(PEDIATRIC, reply(condition="asthma", constraints=[ASTHMA]))
    with pytest.raises(LLMOutputError, match="women"):
        build("Melanoma trials in women by phase", reply(condition="melanoma"))


def test_an_age_word_inside_a_condition_quote_is_accounted_for() -> None:
    llm = reply(
        condition="pediatric asthma", constraints=[constraint("pediatric asthma", "condition")]
    )
    ok(build(PEDIATRIC, llm))


@pytest.mark.parametrize(
    "query,filters,quotes",
    [
        # a possessive is the name
        ("What is the status breakdown of Pfizer's trials?", {"sponsor": "Pfizer"}, ["Pfizer"]),
        # a vocab label is a chart category, not a constraint
        ("Who funds asthma trials: industry, NIH or universities?", {"condition": "asthma"}, []),
        # a one-letter word counts when it is a whole word of a quote
        ("Enrollment for hepatitis C trials", {"condition": "hepatitis C"}, ["hepatitis C"]),
        # sentence starts are not names
        ("Melanoma trials by phase. Show them.", {"condition": "melanoma"}, []),
    ],
)
def test_quoted_names_labels_and_sentence_starts_are_accounted_for(
    query: str, filters: dict[str, str], quotes: list[str]
) -> None:
    key = next(iter(filters))
    llm = reply(constraints=[constraint(q, key) for q in quotes])
    llm["filters"] |= filters
    ok(build(query, llm))


def test_compared_names_are_accounted_for_by_their_cohorts() -> None:
    ok(
        build(
            "Compare Keytruda and Opdivo by phase",
            reply("comparison.phase", [cohort("Keytruda"), cohort("Opdivo")]),
        )
    )


# --- a comparison's dimension is never the kind being compared ---


def test_comparing_conditions_by_condition_is_an_output_error() -> None:
    with pytest.raises(LLMOutputError, match="comparison"):
        build(
            "Compare sponsor categories across lung cancer and colorectal cancer trials.",
            reply(
                "comparison.condition",
                [cohort("lung cancer", "condition"), cohort("colorectal cancer", "condition")],
            ),
        )


def test_comparing_drugs_by_condition_is_allowed() -> None:
    ok(
        build(
            "Conditions for pembrolizumab vs nivolumab",
            reply("comparison.condition", [cohort("pembrolizumab"), cohort("nivolumab")]),
        )
    )


def test_stated_match_ignores_case() -> None:
    plan = ok(build("PEMBROLIZUMAB by phase", reply(drug_name="pembrolizumab")))
    assert plan.stated == {"drug_name": "pembrolizumab"}


def test_contradictory_merged_years_are_an_output_error() -> None:
    with pytest.raises(LLMOutputError, match="start_year"):
        build(
            "melanoma trials per year until 2015",
            reply(end_year=2015),
            condition="melanoma",
            start_year=2020,
        )


# --- anchor rule (§7.8) ---


def test_no_anchor_asks_for_one() -> None:
    result = clarify(
        build(
            "How many trials started each year since 2020?",
            reply("time_trend.start_year", start_year=2020),
        )
    )
    assert result.missing == ANCHORS
    assert result.stated == {"start_year": 2020}
    assert any("drug, condition or sponsor" in note for note in result.notes)


@pytest.mark.parametrize("anchor", ANCHORS)
def test_each_anchor_satisfies_the_rule(anchor: str) -> None:
    llm = reply(constraints=[constraint("X", anchor)])
    llm["filters"][anchor] = "X"
    ok(build("trials by phase for X", llm))


def test_unsupported_question_asks_for_clarification_with_the_reason() -> None:
    result = clarify(
        build(
            "Which investigators run the most melanoma trials?",
            reply(condition="melanoma", unsupported="Investigators are not supported."),
        )
    )
    assert result.missing == ()
    assert "Investigators are not supported." in result.notes


# --- cohorts (§7.2) ---


def test_comparison_cohorts_override_one_entity_on_the_shared_filters() -> None:
    plan = ok(
        build(
            "Compare phases for pembrolizumab vs nivolumab since 2015",
            reply(
                "comparison.phase", [cohort("pembrolizumab"), cohort("nivolumab")], start_year=2015
            ),
        )
    )
    assert [c.label for c in plan.cohorts] == ["pembrolizumab", "nivolumab"]
    assert [c.filters.drug_name for c in plan.cohorts] == ["pembrolizumab", "nivolumab"]
    assert all(c.filters.start_year == 2015 for c in plan.cohorts)
    assert plan.filters.drug_name is None


@pytest.mark.parametrize("count", [0, 1, 5])
def test_cohort_count_outside_2_to_4_asks_for_clarification(count: int) -> None:
    names = ["a1", "b2", "c3", "d4", "e5"][:count]
    result = clarify(
        build(
            f"Compare phases for {', '.join(names)}",
            reply("comparison.phase", [cohort(n) for n in names] or None),
        )
    )
    assert result.missing == (ANCHORS if count == 0 else ())  # named cohorts are anchors
    assert any("2 to 4" in note for note in result.notes)


def test_four_cohorts_are_allowed() -> None:
    names = ["a", "b", "c", "d"]
    plan = ok(
        build(
            "Compare phases for a, b, c and d",
            reply("comparison.phase", [cohort(n) for n in names]),
        )
    )
    assert len(plan.cohorts) == 4


def test_mixed_cohort_entities_ask_for_clarification() -> None:
    cohorts = [cohort("pembrolizumab"), cohort("melanoma", "condition")]
    result = clarify(build("Compare pembrolizumab vs melanoma", reply("comparison.phase", cohorts)))
    assert any("one kind" in note for note in result.notes)


def test_cohort_entity_also_set_as_a_shared_filter_asks_for_clarification() -> None:
    cohorts = [cohort("pembrolizumab"), cohort("nivolumab")]
    result = clarify(
        build(
            "Compare phases for pembrolizumab vs nivolumab",
            reply("comparison.phase", cohorts),
            drug_name="aspirin",
        )
    )
    assert any("drug_name" in note for note in result.notes)


def test_cohort_value_not_in_the_query_is_disclosed() -> None:
    cohorts = [cohort("Keytruda"), {"label": "Opdivo", "entity": "drug_name", "value": "nivolumab"}]
    plan = ok(build("Compare phases for Keytruda vs Opdivo", reply("comparison.phase", cohorts)))
    assert len(plan.assumptions) == 1 and "nivolumab" in plan.assumptions[0]


def test_cohorts_outside_a_comparison_are_an_output_error() -> None:
    with pytest.raises(LLMOutputError, match="cohorts"):
        build("phases for a and b", reply("distribution.phase", [cohort("a"), cohort("b")]))


# --- the call: retry once with the error, then PlanError (§7.2) ---


def _plan(
    *responses: httpx2.Response, **fields: Any
) -> tuple[QueryPlan | Clarification, list[dict[str, Any]]]:
    llm, bodies = fake_llm(replies(*responses))
    request = VisualizeRequest.model_validate({"query": "Phases of melanoma trials", **fields})
    return plan_request(request, llm, today=TODAY), bodies


def test_valid_first_answer_is_used_with_the_registry_schema() -> None:
    result, bodies = _plan(json_reply(reply(condition="melanoma")))
    assert ok(result).filters.condition == "melanoma"
    assert len(bodies) == 1
    assert bodies[0]["text"]["format"]["schema"] == plan_schema()
    assert "2026-10-04" in bodies[0]["instructions"]


def test_user_message_carries_the_query_and_the_supplied_fields() -> None:
    _, bodies = _plan(json_reply(reply(condition="melanoma")), trial_phase="PHASE3")
    assert "Phases of melanoma trials" in bodies[0]["input"]
    assert "trial_phase" in bodies[0]["input"] and "PHASE3" in bodies[0]["input"]


def test_invalid_answer_is_retried_once_with_the_error() -> None:
    result, bodies = _plan(
        json_reply(reply("distribution.investigator", condition="melanoma")),
        json_reply(reply(condition="melanoma")),
    )
    ok(result)
    assert len(bodies) == 2
    assert "distribution.investigator" in bodies[1]["input"]


def test_malformed_json_is_retried_once() -> None:
    result, bodies = _plan(text_reply("not json"), json_reply(reply(condition="melanoma")))
    ok(result)
    assert len(bodies) == 2


def test_two_invalid_answers_raise_plan_error() -> None:
    with pytest.raises(PlanError, match="analysis"):
        _plan(
            json_reply(reply("distribution.investigator")),
            json_reply(reply("distribution.investigator")),
        )


def test_upstream_failure_is_not_retried_by_the_planner() -> None:
    with pytest.raises(LLMUpstreamError):
        _plan(httpx2.Response(500, json={"error": {"message": "down", "type": "server"}}))


# --- acceptance: the eval expectations, with the LLM's part stubbed ---
# The stub answers as a correct LLM would: the expected analysis, the expected stated values that
# no request field supplies, the first acceptable inferred value and the expected cohorts. This
# tests every rule Python applies on top of the LLM against expectations fixed before the code.
# Excluded: 422s (never planned) and clarifications with no anchor problem (the 5-cohort case,
# covered above), whose LLM answer the expectations do not determine. Field-vs-query overrides
# need the LLM to read the query, so they are asserted only in the live planner test.


def _derivable(q: EvalQuestion) -> bool:
    e = q.expected
    return e.http == 200 and not (e.status == "clarification_needed" and not e.missing)


ACCEPTANCE = [q for q in load_questions() if _derivable(q)]


def _stub_reply(q: EvalQuestion) -> dict[str, Any]:
    """A correct LLM answer derived from the expectation: each stated value is quoted where the
    question writes it, and a name left over is the wording of the one inferred filter
    ("Korea" for South Korea), as the prompt asks."""
    e = q.expected
    filters: dict[str, Any] = {k: v for k, v in e.stated.items() if k not in q.request}
    filters |= {k: values[0] for k, values in e.inferred.items()}
    cohorts = [c.model_dump() for c in e.cohorts] if e.cohorts else None
    query = str(q.request["query"])
    quotes = [
        constraint(str(v), k) for k, v in filters.items() if str(v).casefold() in query.casefold()
    ]
    left = unaccounted_names(
        query, [c["quote"] for c in quotes] + [c.label for c in e.cohorts or []]
    )
    if left and len(e.inferred) == 1:
        quotes += [constraint(name, next(iter(e.inferred))) for name in left]
    return reply(e.analysis or "distribution.phase", cohorts, constraints=quotes, **filters)


@pytest.mark.parametrize("question", ACCEPTANCE, ids=[q.id for q in ACCEPTANCE])
def test_eval_expectation_with_a_stubbed_llm(question: EvalQuestion) -> None:
    e = question.expected
    result = build_plan(
        VisualizeRequest.model_validate(question.request),
        LLMPlan.model_validate(_stub_reply(question)),
    )
    if e.status == "clarification_needed":
        assert clarify(result).missing == tuple(e.missing)
        return
    plan = ok(result)  # ok and no_results both plan; no_results is decided after the fetch
    assert plan.analysis == e.analysis
    assert {k: str(v) for k, v in plan.stated.items()} == {k: str(v) for k, v in e.stated.items()}
    assert plan.inferred.keys() == e.inferred.keys()
    for key, value in plan.inferred.items():
        assert value in e.inferred[key]
    if e.cohorts:
        assert [
            (c.label, getattr(c.filters, ec.entity))
            for c, ec in zip(plan.cohorts, e.cohorts, strict=True)
        ] == [(ec.label, ec.value) for ec in e.cohorts]
    if e.inferred:
        assert plan.assumptions
