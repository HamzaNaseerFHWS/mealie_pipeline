# 27: Find the right recipe page on the web for each recipe name

**What to build:** A `find` stage for Recipe Requests. For each request that has a `name` but no `url`, it searches the web, fetches the top candidates, and picks the page that really is that recipe. The chosen URL is stored on the request for ticket 28. Requests that already have a `url` skip the search and are only checked to be a real recipe page.

**How it works:**
1. **Search** through a `WebSearch` port: `search(query, language?, count) -> [SearchHit(url, title, snippet)]`. There are two real adapters, as decided in wayfinder 21:
   - **`DdgsSearch`** (primary): the `ddgs` library, no key. Region from the language, about 10 results, ≥ 3 s between queries (injected clock).
   - **`ClaudeWebSearch`** (fallback): `claude -p --tools "WebSearch"` with a JSON schema returning `{urls: [{url, title}]}`. Used only when `ddgs` errors, is rate-limited, or yields no valid candidate for that name.
   - `FakeWebSearch` returns scripted hits for tests.
2. **Build the query** from the per-language template in `config/settings.yaml` (`"{name} recipe"`, `"{name} Rezept"`), plus the sheet's cuisine/notes hint.
3. **Filter hits:** drop denylisted domains (`config/recipe_sites.yaml`: social media, Pinterest, Reddit, shops), drop duplicate URLs after normalization, and keep the top 5.
4. **Fetch and read** each candidate with ticket 06's `WebFetcher` and Structured Recipe Extraction. A candidate is valid only if it yields one real recipe (structured data or a recipe card) with ≥ 2 ingredients and ≥ 1 step. Pages listing many recipes ("25 best…") are invalid.
5. **Score** each valid candidate (pure, weights in settings):
   - name similarity between the requested name and the page's recipe name
   - structured-data quality (JSON-LD Recipe > plugin card > text)
   - completeness (ingredients, steps, times, yield, image)
   - language match with the sheet's hint
6. **Decide:**
   - Best score ≥ 0.75 and ≥ 0.1 ahead of the runner-up: `found`.
   - No valid candidate from either search source: `not_found`, with the reason.
   - Otherwise: `needs_choice`. The top 3 candidates (title, URL, score, ingredient preview) go to `review/request-<row>.md` and to `reports/request_choices.csv`, which has a `choice` column. The user writes 1–3, a different URL, or `skip`, and the next run continues from that. Choices always win over the scorer.

**Blocked by:** 26, 06; wayfinder ticket `21-recipe-name-search-provider.md` (resolved: read its Answer for the providers, denylist, query templates and thresholds)

**Status:** done

**Read first:** `spec.md` modules 3 (`WebFetcher`, `LLMBackend`), 6 (Source Builder), 15 (Reporter) and 18 (Recipe Requests); ticket 06. If ticket 17 is already done, use its rendered fetch for `needs_browser` pages; otherwise those candidates simply count as invalid.

- [x] The `WebSearch` port has the fake and both real adapters, with one shared contract test. The `ddgs` adapter is tested against recorded results (no live calls in CI). The `ClaudeWebSearch` adapter is tested with the stub `claude` executable from ticket 02, and its argument list includes `--tools "WebSearch"`, `--safe-mode` and the JSON schema, never `--bare`.
- [x] Query building, URL filtering and candidate scoring are pure and table-tested with hand-written cases:
  - an exact-name single-recipe page wins
  - a "25 best chicken recipes" listicle is rejected
  - a Pinterest/YouTube hit is dropped
  - two near-identical candidates give `needs_choice`
  - a German name with a `de` hint prefers a German page
  - a page whose recipe name doesn't resemble the request scores low
- [x] Fallback order is tested: a `ddgs` error, or no valid candidate from it, triggers `ClaudeWebSearch` for that name only. Both failing gives `not_found`. A search-source outage (both erroring) leaves requests `pending` and stops the stage with a clear message, rather than marking them `not_found`.
- [x] Pipeline-seam test with `FakeWebSearch` and fixture pages: three requests end as `found`, `not_found` and `needs_choice`. After the test writes `2` into `request_choices.csv`, the next run marks the third `found` with the second candidate's URL. A request with a `url` makes no search call.
- [x] Polite fetching is unchanged: robots.txt, ≥ 2 s per domain, on-disk cache.
- [x] `ddgs` is pinned to an exact version in `pyproject.toml`.

**Manual check on the laptop (user):** `uv run mp run --stages find` after importing your sheet. Open `reports/requests.csv` and `reports/request_choices.csv`, check that the chosen pages are the recipes you meant, and fill in `choice` where asked.

## Comments

### Built (2026-10-26)

`mp run --stages find` takes every `pending` Recipe Request to `found`, `not_found` or `needs_choice`. It writes nothing to Mealie and makes no Claude call except the optional search fallback. (The default `mp run` does not include `find`; ticket 28 wires requests into the normal run.)

- **WebSearch port** (`adapters/search.py`, `adapters/fake_search.py`): `DdgsSearch` (`ddgs` pinned to 9.16.1, region from the language, >= 3 s between queries through an injected clock), `ClaudeWebSearch` (`claude -p --tools "WebSearch" --safe-mode`, schema `{urls: [{url, title}]}`, `prompts/websearch.md`, never `--bare`; it reuses `ClaudeCliBackend`, which gained a `tools` setting) and `FakeWebSearch`. One shared contract test runs against all three (`tests/test_search_adapters.py`); the `ddgs` adapter is tested against recorded results (`tests/fixtures/ddgs_results.json`).
- **Pure logic** (`find.py`, table-tested): query building from `find.query_templates` plus the sheet's cuisine/notes hint; hit filtering (denylist from `links.py` + `config/recipe_sites.yaml`, listicle titles, duplicates after URL normalization, top 5); `single_recipe` (exactly one structured recipe with >= 2 ingredients; roundups and text-only pages are rejected); scoring (name similarity 0.5, structure 0.15, completeness 0.2, language fit 0.15, weights in `find.weights`); the decision (>= 0.75 and >= 0.1 ahead -> `found`, otherwise the top 3 -> `needs_choice`, none -> `not_found`).
- **Fallback order:** `ddgs` first; the Claude search only for a name where `ddgs` errored or yielded no valid candidate. If both sources raise, the stage stops with "Every search source failed ..." and the requests stay `pending` (nothing is marked `not_found`). A healthy but empty `ddgs` plus a failing fallback is `not_found`, with the fallback error in the reason.
- **Choices:** `reports/request_choices.csv` (request_id, cell, name, category, then title/url/score/ingredients for candidates 1-3, and an empty `choice` column) and `review/request-<cell>.md`. Write `1`, `2`, `3`, a full URL or `skip`; the next `mp run --stages find` applies it first and never searches that name again. An unreadable choice is reported and the request keeps waiting.
- **Sheet URL:** a request with a `url` makes no search call; the page is only checked to be a real single-recipe page.
- **Language:** the sheet's `language` column wins; otherwise `guess_language` (German words/umlauts/compound endings -> `de`, Devanagari -> `hi`, Arabic script -> `ur`, else `en`). It is a heuristic: set the `language` column for names it gets wrong.

### Notes and deviations

- Review files are named `request-<cell>.md` (for example `request-R2C1.md`) because with the grid layout a row number is not unique.
- `--dry-run` has no effect on `find` (it already writes nothing to Mealie).
- The live `ddgs` call could not be exercised from the agent sandbox (the outbound proxy blocks the search sites); the adapter reports that as a `SearchError`, and the fallback takes over.

### Manual verification on the laptop (user)

1. `uv sync`, then `uv run mp requests add --file "<path>\food_list_kategorien.csv.csv"` (379 requests).
2. Start small: `uv run mp run --stages find --limit 10`. It waits 3 s between searches and 2 s per website, so 10 names take a minute or two.
3. Open `reports/requests.csv`: `found` rows show `chosen_url` and `score`. Check that those pages are the recipes you meant.
4. If some say `needs_choice`, open `reports/request_choices.csv` (and `review/request-*.md`), fill `choice` with `1`, `2`, `3`, a URL or `skip`, and run the same command again.
5. If everything says "Every search source failed", `ddgs` is blocked or rate-limited and the Claude fallback failed too: check `uv run mp doctor` and try again later.
6. Then run without `--limit`; it continues with the pending requests (press Ctrl+C to stop between requests).
