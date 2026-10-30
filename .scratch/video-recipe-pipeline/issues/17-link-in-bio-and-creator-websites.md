# 17: Find recipes behind link-in-bio pages, JS-only pages and Creator websites

**What to build:** Extend `scrape`:
- **Link-in-bio pages:** pages like `linktr.ee`, `lnk.bio` and `beacons.ai` (and pages marked `needs_browser` by ticket 06) are opened through the Browser adapter (plain, no login needed). Their links are collected, and the one matching the Video title is chosen.
- **Creator registry:** a Creator → Recipe Website registry is filled from channel "About" links, bio links and earlier Videos.
- **Site search:** when a Video has no recipe link but its Creator has a known Recipe Website, the site is searched in this order: WordPress search page, WP REST `/wp-json/wp/v2/posts?search=`, `sitemap.xml`. The page is matched by fuzzy title ≥ 85 and flagged `link_source=site_search`. Ticket 08's S1 check is then stricter (configurable).

**Blocked by:** 06, 14

**Status:** done

**Read first:** `spec.md` module 6; `PIPELINE_SPEC.md` §4.2.

- [x] Link-in-bio parsing is pure and tested on saved HTML fixtures for Linktree, lnk.bio and Beacons.
- [x] Creator registry: the same Creator on several platforms (handle match) shares one website. The website domain is learned from the first Video that links to it.
- [x] Site-search strategies are tested against a local `pytest-httpserver` serving a WP search page, a REST JSON response and a sitemap. Each strategy is tried in order, and the first confident match wins.
- [x] Pipeline-seam test: a reel whose caption says "recipe in bio" ends up with the website recipe through the Creator registry + site search, and its report row shows `link_source=site_search`.
- [x] Rendering through Playwright is used only for `needs_browser` pages and link-in-bio hosts (configurable list), never by default.

## Comments

**Built**
- `links.py`: pure link-in-bio parsing (`bio_links`) and title matching of bio buttons against the Video title (`web.bio_min_score`, default 70), tested on saved Linktree, lnk.bio and Beacons fixtures under `tests/fixtures/web/bio/`.
- `creators.py` + store migration 7 (`creator_websites`): a Creator → Recipe Website registry keyed by normalized handle, so the same Creator on several platforms shares one website; the first Video that links a website teaches it, later ones don't overwrite it.
- `site_search.py`: WordPress search page, then WP REST `/wp-json/wp/v2/posts?search=`, then `sitemap.xml` (following a sitemap index to the post sitemap); first page whose title fuzzy-matches ≥ `web.site_search_min_score` (85) wins. Tested against `pytest-httpserver`.
- Browser port: `fetch_rendered` on `PlaywrightBrowser` and `FakeBrowser`. Rendering is only used for link-in-bio hosts (`web.link_in_bio_hosts`) and pages the plain fetch marked `needs_browser` (`web.render_blocked`). A page that still shows a challenge stays `needs_browser`; it is never worked around.
- `scrape.py` / `pipeline.py`: open link-in-bio pages, render blocked pages, and fall back to site search on the Creator's website when the Video links no recipe. The Source records `link_source` (`description`, `pinned_comment`, `link_in_bio`, `site_search`, ...), shown as a new `link_source` column in `report.csv`.
- Stricter Gate for site-search recipes: `verify.site_search_upload_at` (default 90); below it a site-search recipe uploads with the review tag at best.
- New `web:` and `verify:` keys documented in `config/settings.yaml`.
- Pipeline-seam tests in `tests/test_link_in_bio_seam.py`.

**Deferred**
- Wiring the stricter S1 check itself (website vs video food overlap) for site-search recipes; the stricter upload bar stands in for it for now.
- Learning Recipe Websites from channel "About" links (needs a metadata source for About pages); the registry is currently filled from links in Videos and bio pages.
- Playwright response listening (reading JSON the page fetches, e.g. Linktree's API) instead of parsing the rendered DOM.

**Manual verification (on the laptop)**
1. A real Instagram reel whose caption says "recipe in bio" with a Linktree, one with lnk.bio and one with Beacons: `mp run` on each, check `reports/report.csv` shows `link_source=link_in_bio` and the right recipe in Mealie.
2. A Cloudflare-protected recipe site: the plain fetch comes back blocked, `fetch_rendered` in the pipeline Chrome profile reads it; if a challenge is still shown the item stays `needs_browser` (nothing clicks through it).
3. A reel with no recipe link from a Creator whose WordPress site is known: the recipe is found by site search, `link_source=site_search`, and it only uploads untagged at a score ≥ 90.
