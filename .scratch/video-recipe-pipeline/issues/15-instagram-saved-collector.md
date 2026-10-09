# 15: Collect Instagram saved "All posts"

**What to build:** An Instagram `ListCollector`. For `https://www.instagram.com/<user>/saved/all-posts/` (and a named saved collection URL), it opens the page in the pipeline Chrome profile and enumerates every saved post/reel by **listening to the network responses** the grid loads while scrolling. It falls back to reading tile anchors from the DOM. Scrolling is human-paced (randomized 1.5–4 s pauses, a per-session cap from settings) and it resumes from where it stopped. Instagram metadata (caption, uploader, duration, thumbnail, location) comes from yt-dlp with the exported cookies, at ≤ 60 Videos/hour by default. Stop signals end the platform's run cleanly.

**Blocked by:** 14; wayfinder ticket `15-instagram-saved-enumeration.md` (read its Answer: endpoint patterns, pagination fields, stop signals, yt-dlp options; implement against those findings)

**Status:** ready-for-agent

**Read first:** `spec.md` module 3 (`ListCollector`, `Browser`); `PIPELINE_SPEC.md` §3.1.

- [ ] Response parsing is pure and tested with trimmed, anonymized JSON fixtures in the shape wayfinder 15 recorded: shortcodes and media types out, cursor/"more available" handled, non-video posts kept (an image post with a recipe caption still counts) but marked `media_type`.
- [ ] The DOM fallback parser is pure and tested on a saved HTML snippet.
- [ ] Pacing and caps use the injected clock and are tested. Resume: a stored cursor or "last seen shortcode" stops enumeration early on re-sync.
- [ ] Pipeline-seam test with a fake browser that serves 3 response pages: 25 Videos collected, normalized to `instagram:<shortcode>`, deduped against an existing Video, and membership recorded.
- [ ] The metadata stage for Instagram uses yt-dlp with `cookiefile` and the options wayfinder 15 recorded. The rate limit is enforced by settings.

**Manual check on the laptop (user):** `uv run mp login instagram`, then `uv run mp lists add https://www.instagram.com/<you>/saved/all-posts/` and `uv run mp sync`. Compare the count with what you see in the app.
