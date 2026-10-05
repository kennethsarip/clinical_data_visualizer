"""The LLM client: one structured-output call, validated before any caller sees it (CLAUDE.md §7.2).

Expected behavior comes from §7.2 (schema-validated output, typed errors), §7.7 (an unreachable LLM
is a 502, a malformed answer is retried by the caller) and OpenAI's strict-mode rules (every
property required, no additional properties, optional fields as null unions).
"""

from enum import StrEnum
from typing import Annotated, Any

import httpx2
import pytest
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.llm import LLMOutputError, LLMUpstreamError, strict_json_schema
from tests.llm_fakes import (
    MODEL,
    fake_llm,
    json_reply,
    refusal_reply,
    replies,
    text_reply,
)


class Color(StrEnum):
    RED = "red"
    BLUE = "blue"


class Inner(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(min_length=1, max_length=5)]


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    color: Color
    inner: Inner
    note: str | None = None
    tags: list[str] = Field(default_factory=list)


GOOD: dict[str, Any] = {"color": "red", "inner": {"name": "abc"}, "note": None, "tags": []}


def _complete(handler: Any) -> tuple[Answer, list[dict[str, Any]]]:
    client, bodies = fake_llm(handler)
    answer = client.complete(
        instructions="system text", user_input="user text", name="answer", output_type=Answer
    )
    return answer, bodies


# --- the call ---


def test_returns_the_validated_model() -> None:
    answer, _ = _complete(replies(json_reply(GOOD)))
    assert answer == Answer(color=Color.RED, inner=Inner(name="abc"))


def test_request_carries_model_effort_prompt_and_strict_schema() -> None:
    _, bodies = _complete(replies(json_reply(GOOD)))
    body = bodies[0]
    assert body["model"] == MODEL
    assert body["reasoning"] == {"effort": "low"}
    assert body["instructions"] == "system text"
    assert body["input"] == "user text"
    fmt = body["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True and fmt["name"] == "answer"
    assert fmt["schema"] == strict_json_schema(Answer)


def test_effort_can_be_lowered_per_call() -> None:
    # The title call needs no reasoning: 1.06 s median at "none" vs 2.0 s at medium, with
    # equivalent titles (measured on six eval questions, Phase 5.3).
    llm, bodies = fake_llm(replies(json_reply(GOOD)))
    llm.complete(
        instructions="i", user_input="u", name="answer", output_type=Answer, reasoning_effort="none"
    )
    assert bodies[0]["reasoning"] == {"effort": "none"}


# --- malformed output: LLMOutputError, which the caller retries once (§7.2) ---


def test_non_json_text_is_an_output_error() -> None:
    with pytest.raises(LLMOutputError, match="answer"):
        _complete(replies(text_reply("Sure! The color is red.")))


def test_json_failing_validation_is_an_output_error_naming_the_field() -> None:
    bad = {**GOOD, "inner": {"name": "far too long"}}
    with pytest.raises(LLMOutputError, match="inner.name"):
        _complete(replies(json_reply(bad)))


def test_unknown_enum_value_is_an_output_error() -> None:
    with pytest.raises(LLMOutputError, match="color"):
        _complete(replies(json_reply({**GOOD, "color": "green"})))


def test_refusal_is_an_output_error() -> None:
    with pytest.raises(LLMOutputError, match="refused"):
        _complete(replies(refusal_reply("I can't help with that.")))


def test_incomplete_response_is_an_output_error() -> None:
    reply = text_reply('{"color": "re', status="incomplete", reason="max_output_tokens")
    with pytest.raises(LLMOutputError, match="max_output_tokens"):
        _complete(replies(reply))


def test_output_error_keeps_the_raw_text_for_the_retry_prompt() -> None:
    with pytest.raises(LLMOutputError) as caught:
        _complete(replies(text_reply("not json")))
    assert caught.value.raw == "not json"


# --- unreachable or failing API: LLMUpstreamError, mapped to 502 (§7.7) ---


@pytest.mark.parametrize("status", [400, 401, 429, 500, 503])
def test_api_error_status_is_an_upstream_error(status: int) -> None:
    error = httpx2.Response(status, json={"error": {"message": "nope", "type": "x"}})
    with pytest.raises(LLMUpstreamError, match=str(status)):
        _complete(replies(error))


def test_connection_failure_is_an_upstream_error() -> None:
    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    with pytest.raises(LLMUpstreamError):
        _complete(down)


# --- strict schema (OpenAI strict mode; constraints are re-checked by Pydantic) ---


def _objects(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if node.get("type") == "object":
            found.append(node)
        for value in node.values():
            found.extend(_objects(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_objects(value))
    return found


def _keys(node: Any) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for v in node.values() for k in _keys(v)}
    if isinstance(node, list):
        return {k for v in node for k in _keys(v)}
    return set()


def test_strict_schema_requires_every_property_and_forbids_extras() -> None:
    objects = _objects(strict_json_schema(Answer))
    assert len(objects) == 2  # Answer and Inner
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])


def test_strict_schema_drops_keywords_strict_mode_rejects() -> None:
    keys = _keys(strict_json_schema(Answer))
    assert not keys & {"default", "minLength", "maxLength", "title"}


def test_strict_schema_keeps_enums_and_null_unions() -> None:
    schema = strict_json_schema(Answer)
    assert schema["$defs"]["Color"]["enum"] == ["red", "blue"]
    assert {"type": "null"} in schema["properties"]["note"]["anyOf"]


def test_an_explicit_schema_replaces_the_generated_one() -> None:
    """The planner narrows `analysis` to the registered keys, which a static model cannot."""
    client, bodies = fake_llm(replies(json_reply(GOOD)))
    schema = strict_json_schema(Answer)
    schema["properties"]["color"] = {"type": "string", "enum": ["red"]}
    client.complete(
        instructions="i", user_input="u", name="answer", output_type=Answer, schema=schema
    )
    assert bodies[0]["text"]["format"]["schema"]["properties"]["color"]["enum"] == ["red"]
