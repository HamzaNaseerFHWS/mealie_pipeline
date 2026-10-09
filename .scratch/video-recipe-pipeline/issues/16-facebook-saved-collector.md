# 16: Collect Facebook saved items and collections

**What to build:** A Facebook `ListCollector` for `https://www.facebook.com/saved/` and saved collection URLs. It uses the pipeline Chrome profile, listens to the GraphQL responses while scrolling (DOM fallback), and keeps only saved **videos/reels**. Links, places and plain posts are recorded as skipped. Every Facebook URL form normalizes to one Video Key (share links resolved by redirect). Pacing, caps, resume and stop signals work as for Instagram. Metadata comes from yt-dlp with cookies.

**Blocked by:** 14; wayfinder ticket `16-facebook-saved-enumeration.md` (read its Answer and implement against it)

**Status:** ready-for-agent

**Read first:** `spec.md` modules 3 and 4; `PIPELINE_SPEC.md` §3.1.

- [ ] Response parsing is pure and tested with anonymized fixtures in the shapes wayfinder 16 recorded, incl. non-video saved items being filtered.
- [ ] The URL Normalizer cases from wayfinder 16 (all Facebook video URL forms) are added to its table tests.
- [ ] Pipeline-seam test with a fake browser: a mix of reels, watch videos, a link and a place → only Videos are stored; the rest are counted as skipped in `mp lists`.
- [ ] Pacing, caps and resume are tested with the injected clock, like ticket 15.

**Manual check on the laptop (user):** `uv run mp login facebook`, add your saved URL, and sync.
