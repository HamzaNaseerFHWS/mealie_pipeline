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


class WebSettings(BaseModel):
    """Recipe Website fetching (the `scrape` stage)."""

    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )
    min_delay_seconds: float = 2.0  # per domain
    timeout_seconds: float = 20
    cache_dir: str = "data/web_cache"
    # Domains whose robots.txt is not consulted (your own sites).
    robots_allowlist: list[str] = Field(default_factory=list)
    max_pages: int = 3  # candidate links tried per Video
    fetch_pinned_comment: bool = True


class FindSettings(BaseModel):
    """The `find` stage: turning a recipe name into the right recipe page (ticket 27)."""

    # {name} is the requested name; the sheet's cuisine/notes hint is appended when present.
    query_templates: dict[str, str] = Field(
        default_factory=lambda: {
            "en": "{name} recipe",
            "de": "{name} Rezept",
            "ur": "{name} recipe",
            "hi": "{name} recipe",
        }
    )
    regions: dict[str, str] = Field(
        default_factory=lambda: {"en": "us-en", "de": "de-de", "ur": "pk-en", "hi": "in-en"}
    )
    default_language: str = "en"
    search_results: int = 10  # hits asked of the search source
    candidates: int = 5  # pages fetched per name
    search_delay_seconds: float = 3.0  # between two queries to the same source
    accept_score: float = 0.75  # the best candidate needs at least this ...
    accept_lead: float = 0.1  # ... and this much lead over the runner-up, else the user chooses
    min_name_similarity: float = 0.35  # a page whose recipe name is less alike than this is no candidate
    weights: dict[str, float] = Field(
        default_factory=lambda: {"name": 0.5, "structure": 0.15, "completeness": 0.2, "language": 0.15}
    )
    use_claude_fallback: bool = True


class VerifySettings(BaseModel):
    """The Gate: thresholds and weights for the Quality Score (0-100)."""

    upload_at: float = 80  # score >= this uploads as is
    review_at: float = 60  # score >= this (and < upload_at) uploads with the `To Review` tag
    judge_skip_at: float = 90  # the LLM judge runs only below this deterministic score
    grounding_threshold: float = 90  # fuzzy containment of an Evidence quote in its Source
    max_dropped_fraction: float = 0.2  # more ungrounded ingredients (or steps) than this fails H3
    soft_fail_below: float = 0.75  # a soft check scoring under this is listed as failed
    # Weight of each component in the weighted average. A check that does not apply yet (no website,
    # no transcript, no second parse engine) is left out of the average, not counted as zero.
    weights: dict[str, float] = Field(
        default_factory=lambda: {"H3": 20, "S1": 15, "S2": 25, "S3": 15, "S4": 10, "S5": 10, "S6": 15}
    )
    # Points the LLM judge takes off per problem it reports.
    judge_penalties: dict[str, float] = Field(
        default_factory=lambda: {"blocker": 30, "major": 15, "minor": 5}
    )
    review_tag: str = "To Review"


class Settings(BaseModel):
    mealie: MealieSettings = Field(default_factory=MealieSettings)
    verify: VerifySettings = Field(default_factory=VerifySettings)
    llm: LlmSettings = Field(default_factory=LlmSettings)
    images: ImageSettings = Field(default_factory=ImageSettings)
    web: WebSettings = Field(default_factory=WebSettings)
    find: FindSettings = Field(default_factory=FindSettings)
    mealie_url: str | None = None
    mealie_token: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    openai_max_usd: float = 5.0

    @field_validator("mealie_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str | None) -> str | None:
        return value.rstrip("/") if value else value or None


SECRET_FIELDS = {"mealie_url", "mealie_token", "openai_api_key", "openai_max_usd"}
NESTED_SECTIONS = {"mealie", "llm", "images", "verify", "web", "find"}


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
