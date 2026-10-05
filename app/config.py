"""Single source of settings: every value comes from an env var (CLAUDE.md §3).

Env var names are the uppercased field names of `Settings`. `.env.example` must list exactly
these, which tests/test_config.py enforces in both directions. Fields without a default are
required; an empty value counts as unset, so a blank line in `.env` falls back to the default.
"""

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, PositiveInt, SecretStr, ValidationError

# The values gpt-5.4-mini accepts (verified against OpenAI's model page, 2026-10-04).
ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh"]


class ConfigError(RuntimeError):
    """A required env var is missing or empty, or a value has the wrong type."""


class Settings(BaseModel):
    openai_api_key: SecretStr
    openai_model: str
    # medium, not low: low misrouted 3/15 enrollment questions, medium 0/15, for ~0.2 s more
    # (live eval, 2026-10-04; CLAUDE.md §3).
    openai_reasoning_effort: ReasoningEffort = "medium"
    database_url: SecretStr  # may embed the DB password
    ctgov_base_url: str = "https://clinicaltrials.gov/api/v2"
    fetch_cap: PositiveInt = 2000  # max records fetched per request (CLAUDE.md §7.3)
    cache_ttl_hours: PositiveInt = 168


def env_var_names() -> set[str]:
    return {field.upper() for field in Settings.model_fields}


def required_env_var_names() -> set[str]:
    return {name.upper() for name, info in Settings.model_fields.items() if info.is_required()}


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    missing = sorted(name for name in required_env_var_names() if not env.get(name))
    if missing:
        raise ConfigError(f"Missing env vars: {', '.join(missing)}. See .env.example.")
    values: dict[str, str] = {}
    for field in Settings.model_fields:
        value = env.get(field.upper())
        if value:
            values[field] = value
    try:
        return Settings.model_validate(values)
    except ValidationError as exc:
        raise ConfigError(f"Invalid env var values: {exc}") from exc


def load_database_url(environ: Mapping[str, str] | None = None) -> str:
    """Only DATABASE_URL, for tools such as the migrator that never call the LLM."""
    env = os.environ if environ is None else environ
    url = env.get("DATABASE_URL")
    if not url:
        raise ConfigError("Missing env vars: DATABASE_URL. See .env.example.")
    return url
