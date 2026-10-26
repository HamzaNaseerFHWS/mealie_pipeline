"""One shared contract for the WebSearch port, run against the fake and both real adapters."""

import json
from pathlib import Path

import pytest

from mealie_pipeline.adapters.fake_search import FakeWebSearch
from mealie_pipeline.adapters.search import ClaudeWebSearch, DdgsSearch, SearchError, SearchHit, WebSearch
from tests.test_claude_cli_backend import stub  # noqa: F401  (the stub `claude` executable fixture)

__all__ = ["stub"]

RECORDED = json.loads((Path(__file__).parent / "fixtures" / "ddgs_results.json").read_text(encoding="utf-8"))
KARAHI = SearchHit("https://www.example-kitchen.com/chicken-karahi/", "Authentic Chicken Karahi Recipe")


class RecordedDdgs:
    """Stands in for `ddgs.DDGS`: replays recorded results, or raises."""

    def __init__(self, results=None, error: Exception | None = None):
        self.results, self.error, self.calls = results or [], error, []

    def text(self, query, **kwargs):
        self.calls.append((query, kwargs))
        if self.error:
            raise self.error
        return self.results


@pytest.fixture(params=["fake", "ddgs", "claude"])
def adapter(request, stub, tmp_path):  # noqa: F811
    """`(search, set_outcome)`: `set_outcome("hits" | "empty" | "error")` scripts the next search."""
    kind = request.param
    if kind == "fake":
        fake = FakeWebSearch()

        def script(outcome):
            fake.hits = {"karahi": [KARAHI]} if outcome == "hits" else {}
            fake.fail = "boom" if outcome == "error" else None

        return fake, script
    if kind == "ddgs":
        client = RecordedDdgs()
        search = DdgsSearch(client=client, min_delay_seconds=0)

        def script(outcome):
            client.results = RECORDED if outcome == "hits" else []
            client.error = RuntimeError("202 Ratelimit") if outcome == "error" else None

        return search, script
    search = ClaudeWebSearch(tmp_path / "prompts")

    def script(outcome):
        if outcome == "error":
            stub.reply({"is_error": True, "result": "boom"}, exit_code=1)
        else:
            urls = [{"url": KARAHI.url, "title": KARAHI.title}] if outcome == "hits" else []
            stub.reply({"is_error": False, "structured_output": {"urls": urls}})

    return search, script


def test_hits_come_back_in_order_with_url_and_title(adapter):
    search, script = adapter
    script("hits")

    hits = search.search("Chicken Karahi recipe karahi", "en", 10)

    assert hits[0].url == KARAHI.url
    assert hits[0].title


def test_no_results_is_an_empty_list_not_an_error(adapter):
    search, script = adapter
    script("empty")

    assert search.search("zzz nothing", "en", 10) == []


def test_a_failing_source_raises_search_error(adapter):
    search, script = adapter
    script("error")

    with pytest.raises(SearchError):
        search.search("Chicken Karahi recipe", "en", 10)


# -- adapter specifics ---------------------------------------------------------------------------


def test_ddgs_replays_recorded_results_dropping_entries_without_an_address():
    client = RecordedDdgs(RECORDED)

    hits = DdgsSearch(client=client, min_delay_seconds=0).search("Chicken Karahi recipe", "en", 10)

    assert [h.url for h in hits] == [
        "https://www.example-kitchen.com/chicken-karahi/",
        "https://www.pinterest.com/pin/12345/",
        "https://www.youtube.com/watch?v=abc",
    ]
    assert hits[0].snippet.startswith("A Pakistani classic")


@pytest.mark.parametrize(
    ("language", "region"),
    [("en", "us-en"), ("de", "de-de"), ("ur", "pk-en"), ("hi", "in-en"), (None, "us-en")],
)
def test_ddgs_region_follows_the_language(language, region):
    client = RecordedDdgs(RECORDED)

    DdgsSearch(client=client, min_delay_seconds=0).search("q", language, 7)

    assert client.calls == [("q", {"region": region, "max_results": 7})]


def test_ddgs_waits_at_least_three_seconds_between_queries():
    now = [100.0]
    slept: list[float] = []

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    search = DdgsSearch(client=RecordedDdgs(RECORDED), clock=lambda: now[0], sleep=sleep)

    search.search("one", "en")  # the first query does not wait
    now[0] += 1.0  # one second passes
    search.search("two", "en")
    now[0] += 10.0
    search.search("three", "en")

    assert slept == [pytest.approx(2.0)]  # only the second query waited, for the missing 2 s


def test_claude_search_runs_with_the_websearch_tool_and_never_bare(stub, tmp_path):  # noqa: F811
    stub.reply({"is_error": False, "structured_output": {"urls": []}})

    ClaudeWebSearch(tmp_path / "prompts").search("Linsensuppe Rezept", "de", 5)

    recorded = stub.recorded()
    argv = recorded["argv"]
    assert argv[argv.index("--tools") + 1] == "WebSearch"
    assert "--safe-mode" in argv and "--bare" not in argv
    assert "--no-session-persistence" in argv
    schema = json.loads(argv[argv.index("--json-schema") + 1])
    assert "urls" in json.dumps(schema)
    assert argv[argv.index("--system-prompt-file") + 1] == str(tmp_path / "prompts" / "websearch.md")
    assert "Linsensuppe Rezept" in recorded["stdin"] and "at most 5" in recorded["stdin"]


def test_claude_search_turns_a_usage_limit_into_a_search_error(stub, tmp_path):  # noqa: F811
    stub.reply({"is_error": True, "result": "Claude usage limit reached."}, exit_code=1)

    with pytest.raises(SearchError, match="usage limit"):
        ClaudeWebSearch(tmp_path / "prompts").search("q", "en")


def test_the_websearch_prompt_exists():
    prompt = (Path(__file__).parents[1] / "prompts" / "websearch.md").read_text(encoding="utf-8")

    assert "Never invent" in prompt and "urls" in prompt


def test_fake_search_matches_by_substring_and_records_queries():
    fake: WebSearch = FakeWebSearch({"karahi": [KARAHI]})

    assert fake.search("Chicken KARAHI recipe", "en", 10) == [KARAHI]
    assert fake.search("Biryani recipe", "en", 10) == []
