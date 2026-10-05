"""Live LLM smoke test (`-m live`, needs `.env`): OpenAI accepts our strict schema and the reply
validates. The offline fakes cannot prove the first part, which is the main integration risk."""

from enum import StrEnum

import pytest
from pydantic import BaseModel, ConfigDict

from app.config import load_settings
from app.llm import LLMClient

pytestmark = pytest.mark.live


class Planet(StrEnum):
    MERCURY = "mercury"
    VENUS = "venus"
    EARTH = "earth"


class Nested(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str


class Reply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    planet: Planet
    moon_name: str | None = None
    detail: Nested


def test_structured_call_round_trips() -> None:
    client = LLMClient.from_settings(load_settings())
    reply = client.complete(
        instructions="Answer with the requested JSON only.",
        user_input="Which planet do humans live on, and what is its moon called?",
        name="planet_reply",
        output_type=Reply,
    )
    assert reply.planet is Planet.EARTH
    assert reply.moon_name is not None and "moon" in reply.moon_name.casefold()
