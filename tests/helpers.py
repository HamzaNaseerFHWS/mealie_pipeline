"""Shared test construction: an Adapters bundle made of fakes."""

from typing import Any

from mealie_pipeline.adapters import Adapters
from mealie_pipeline.adapters.downloader import FakeImageDownloader
from mealie_pipeline.adapters.fake_llm import FakeLLM
from mealie_pipeline.adapters.fake_mealie import FakeMealie
from mealie_pipeline.adapters.fake_system import FakeSystemProbe
from mealie_pipeline.adapters.fake_video_source import FakeVideoSource
from mealie_pipeline.adapters.ingredient_engine import FakeIngredientEngine


def fake_adapters(**overrides: Any) -> Adapters:
    parts: dict[str, Any] = {
        "mealie": FakeMealie(),
        "system": FakeSystemProbe(),
        "llm": FakeLLM(),
        "videos": FakeVideoSource(),
        "images": FakeImageDownloader(),
        "engine": FakeIngredientEngine(),
    }
    parts.update(overrides)
    return Adapters(**parts)
