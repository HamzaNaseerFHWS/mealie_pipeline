# 06: Use the Creator's Recipe Website when a Video links to it

**What to build:** A `scrape` stage that finds recipe links in a Video's description and the creator's pinned comment, expands short links, fetches the page politely, and pulls the recipe out of structured data. The order is:
1. JSON-LD Recipe, including `@graph`
2. microdata/RDFa
3. WPRM / Tasty Recipes / Mediavine card selectors from `config/site_selectors.yaml`
4. `recipe-scrapers`
5. main-text fallback

The result becomes the top-priority `web` Source for extraction. The extraction prompt then normalizes it instead of inventing, and the website image is preferred as the recipe image. A Video whose description has no recipe but links to a recipe page now imports with the website's exact ingredients.

**Blocked by:** 03

**Status:** done

**Read first:** `spec.md` modules 3 (`WebFetcher`) and 6; `PIPELINE_SPEC.md` §4.2–4.3.

- [x] Link Discovery is pure and table-tested:
  - URL extraction from text (including bare domains and trailing punctuation)
  - an affiliate/shop/social domain denylist
  - choosing the link whose slug or anchor text best matches the Video title
- [x] Short links (`bit.ly`, `tinyurl`, `geni.us`, and generic redirects) are expanded with HEAD/GET through the fetcher, and the final URL is recorded.
- [x] Structured Recipe Extraction is pure and tested on saved HTML fixtures, at least: a WordPress+WPRM page with `@graph`, a Tasty Recipes page, a microdata page, a page with no recipe (main-text fallback), and a page with two Recipe objects (both returned, for ticket 12). Each records `extraction_method`.
- [x] The httpx `WebFetcher` sends a real browser User-Agent, honours `robots.txt` for non-allowlisted domains, waits at least 2 s per domain (injected clock in tests), and caches on disk by URL. A blocked page (403/429 or a challenge page) is marked `needs_browser` for ticket 17 rather than failing.
- [x] Pipeline-seam test: a Video whose description only says "Full recipe: https://…" (a fixture page) ends up in `FakeMealie` with the website's ingredient list. The `extract` call's prompt contains a `[SRC:web]` block, and the website image is uploaded.
- [x] When structured data exists, the prompt tells the LLM to keep the website's quantities and wording and only fill gaps. A `FakeLLM` assertion checks this instruction is present.

**Manual check on the laptop (user):** add a Video that links to a recipe blog and run it. Confirm the Mealie ingredients match the blog.

## Comments

### Built (2026-10-26)

A `scrape` stage (per Video) now runs after `metadata` and `linkcheck`; `extract` waits for it. `STAGES = metadata, linkcheck, scrape, extract, parse, tag, verify, upload`. A Video whose Parts are all skipped by `linkcheck` (already in Mealie) is not scraped at all.

- **Link Discovery** (`links.py`, pure, table-tested): URLs from the description and the creator's pinned comment (bare domains, trailing punctuation), affiliate/shop/social denylist (applied again after short links are expanded), ranking by slug/anchor similarity to the Video title with a nudge for "recipe" URLs and home pages last.
- **WebFetcher** (`adapters/web.py` + `FakeWebFetcher`): httpx with a browser User-Agent, `robots.txt` honoured except for `web.robots_allowlist`, at least 2 s between requests to one domain (clock and sleep are injected), on-disk cache `data/web_cache/` by URL, `expand()` follows redirects (HEAD, then GET). 403/429 or a challenge page is returned as `needs_browser` (ticket 17 does the Playwright retry), `robots` as `robots`; none of these fails the Video. Contract-tested with httpx's mock transport, no network.
- **Structured Recipe Extraction** (`recipe_extraction.py`, pure): JSON-LD incl. `@graph`, microdata/RDFa, WPRM/Tasty/Mediavine cards from `config/site_selectors.yaml` (with sections), `recipe-scrapers`, then main text via trafilatura. Every result records `extraction_method`. Tested on saved HTML fixtures (`tests/fixtures/web/`): WPRM + Yoast `@graph`, Tasty card, microdata, WPRM card with sections, no recipe (main text), two Recipe objects (both returned; the one closest to the Video title is used until ticket 12).
- **Extraction:** `[SRC:web]` goes first in the prompt with the rule "Keep the website's quantities and wording and only fill gaps ..." (asserted through `FakeLLM`); unstructured page text is used only if it mentions ingredients and gets a different rule. `prompts/extract.md` explains `web` vs `desc`. The Gate's Sources now include `web`, so website evidence is grounded against the page text.
- **Image:** the website's image is tried before the thumbnail (and uploaded as a file first, as before).
- **VideoSource** gained `pinned_comments(url)` (yt-dlp comments, pinned and by the uploader; any failure returns "").

### Deferred / notes

- Link-in-bio pages, creator-website discovery and site search are ticket 17; the Playwright retry for `needs_browser` is ticket 17.
- Pages with several recipes: only the best title match is used (ticket 12 splits them).
- `scrape` results are cached in `data/<platform>/<id>/web.json`; `mp reset scrape` re-reads (the page itself comes from the web cache).
- `recipe-scrapers` is only tested through a stub (its real behaviour depends on the site).

### Manual verification on the laptop (user)

1. `uv sync`, then pick a YouTube video whose description (or pinned comment) links to the creator's recipe blog, ideally with a short link.
2. `uv run mp add "<url>"` and `uv run mp run --dry-run`. Check `data/youtube/<id>/web.json` (`final_url`, `extraction_method`) and `work/payloads/*.json`.
3. `uv run mp run`; open the Mealie recipe and compare the ingredients and steps with the blog. The recipe image should be the blog's.
4. Try a video linking only to Instagram/Amazon: it imports from the description as before. A blog behind Cloudflare shows a `needs_browser` warning but the Video still imports.
5. `data/web_cache/` holds the fetched pages; a second run makes no web requests.
