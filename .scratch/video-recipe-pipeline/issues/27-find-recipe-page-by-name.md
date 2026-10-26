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

**Status:** ready-for-agent

**Read first:** `spec.md` modules 3 (`WebFetcher`, `LLMBackend`), 6 (Source Builder), 15 (Reporter) and 18 (Recipe Requests); ticket 06. If ticket 17 is already done, use its rendered fetch for `needs_browser` pages; otherwise those candidates simply count as invalid.

- [ ] The `WebSearch` port has the fake and both real adapters, with one shared contract test. The `ddgs` adapter is tested against recorded results (no live calls in CI). The `ClaudeWebSearch` adapter is tested with the stub `claude` executable from ticket 02, and its argument list includes `--tools "WebSearch"`, `--safe-mode` and the JSON schema, never `--bare`.
- [ ] Query building, URL filtering and candidate scoring are pure and table-tested with hand-written cases:
  - an exact-name single-recipe page wins
  - a "25 best chicken recipes" listicle is rejected
  - a Pinterest/YouTube hit is dropped
  - two near-identical candidates give `needs_choice`
  - a German name with a `de` hint prefers a German page
  - a page whose recipe name doesn't resemble the request scores low
- [ ] Fallback order is tested: a `ddgs` error, or no valid candidate from it, triggers `ClaudeWebSearch` for that name only. Both failing gives `not_found`. A search-source outage (both erroring) leaves requests `pending` and stops the stage with a clear message, rather than marking them `not_found`.
- [ ] Pipeline-seam test with `FakeWebSearch` and fixture pages: three requests end as `found`, `not_found` and `needs_choice`. After the test writes `2` into `request_choices.csv`, the next run marks the third `found` with the second candidate's URL. A request with a `url` makes no search call.
- [ ] Polite fetching is unchanged: robots.txt, ≥ 2 s per domain, on-disk cache.
- [ ] `ddgs` is pinned to an exact version in `pyproject.toml`.

**Manual check on the laptop (user):** `uv run mp run --stages find` after importing your sheet. Open `reports/requests.csv` and `reports/request_choices.csv`, check that the chosen pages are the recipes you meant, and fill in `choice` where asked.
