"""The only module that calls the LLM; returns validated models (CLAUDE.md §7.2).

One call shape, OpenAI structured outputs in strict mode: the model's answer must parse as JSON
against a schema generated from a Pydantic model, and is then validated by that model, so the
constraints strict mode cannot express (lengths, cross-field rules) are still enforced. Callers
never see unvalidated text.

Errors are typed for the single mapping in `pipeline.py` (§7.7): `LLMUpstreamError` means the LLM
could not be reached or rejected the call (502); `LLMOutputError` means it answered with something
unusable, which the caller may retry once with the error message.
"""

import logging
from typing import Any

import openai
from openai.types.responses import Response
from pydantic import BaseModel, ValidationError

from app.config import ReasoningEffort, Settings

logger = logging.getLogger(__name__)


TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 2  # the SDK retries connection errors, 429 and 5xx with backoff
# Plans and titles are a few hundred tokens; the cap bounds cost if the model rambles, and
# reasoning tokens count toward it. Hitting it surfaces as an incomplete response.
MAX_OUTPUT_TOKENS = 4000

# Keywords OpenAI strict mode accepts that we use. Everything else (lengths, defaults, titles) is
# dropped from the schema sent and enforced by Pydantic after the call instead.
_KEPT_KEYWORDS = frozenset(
    {"type", "properties", "required", "items", "enum", "const", "anyOf", "$ref", "$defs"}
    | {"description", "additionalProperties"}
)


class LLMUpstreamError(RuntimeError):
    """The LLM API was unreachable, timed out or returned an error status."""


class LLMOutputError(ValueError):
    """The LLM answered, but not with a valid instance of the requested model."""

    def __init__(self, message: str, raw: str | None = None) -> None:
        super().__init__(message)
        self.raw = raw


class LLMClient:
    def __init__(
        self,
        sdk: openai.OpenAI,
        model: str,
        reasoning_effort: ReasoningEffort,
        prose_reasoning_effort: ReasoningEffort,
    ) -> None:
        self._sdk = sdk
        self._model = model
        self._reasoning_effort = reasoning_effort
        self.prose_reasoning_effort = prose_reasoning_effort

    @classmethod
    def from_settings(cls, settings: Settings) -> "LLMClient":
        sdk = openai.OpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=TIMEOUT_SECONDS,
            max_retries=MAX_RETRIES,
        )
        return cls(
            sdk,
            settings.openai_model,
            settings.openai_reasoning_effort,
            settings.openai_prose_reasoning_effort,
        )

    def complete[M: BaseModel](
        self,
        *,
        instructions: str,
        user_input: str,
        name: str,
        output_type: type[M],
        schema: dict[str, Any] | None = None,
        reasoning_effort: ReasoningEffort | None = None,
    ) -> M:
        """One structured-output call; `name` labels the schema and every error message.

        `schema` overrides the one generated from `output_type`, for constraints known only at
        runtime (the registered analysis keys). The reply is still validated by `output_type`.
        `reasoning_effort` overrides the client's for this call.
        """
        try:
            response = self._sdk.responses.create(
                model=self._model,
                instructions=instructions,
                input=user_input,
                reasoning={"effort": reasoning_effort or self._reasoning_effort},
                max_output_tokens=MAX_OUTPUT_TOKENS,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": name,
                        "strict": True,
                        "schema": schema or strict_json_schema(output_type),
                    }
                },
            )
        except openai.APIStatusError as exc:
            raise LLMUpstreamError(f"LLM API returned HTTP {exc.status_code} for {name}") from exc
        except openai.APIError as exc:
            raise LLMUpstreamError(f"LLM API unreachable for {name}: {exc}") from exc
        return _parse(response, name, output_type)


def _parse[M: BaseModel](response: Response, name: str, output_type: type[M]) -> M:
    if response.status == "incomplete":
        details = response.incomplete_details
        reason = details.reason if details else "unknown reason"
        raise LLMOutputError(f"{name}: response incomplete ({reason})", response.output_text)
    refusal = _refusal(response)
    if refusal is not None:
        raise LLMOutputError(f"{name}: the model refused: {refusal}")
    raw = response.output_text
    try:
        return output_type.model_validate_json(raw)
    except ValidationError as exc:
        logger.warning("LLM output for %s failed validation: %s", name, exc)
        raise LLMOutputError(f"{name}: invalid output: {_summary(exc)}", raw) from exc


def _refusal(response: Response) -> str | None:
    for item in response.output:
        if item.type != "message":
            continue
        for part in item.content:
            if part.type == "refusal":
                return part.refusal
    return None


def _summary(exc: ValidationError) -> str:
    """Compact, model-readable errors (`inner.name: String should have at most 5 characters`),
    short enough to send back in the retry prompt."""
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}" for err in exc.errors()
    )


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """`model`'s JSON schema in the form OpenAI strict mode requires: every object lists all its
    properties as required and forbids others; optional fields stay as null unions."""
    schema: dict[str, Any] = _strict(model.model_json_schema())
    return schema


def _strict(node: Any) -> Any:
    if isinstance(node, list):
        return [_strict(item) for item in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key not in _KEPT_KEYWORDS:
            continue
        if key in ("properties", "$defs"):  # maps of name -> schema: keep every name
            out[key] = {name: _strict(sub) for name, sub in value.items()}
        else:
            out[key] = _strict(value)
    if out.get("type") == "object":
        if "properties" not in out:
            raise ValueError("strict mode needs fixed properties; a free-form map is unsupported")
        out["required"] = list(out["properties"])
        out["additionalProperties"] = False
    return out
