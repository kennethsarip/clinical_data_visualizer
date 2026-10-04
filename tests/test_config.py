from pathlib import Path

import pytest

from app.config import ConfigError, env_var_names, load_settings

ENV_EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"

FULL_ENV = {
    "OPENAI_API_KEY": "sk-test",
    "OPENAI_MODEL": "model-x",
    "DATABASE_URL": "postgresql://user:pw@localhost/db",
}


def _env_example_entries() -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in ENV_EXAMPLE.read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            key, _, value = stripped.partition("=")
            entries[key.strip()] = value.strip()
    return entries


def test_env_example_lists_exactly_the_settings() -> None:
    assert set(_env_example_entries()) == env_var_names()


def test_env_example_values_are_blank() -> None:
    assert all(value == "" for value in _env_example_entries().values())


def test_load_settings_names_every_missing_var() -> None:
    with pytest.raises(ConfigError) as excinfo:
        load_settings({})
    for name in env_var_names():
        assert name in str(excinfo.value)


def test_load_settings_treats_empty_value_as_missing() -> None:
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        load_settings({**FULL_ENV, "OPENAI_API_KEY": ""})


def test_load_settings_reads_each_var() -> None:
    settings = load_settings(FULL_ENV)
    assert settings.openai_api_key.get_secret_value() == "sk-test"
    assert settings.openai_model == "model-x"
    assert settings.database_url.get_secret_value() == "postgresql://user:pw@localhost/db"
