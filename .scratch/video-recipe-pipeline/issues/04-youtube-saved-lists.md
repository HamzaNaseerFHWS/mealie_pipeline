# 04: Collect and re-sync YouTube Saved Lists, with URL normalization

**What to build:** The user registers a YouTube playlist with `mp lists add <playlist url>`, and `mp sync` (or the `collect` stage) enumerates every Video in it into the State Store. Each Video is stored once per Video Key even when it appears in several lists or with different URL forms, and membership is remembered per list. Re-syncing adds only new Videos. `mp lists` shows each list with its item count and last sync time. Any supported Video URL anywhere in the system goes through the pure URL Normalizer first.

**Blocked by:** 03

**Status:** done

**Read first:** `spec.md` modules 3 (`VideoSource.list_playlist`, `ListCollector`) and 4 (URL Normalizer); `PIPELINE_SPEC.md` §3.1.

- [x] The URL Normalizer is pure and table-tested for the cases below. Ticket 22 may already have built it (it comes first in the build order); if so, reuse it and add only the missing cases:
  - YouTube: watch, `youtu.be`, `/shorts/`, `m.` and `music.` hosts, the `si` parameter, playlist-context URLs
  - Instagram: `/p/`, `/reel/`, `/reels/`, `/tv/`, `igsh`
  - Facebook: `/reel/<id>`, `/watch/?v=`, `/<page>/videos/<id>`, `fbclid`, `mibextid`
  - Unsupported URLs
  - `fb.watch` and `/share/` links are marked "needs redirect resolution", and a resolver step follows the redirect before normalizing.
- [x] The YouTube collector uses yt-dlp's flat playlist extraction (no downloads). It stores title, channel and duration as early metadata, and pages through large playlists.
- [x] Sync is incremental: a pipeline-seam test with a fake collector returns 3 items, then 5 (2 new). The State Store ends with 5 Videos, 2 marked new in that sync, and the list's `last_synced` updated.
- [x] The same Video in two lists (and as `youtu.be` vs `watch?v=`) is one Video with two memberships.
- [x] Private lists (`list=WL`, `list=LL`, private playlists) fail with a clear message telling the user to run `mp login youtube` (built in ticket 14), not with a stack trace.

**Manual check on the laptop (user):** `uv run mp lists add <your YouTube playlist>` then `uv run mp sync`. Confirm `mp lists` shows the right count.

## Comments

**Built**
- `mp lists add <url>` registers a YouTube playlist (also `watch?v=…&list=…`, Watch Later `list=WL`, Liked `list=LL`) as a Saved List keyed `youtube:<list id>`; adding it again changes nothing. `mp lists` shows each list with its item count, last sync time and last problem. `mp sync [--list <url|key>]` collects.
- URL Normalizer (`url_normalizer.py`, from ticket 22) gained `normalize_list`, `needs_redirect` (`fb.watch`, Facebook `/share/…`) and `resolve(url, expand)`, which follows the redirect through `WebFetcher.expand` before normalizing. Added table cases for `music.` hosts, playlist-context watch URLs and the redirect links.
- `VideoSource.list_playlist` (yt-dlp `extract_flat="in_playlist"`, `lazy_playlist=True`, so large playlists page as they are consumed; nothing is downloaded). It yields `PlaylistEntry(url, title, channel, duration_s)`. yt-dlp errors that mean "log in first" become `LoginRequired`.
- `ListCollector` port (`adapters/collectors.py`) with `YouTubeCollector`, in the `Adapters` bundle as `collectors`. Without a login, WL/LL fail up front with the `mp login youtube` hint (ticket 14 sets `logged_in` once cookies exist).
- `collect.py` syncs lists one by one: one Video per Video Key, every URL form kept (`video_urls`), one membership per list, early metadata (`Video.early`), and only new memberships reported. A list that fails (private, network) records `last_error` and doesn't stop the others; `mp sync` then exits 1.
- State Store migration 6: `saved_lists`, `list_members` (first/last sync number), `video_urls`, `videos.early_json`. Existing Videos get their URL copied into `video_urls`.

**Deferred**
- Collect isn't a Stage Runner stage: it's `mp sync`, run before `mp run`. Ticket 23 (Auto Sync) can call `sync_lists` directly.
- A Video that drops out of a list keeps its membership (removal is never propagated). Marking it `unlisted` is left to ticket 23, which needs it; `list_members.last_sync` already makes it a query.
- The list title isn't fetched yet (the column exists).

**Manual check on the laptop (user)**
1. `uv run mp lists add "<one of your public YouTube playlist URLs>"`
2. `uv run mp sync`: it prints `<n> listed, <n> new`. Compare `n` with the playlist's video count on YouTube (deleted or private videos inside the playlist may be skipped or listed as unsupported).
3. `uv run mp lists`: the right count and a last-synced time.
4. `uv run mp sync` again: `0 new`.
5. `uv run mp lists add "https://www.youtube.com/playlist?list=WL"` then `uv run mp sync`: a clear `FAILED youtube:WL: needs a login … Run mp login youtube` line, no traceback.
