# 15: How does Instagram's web app load the saved "All posts" grid, and what is the most robust way to enumerate it?

Type: research
Status: open
Blocked by: none
Mode: AFK

## Question

For a logged-in Playwright session (real Chrome, persistent profile) on `https://www.instagram.com/<user>/saved/all-posts/`, how should the collector get every saved post/reel URL reliably?

Find out and record:

1. Whether the grid is filled from a JSON endpoint (for example a `feed/saved` or GraphQL call) that can be read by **listening to network responses** while scrolling. Record the request URL pattern, the pagination field (cursor / `more_available` / `next_max_id`), and where the shortcode and media type sit in the response. Prefer response-listening over DOM scraping.
2. The DOM fallback: the anchor patterns for tiles (`/p/<shortcode>/`, `/reel/<shortcode>/`) and how lazy loading behaves.
3. Signals of trouble to detect and **stop** on: login redirect, `challenge`/checkpoint URLs, "Try again later" / rate-limit responses (status codes, JSON keys).
4. Sensible human-like pacing for about 300 items, and whether the page caps how far back it loads.
5. Whether `yt-dlp` (current release) can fetch metadata (caption, uploader, duration, thumbnail) for a single `/p/` or `/reel/` URL using the exported `cookies.txt`, and which options it needs (for example impersonation via `curl_cffi`).

Sources to use: yt-dlp's Instagram extractor source and recent issues, Instaloader's source for saved posts, and recent public write-ups. Don't log in to anything.

## Answer

_pending: record findings here (endpoint patterns, field paths, stop signals, pacing), with links._
