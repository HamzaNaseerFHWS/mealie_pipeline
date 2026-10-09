# 06: Use the Creator's Recipe Website when a Video links to it

**What to build:** A `scrape` stage that finds recipe links in a Video's description and the creator's pinned comment, expands short links, fetches the page politely, and pulls the recipe out of structured data. The order is:
1. JSON-LD Recipe, including `@graph`
2. microdata/RDFa
3. WPRM / Tasty Recipes / Mediavine card selectors from `config/site_selectors.yaml`
4. `recipe-scrapers`
5. main-text fallback

The result becomes the top-priority `web` Source for extraction. The extraction prompt then normalizes it instead of inventing, and the website image is preferred as the recipe image. A Video whose description has no recipe but links to a recipe page now imports with the website's exact ingredients.

**Blocked by:** 03

**Status:** ready-for-agent

**Read first:** `spec.md` modules 3 (`WebFetcher`) and 6; `PIPELINE_SPEC.md` §4.2–4.3.

- [ ] Link Discovery is pure and table-tested:
  - URL extraction from text (including bare domains and trailing punctuation)
  - an affiliate/shop/social domain denylist
  - choosing the link whose slug or anchor text best matches the Video title
- [ ] Short links (`bit.ly`, `tinyurl`, `geni.us`, and generic redirects) are expanded with HEAD/GET through the fetcher, and the final URL is recorded.
- [ ] Structured Recipe Extraction is pure and tested on saved HTML fixtures, at least: a WordPress+WPRM page with `@graph`, a Tasty Recipes page, a microdata page, a page with no recipe (main-text fallback), and a page with two Recipe objects (both returned, for ticket 12). Each records `extraction_method`.
- [ ] The httpx `WebFetcher` sends a real browser User-Agent, honours `robots.txt` for non-allowlisted domains, waits at least 2 s per domain (injected clock in tests), and caches on disk by URL. A blocked page (403/429 or a challenge page) is marked `needs_browser` for ticket 17 rather than failing.
- [ ] Pipeline-seam test: a Video whose description only says "Full recipe: https://…" (a fixture page) ends up in `FakeMealie` with the website's ingredient list. The `extract` call's prompt contains a `[SRC:web]` block, and the website image is uploaded.
- [ ] When structured data exists, the prompt tells the LLM to keep the website's quantities and wording and only fill gaps. A `FakeLLM` assertion checks this instruction is present.

**Manual check on the laptop (user):** add a Video that links to a recipe blog and run it. Confirm the Mealie ingredients match the blog.
