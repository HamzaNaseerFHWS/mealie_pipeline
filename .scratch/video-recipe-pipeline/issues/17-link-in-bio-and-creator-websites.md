# 17: Find recipes behind link-in-bio pages, JS-only pages and Creator websites

**What to build:** Extend `scrape`:
- **Link-in-bio pages:** pages like `linktr.ee`, `lnk.bio` and `beacons.ai` (and pages marked `needs_browser` by ticket 06) are opened through the Browser adapter (plain, no login needed). Their links are collected, and the one matching the Video title is chosen.
- **Creator registry:** a Creator → Recipe Website registry is filled from channel "About" links, bio links and earlier Videos.
- **Site search:** when a Video has no recipe link but its Creator has a known Recipe Website, the site is searched in this order: WordPress search page, WP REST `/wp-json/wp/v2/posts?search=`, `sitemap.xml`. The page is matched by fuzzy title ≥ 85 and flagged `link_source=site_search`. Ticket 08's S1 check is then stricter (configurable).

**Blocked by:** 06, 14

**Status:** in-progress

**Read first:** `spec.md` module 6; `PIPELINE_SPEC.md` §4.2.

- [ ] Link-in-bio parsing is pure and tested on saved HTML fixtures for Linktree, lnk.bio and Beacons.
- [ ] Creator registry: the same Creator on several platforms (handle match) shares one website. The website domain is learned from the first Video that links to it.
- [ ] Site-search strategies are tested against a local `pytest-httpserver` serving a WP search page, a REST JSON response and a sitemap. Each strategy is tried in order, and the first confident match wins.
- [ ] Pipeline-seam test: a reel whose caption says "recipe in bio" ends up with the website recipe through the Creator registry + site search, and its report row shows `link_source=site_search`.
- [ ] Rendering through Playwright is used only for `needs_browser` pages and link-in-bio hosts (configurable list), never by default.
