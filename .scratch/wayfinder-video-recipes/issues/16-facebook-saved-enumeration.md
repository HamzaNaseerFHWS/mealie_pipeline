# 16: How does Facebook's saved-items page load, and what is the most robust way to enumerate saved videos and reels?

Type: research
Status: open
Blocked by: none
Mode: AFK

## Question

For a logged-in Playwright session on `https://www.facebook.com/saved/` (all items) and a saved collection (`?list_id=…` or `/saved/collections/…`), how should the collector get every saved video/reel URL?

Find out and record:

1. Whether items arrive through GraphQL responses that can be read while scrolling: request pattern, pagination cursor, and where the saved item's URL/ID and type sit.
2. Every URL form a saved video can take (`/reel/<id>`, `/watch/?v=<id>`, `/<page>/videos/<id>`, `fb.watch/<code>`, `/share/v/<code>`, `/share/r/<code>`) and how to normalize each to one Video Key.
3. How non-video saved items (links, posts, places) show up, so they can be skipped.
4. Stop signals (checkpoint, login wall, rate limit).
5. Whether current `yt-dlp` fetches metadata for each URL form with `cookies.txt`.

## Answer

_pending_
