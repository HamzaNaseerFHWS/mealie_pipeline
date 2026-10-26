# 21: How does the pipeline find a recipe page on the web from just a recipe name?

Type: grilling
Status: resolved
Blocked by: none

## Question

For the one-off CSV/Excel import of recipe names (implementation tickets 26–28), which search source turns "Chicken Karahi" into candidate recipe-page URLs?

## Answer

Decided 2026-10-26. The user needs this **once**, so anything that works today is fine; long-term stability doesn't matter.

- **Google is out.** Its Custom Search JSON API is closed to new customers and is being discontinued on 2027-01-01. Vertex AI Search doesn't return the public web.
- **Primary: the `ddgs` Python library** ("Dux Distributed Global Search", PyPI `ddgs`, v9.16.1 checked 2026-10-26, Python ≥ 3.10). It's a metasearch library with **no API key, no account and no cost**, and no Claude usage. Use its text search with `region` from the sheet's language (`us-en`, `de-de`, `pk-en`/`in-en`), about 10 results per name, and ≥ 3 s between queries. Pin the exact version in `pyproject.toml`, because it's an unofficial scraper that can break. That's acceptable for a one-off.
- **Fallback: Claude Code's built-in `WebSearch` tool** through `claude -p` on the user's Pro subscription. It's used only for names where `ddgs` errors, is rate-limited, or returns no valid candidate. Call it with `--tools "WebSearch"` (still `--safe-mode`, `--output-format json`, `--json-schema` for `{"urls": [{url, title}]}`, `--no-session-persistence`). Per the Claude Code tools reference, WebSearch returns titles and URLs only, may run up to eight backend searches per call, and in `-p` mode its search limit applies per run. The pipeline fetches the pages itself.
- **Site preferences:** no allowlist is needed for a one-off. A small **denylist** is enough: Pinterest, YouTube/Instagram/Facebook/TikTok, Reddit, Amazon and other shops, and listicle/aggregator pages, plus any paywalled page that fails to parse.
- **Query template:** `"{name} recipe"` for English, `"{name} Rezept"` for German, `"{name} recipe"` for Urdu/Hindi names. The sheet's `cuisine`/`notes` hint is appended when present.
- **Candidates and thresholds:** fetch the top 5 valid hits. Accept automatically when the best score ≥ 0.75 and it leads the runner-up by ≥ 0.1. Otherwise the top 3 go to the user to pick (ticket 27).

No `.env` key is needed for either source.
