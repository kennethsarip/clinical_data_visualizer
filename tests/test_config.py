from pathlib import Path

import pytest

from app.config import ConfigError, env_var_names, load_settings, required_env_var_names

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


def test_load_settings_names_every_missing_required_var() -> None:
    with pytest.raises(ConfigError) as excinfo:
        load_settings({})
    for name in required_env_var_names():
        assert name in str(excinfo.value)


def test_required_vars_are_the_secrets_and_model() -> None:
    assert required_env_var_names() == {"OPENAI_API_KEY", "OPENAI_MODEL", "DATABASE_URL"}


def test_load_settings_treats_empty_value_as_missing() -> None:
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        load_settings({**FULL_ENV, "OPENAI_API_KEY": ""})


def test_load_settings_reads_each_var() -> None:
    settings = load_settings(FULL_ENV)
    assert settings.openai_api_key.get_secret_value() == "sk-test"
    assert settings.openai_model == "model-x"
    assert settings.database_url.get_secret_value() == "postgresql://user:pw@localhost/db"


def test_optional_vars_fall_back_to_defaults_when_blank() -> None:
    blank = {"CTGOV_BASE_URL": "", "FETCH_CAP": "", "CACHE_TTL_HOURS": ""}
    settings = load_settings({**FULL_ENV, **blank})
    # Defaults come from CLAUDE.md §14 Phase 1 and §8.4.
    assert settings.ctgov_base_url == "https://clinicaltrials.gov/api/v2"
    assert settings.fetch_cap == 2000
    assert settings.cache_ttl_hours == 168


def test_optional_vars_override_defaults() -> None:
    settings = load_settings({**FULL_ENV, "FETCH_CAP": "500", "CACHE_TTL_HOURS": "1"})
    assert settings.fetch_cap == 500
    assert settings.cache_ttl_hours == 1


@pytest.mark.parametrize("value", ["0", "-5", "lots"])
def test_invalid_fetch_cap_is_a_config_error(value: str) -> None:
    with pytest.raises(ConfigError, match="fetch_cap"):
        load_settings({**FULL_ENV, "FETCH_CAP": value})
