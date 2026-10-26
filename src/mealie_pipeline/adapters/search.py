"""The WebSearch port: a recipe name in, candidate page addresses out (wayfinder 21).

Primary is the `ddgs` library (no key, no account, no Claude usage). The fallback is Claude Code's
built-in `WebSearch` tool through `claude -p`. Both return only titles and addresses: the pipeline
fetches and reads the pages itself.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from mealie_pipeline.adapters.llm import ClaudeCliBackend, LLMError, UsageLimited


class SearchError(Exception):
    """The search source failed (rate limit, network, parser change, no `claude`). Not "no results"."""


@dataclass(frozen=True)
class SearchHit:
    url: str
    title: str = ""
    snippet: str = ""


class WebSearch(Protocol):
    def search(self, query: str, language: str | None = None, count: int = 10) -> list[SearchHit]:
        """Hits for the query, best first. An empty list means "found nothing"; a failure raises."""
        ...


class DdgsSearch:
    """`ddgs` text search. `client` is injectable so tests replay recorded results."""

    def __init__(
        self,
        *,
        regions: dict[str, str] | None = None,
        min_delay_seconds: float = 3.0,
        client: Any = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.regions = regions or {"en": "us-en", "de": "de-de", "ur": "pk-en", "hi": "in-en"}
        self.min_delay = min_delay_seconds
        self._client = client
        self.clock = clock
        self.sleep = sleep
        self._last: float | None = None

    def _ddgs(self) -> Any:
        if self._client is None:
            from ddgs import DDGS  # imported lazily: not needed unless a search really runs

            self._client = DDGS()
        return self._client

    def search(self, query: str, language: str | None = None, count: int = 10) -> list[SearchHit]:
        if self._last is not None:
            wait = self.min_delay - (self.clock() - self._last)
            if wait > 0:
                self.sleep(wait)
        self._last = self.clock()
        region = self.regions.get(language or "en", "wt-wt")
        try:
            raw = self._ddgs().text(query, region=region, max_results=count)
        except Exception as err:  # ddgs raises its own family (rate limit, timeout, ...) and parser errors
            raise SearchError(f"ddgs: {type(err).__name__}: {err}") from err
        return [
            SearchHit(
                url=str(item["href"]), title=str(item.get("title") or ""), snippet=str(item.get("body") or "")
            )
            for item in raw or []
            if item.get("href")
        ]


class _Found(BaseModel):
    url: str
    title: str = ""


class _FoundList(BaseModel):
    urls: list[_Found]


class ClaudeWebSearch:
    """`claude -p --tools "WebSearch"` with a JSON schema `{urls: [{url, title}]}`."""

    def __init__(
        self, prompts_dir: Path, *, timeout_seconds: float = 300, models: dict[str, str] | None = None
    ):
        self._backend = ClaudeCliBackend(
            prompts_dir, models=models, timeout_seconds=timeout_seconds, tools="WebSearch"
        )

    def search(self, query: str, language: str | None = None, count: int = 10) -> list[SearchHit]:
        prompt = (
            f"Recipe to find: {query}\nLanguage of the sheet: {language or 'en'}\n"
            f"Return at most {count} results.\n"
        )
        try:
            raw = self._backend.complete("websearch", prompt, _FoundList.model_json_schema(), "fast")
            found = _FoundList.model_validate(raw)
        except UsageLimited as err:
            raise SearchError(f"claude usage limit: {err}") from err
        except (LLMError, ValueError) as err:
            raise SearchError(f"claude WebSearch: {err}") from err
        return [SearchHit(url=f.url, title=f.title) for f in found.urls[:count] if f.url]
