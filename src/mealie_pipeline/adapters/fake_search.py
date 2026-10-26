"""Scripted WebSearch for tests."""

from mealie_pipeline.adapters.search import SearchError, SearchHit


class FakeWebSearch:
    """Scripted hits by query substring; records every query. `fail` makes every search raise."""

    def __init__(self, hits: dict[str, list[SearchHit]] | None = None, *, fail: str | None = None):
        self.hits = hits or {}
        self.fail = fail
        self.queries: list[tuple[str, str | None]] = []

    def search(self, query: str, language: str | None = None, count: int = 10) -> list[SearchHit]:
        self.queries.append((query, language))
        if self.fail:
            raise SearchError(self.fail)
        for needle, found in self.hits.items():
            if needle.casefold() in query.casefold():
                return found[:count]
        return []
