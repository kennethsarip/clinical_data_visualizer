"""A scripted OpenAI Responses API on httpx2.MockTransport, so LLM tests need no network or key."""

import json
from collections.abc import Callable
from typing import Any

import httpx2
import openai

from app.llm import LLMClient

MODEL = "gpt-test"
Handler = Callable[[httpx2.Request], httpx2.Response]


def response_body(
    content: list[dict[str, Any]], status: str = "completed", reason: str | None = None
) -> dict[str, Any]:
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 0,
        "model": MODEL,
        "status": status,
        "incomplete_details": {"reason": reason} if reason else None,
        "output": [
            {
                "type": "message",
                "id": "msg_test",
                "status": status,
                "role": "assistant",
                "content": content,
            }
        ],
    }


def text_reply(text: str, **kwargs: Any) -> httpx2.Response:
    return httpx2.Response(
        200,
        json=response_body([{"type": "output_text", "text": text, "annotations": []}], **kwargs),
    )


def json_reply(value: Any) -> httpx2.Response:
    return text_reply(json.dumps(value))


def refusal_reply(message: str) -> httpx2.Response:
    return httpx2.Response(200, json=response_body([{"type": "refusal", "refusal": message}]))


def fake_llm(handler: Handler) -> tuple[LLMClient, list[dict[str, Any]]]:
    """An LLMClient whose request bodies are recorded and whose replies come from `handler`."""
    bodies: list[dict[str, Any]] = []

    def recording(request: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(request.content))
        return handler(request)

    sdk = openai.OpenAI(
        api_key="test-key",
        base_url="https://llm.test/v1",
        http_client=httpx2.Client(transport=httpx2.MockTransport(recording)),
        max_retries=0,
    )
    return LLMClient(sdk, model=MODEL, reasoning_effort="low"), bodies


def replies(*responses: httpx2.Response) -> Handler:
    queue = iter(responses)
    return lambda request: next(queue)
