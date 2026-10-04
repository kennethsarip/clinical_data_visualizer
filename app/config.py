"""Single source of settings: every value comes from an env var (CLAUDE.md §3).

Env var names are the uppercased field names of `Settings`. `.env.example` must list exactly
these, which tests/test_config.py enforces in both directions.
"""

import os
from collections.abc import Mapping

from pydantic import BaseModel, SecretStr


class ConfigError(RuntimeError):
    """A required env var is missing or empty."""


class Settings(BaseModel):
    openai_api_key: SecretStr
    openai_model: str
    database_url: SecretStr  # may embed the DB password


def env_var_names() -> set[str]:
    return {field.upper() for field in Settings.model_fields}


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    missing = sorted(name for name in env_var_names() if not env.get(name))
    if missing:
        raise ConfigError(f"Missing env vars: {', '.join(missing)}. See .env.example.")
    return Settings.model_validate({field: env[field.upper()] for field in Settings.model_fields})
