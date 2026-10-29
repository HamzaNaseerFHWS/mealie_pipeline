"""Shared test construction: an Adapters bundle made of fakes, and a scripted classifier."""

import re
from collections.abc import Callable
from typing import Any

from mealie_pipeline.adapters import Adapters
from mealie_pipeline.adapters.collectors import YouTubeCollector
from mealie_pipeline.adapters.downloader import FakeImageDownloader
from mealie_pipeline.adapters.fake_browser import FakeBrowser
from mealie_pipeline.adapters.fake_llm import FakeLLM, LLMCall
from mealie_pipeline.adapters.fake_mealie import FakeMealie
from mealie_pipeline.adapters.fake_search import FakeWebSearch
from mealie_pipeline.adapters.fake_system import FakeSystemProbe
from mealie_pipeline.adapters.fake_video_source import FakeVideoSource
from mealie_pipeline.adapters.fake_web import FakeWebFetcher
from mealie_pipeline.adapters.ingredient_engine import FakeIngredientEngine


def fake_adapters(**overrides: Any) -> Adapters:
    parts: dict[str, Any] = {
        "mealie": FakeMealie(),
        "system": FakeSystemProbe(),
        "llm": FakeLLM(),
        "videos": FakeVideoSource(),
        "images": FakeImageDownloader(),
        "engine": FakeIngredientEngine(),
        "web": FakeWebFetcher(),
        "search": FakeWebSearch(),
        "search_fallback": FakeWebSearch(),
        "browser": FakeBrowser(),
    }
    parts.update(overrides)
    parts.setdefault("collectors", {"youtube": YouTubeCollector(parts["videos"])})
    return Adapters(**parts)


def classify_as(
    label: str = "recipe", confidence: float = 0.95, others: dict[str, str] | None = None
) -> Callable[[str], dict[str, Any]]:
    """A FakeLLM `classify` response: every Video Key in the prompt gets `label`, except the Video
    Keys in `others`, which get the label given there."""

    def answer(prompt: str) -> dict[str, Any]:
        keys = re.findall(r"^### video_key: (\S+)$", prompt, re.MULTILINE)
        return {
            "items": [
                {
                    "video_key": key,
                    "label": (others or {}).get(key, label),
                    "confidence": confidence,
                    "reasons": ["scripted"],
                }
                for key in keys
            ]
        }

    return answer


def recipe_llm() -> FakeLLM:
    """A FakeLLM whose classifier labels every Video a recipe."""
    llm = FakeLLM()
    llm.script("classify", classify_as("recipe"))
    return llm


def non_classify_calls(llm: FakeLLM) -> list[LLMCall]:
    """The recorded calls after classification: extraction, judge, ..."""
    return [c for c in llm.calls if c.task != "classify"]
