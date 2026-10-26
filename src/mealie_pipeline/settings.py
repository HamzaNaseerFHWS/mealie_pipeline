"""Settings: `config/settings.yaml` defaults, overridden by `.env`, overridden by the environment.

Secrets (`MEALIE_URL`, `MEALIE_TOKEN`, `OPENAI_API_KEY`, `OPENAI_MAX_USD`) are read only from `.env`
or the environment. Nested yaml keys are overridden with a double underscore, such as
`MEALIE__TIMEOUT_SECONDS`.
"""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, Field, SecretStr, field_validator


class MealieSettings(BaseModel):
    timeout_seconds: float = 20
    max_retries: int = 3
    backoff_seconds: float = 1.0


class LlmSettings(BaseModel):
    timeout_seconds: float = 600
    # Overrides of the tier -> `claude --model` alias map: {"fast": "haiku", "strong": "sonnet", ...}.
    models: dict[str, str] = Field(default_factory=dict)


class ImageSettings(BaseModel):
    timeout_seconds: float = 20


class Settings(BaseModel):
    mealie: MealieSettings = Field(default_factory=MealieSettings)
    llm: LlmSettings = Field(default_factory=LlmSettings)
    images: ImageSettings = Field(default_factory=ImageSettings)
    mealie_url: str | None = None
    mealie_token: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    openai_max_usd: float = 5.0

    @field_validator("mealie_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str | None) -> str | None:
        return value.rstrip("/") if value else value or None


SECRET_FIELDS = {"mealie_url", "mealie_token", "openai_api_key", "openai_max_usd"}
NESTED_SECTIONS = {"mealie", "llm", "images"}


def _apply_overrides(data: dict[str, Any], overrides: Mapping[str, str | None]) -> None:
    for raw_key, value in overrides.items():
        if value is None or value == "":
            continue
        key = raw_key.lower()
        if "__" in key:
            section, _, name = key.partition("__")
            if section in NESTED_SECTIONS:
                data.setdefault(section, {})[name] = value
        elif key in SECRET_FIELDS:
            data[key] = value


def load_settings(workspace: Path, environ: Mapping[str, str] | None = None) -> Settings:
    """Loads settings for a workspace; `environ` defaults to the process environment."""
    data: dict[str, Any] = {}
    yaml_path = workspace / "config" / "settings.yaml"
    if yaml_path.is_file():
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    env_file = workspace / ".env"
    if env_file.is_file():
        _apply_overrides(data, dotenv_values(env_file, encoding="utf-8"))
    _apply_overrides(data, os.environ if environ is None else environ)
    return Settings.model_validate(data)
