"""The Adapters bundle: every port the pipeline talks through, selected by one factory.

Tests construct `Adapters(...)` with fakes; the CLI builds the real ones from settings.
"""

from dataclasses import dataclass
from pathlib import Path

from mealie_pipeline.adapters.downloader import HttpImageDownloader, ImageDownloader
from mealie_pipeline.adapters.ingredient_engine import IngredientEngine, NlpIngredientEngine
from mealie_pipeline.adapters.llm import ClaudeCliBackend, LLMBackend
from mealie_pipeline.adapters.mealie import MealieGateway
from mealie_pipeline.adapters.mealie_http import MealieHttpGateway
from mealie_pipeline.adapters.system import RealSystemProbe, SystemProbe
from mealie_pipeline.adapters.video_source import VideoSource, YtDlpVideoSource
from mealie_pipeline.settings import Settings


@dataclass
class Adapters:
    mealie: MealieGateway
    system: SystemProbe
    llm: LLMBackend
    videos: VideoSource
    images: ImageDownloader
    engine: IngredientEngine


def build_adapters(settings: Settings, workspace: Path) -> Adapters:
    token = settings.mealie_token.get_secret_value() if settings.mealie_token else ""
    return Adapters(
        mealie=MealieHttpGateway(
            settings.mealie_url or "",
            token,
            timeout=settings.mealie.timeout_seconds,
            max_retries=settings.mealie.max_retries,
            backoff=settings.mealie.backoff_seconds,
        ),
        system=RealSystemProbe(),
        llm=ClaudeCliBackend(
            workspace / "prompts",
            models=settings.llm.models,
            timeout_seconds=settings.llm.timeout_seconds,
        ),
        videos=YtDlpVideoSource(),
        images=HttpImageDownloader(settings.images.timeout_seconds),
        engine=NlpIngredientEngine(),
    )
