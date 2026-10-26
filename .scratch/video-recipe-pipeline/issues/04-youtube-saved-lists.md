# 04: Collect and re-sync YouTube Saved Lists, with URL normalization

**What to build:** The user registers a YouTube playlist with `mp lists add <playlist url>`, and `mp sync` (or the `collect` stage) enumerates every Video in it into the State Store. Each Video is stored once per Video Key even when it appears in several lists or with different URL forms, and membership is remembered per list. Re-syncing adds only new Videos. `mp lists` shows each list with its item count and last sync time. Any supported Video URL anywhere in the system goes through the pure URL Normalizer first.

**Blocked by:** 03

**Status:** ready-for-agent

**Read first:** `spec.md` modules 3 (`VideoSource.list_playlist`, `ListCollector`) and 4 (URL Normalizer); `PIPELINE_SPEC.md` §3.1.

- [ ] The URL Normalizer is pure and table-tested for the cases below. Ticket 22 may already have built it (it comes first in the build order); if so, reuse it and add only the missing cases:
  - YouTube: watch, `youtu.be`, `/shorts/`, `m.` and `music.` hosts, the `si` parameter, playlist-context URLs
  - Instagram: `/p/`, `/reel/`, `/reels/`, `/tv/`, `igsh`
  - Facebook: `/reel/<id>`, `/watch/?v=`, `/<page>/videos/<id>`, `fbclid`, `mibextid`
  - Unsupported URLs
  - `fb.watch` and `/share/` links are marked "needs redirect resolution", and a resolver step follows the redirect before normalizing.
- [ ] The YouTube collector uses yt-dlp's flat playlist extraction (no downloads). It stores title, channel and duration as early metadata, and pages through large playlists.
- [ ] Sync is incremental: a pipeline-seam test with a fake collector returns 3 items, then 5 (2 new). The State Store ends with 5 Videos, 2 marked new in that sync, and the list's `last_synced` updated.
- [ ] The same Video in two lists (and as `youtu.be` vs `watch?v=`) is one Video with two memberships.
- [ ] Private lists (`list=WL`, `list=LL`, private playlists) fail with a clear message telling the user to run `mp login youtube` (built in ticket 14), not with a stack trace.

**Manual check on the laptop (user):** `uv run mp lists add <your YouTube playlist>` then `uv run mp sync`. Confirm `mp lists` shows the right count.
