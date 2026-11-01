# 15: How does Instagram's web app load the saved "All posts" grid, and what is the most robust way to enumerate it?

Type: research
Status: resolved
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

Researched 2026-11-01 from source code only. Nothing was logged in to. Instagram's internal web API is undocumented and changes often, so every endpoint name below is **what current sources observe, not a contract**. The design consequence is the main finding:

> **Recognize the saved feed by shape, not by an exact endpoint.** Listen to every `instagram.com` API response while scrolling, accept the ones that are (a) on a saved-feed REST path, or (b) a GraphQL body with a key containing `saved`, then walk the JSON for media nodes (`code` + `user`/`owner`). Never forge requests or hardcode a `doc_id`/`query_hash`. Those rotate (Instaloader reports Instagram deprecated several GraphQL doc_ids around June 2026: [instaloader#2706](https://github.com/instaloader/instaloader/pull/2706)).

### 1. Network responses (primary path)

The saved grid is filled from JSON that arrives in **two shapes**, depending on route/build ([saved-post-analyzer `extract.ts` / `ARCHITECTURE.md` §2](https://github.com/dipscoder/instagram-saved-post-analyzer), a 2026 Chrome extension that captures exactly this page by intercepting the page's own responses):

| Shape | URL pattern (match loosely, case-insensitive) | Media list | Pagination |
|---|---|---|---|
| REST | `/api/v1/feed/saved` (e.g. `/api/v1/feed/saved/posts/`); named collections: `/api/v1/collections/` or `/api/v1/feed/collection/` | `items[].media` | top-level `more_available` (bool) + `next_max_id` (string, sent back as `max_id`) |
| GraphQL | `POST /graphql/query` or `/api/graphql` (shared by the whole site, so the URL alone proves nothing) | `data.xdt_api__v1__feed__saved__posts.edges[].node.media` (older builds: `data.user.edge_saved_media.edges[].node`) | `…page_info.has_next_page` + `…page_info.end_cursor` |

REST field names come from [instagram-private-api `SavedFeed`](https://github.com/dilame/instagram-private-api/blob/master/src/feeds/saved.feed.ts) and its [response type](https://github.com/dilame/instagram-private-api/blob/master/src/responses/saved.feed.response.ts). The GraphQL `xdt_api__v1__…` node wraps the *same* v1 media object. Instaloader's `get_feed_posts` uses the identical `more_available`/`next_max_id` loop on `api/v1/feed/timeline/` ([`instaloader.py`](https://github.com/instaloader/instaloader/blob/master/instaloader/instaloader.py)). Instaloader's own `get_saved_posts` still uses the legacy GraphQL `query_hash` `f883d95537fbcd400f466f63d42bd8a1` → `data.user.edge_saved_media` ([`structures.py`](https://github.com/instaloader/instaloader/blob/master/instaloader/structures.py)). That is a fallback shape to recognize, not an endpoint to call.

**Fields on a media node** (same object in both shapes):

- `code`: the shortcode → `instagram:<code>`. Older GraphQL uses `shortcode`.
- `pk` / `id`: numeric media id (`id` is `<pk>_<owner_pk>`).
- `media_type`: `1` image, `2` video, `8` carousel. Older GraphQL uses `is_video` / `__typename` (`GraphImage`, `GraphVideo`, `GraphSidecar`).
- `product_type`: `"clips"` = reel, `"feed"` = regular post, `"carousel_container"`. Use it to choose `/reel/` versus `/p/` for the canonical URL. Either URL resolves, so `https://www.instagram.com/p/<code>/` is always safe.
- `carousel_media[]`: slides (each has its own `media_type`). **Don't descend into it** when collecting. The user saved the outer post, so slides and embedded originals are not saved items.
- `caption.text`, `user.username`, `user.full_name`, `user.pk`, `taken_at` (post time, unix seconds), `video_duration`, `image_versions2.candidates[].url`, `location` (`name`, `pk`, `lat`, `lng`, when present).
- There is **no save timestamp**. The feed order is newest-saved first. That ordering is what makes "stop at last-seen shortcode" resume work.

A media node is recognized as `code|shortcode` (string, ≥ 5 chars) **plus** a `user|owner` object. The owner test excludes unrelated `code` fields such as currency or country codes. Saved-post-analyzer reports ~12 posts per network page.

**Trimmed fixture shapes for ticket 15's tests** (anonymized; values illustrative):

```json
{"items":[{"media":{"pk":"3100000000000000001","id":"3100000000000000001_42","code":"DAbCdEfGhIj",
  "media_type":2,"product_type":"clips","taken_at":1761955200,"video_duration":48.2,
  "caption":{"text":"Chicken karahi recipe 👇 ..."},"user":{"pk":"42","username":"somecook","full_name":"Some Cook"},
  "image_versions2":{"candidates":[{"url":"https://scontent.example/x.jpg","width":640,"height":1138}]}}},
 {"media":{"pk":"3100000000000000002","code":"DAbCdEfGhIk","media_type":1,"product_type":"feed",
  "caption":{"text":"Ingredients: ..."},"user":{"pk":"43","username":"other"}}}],
 "num_results":2,"more_available":true,"next_max_id":"QVFE...","status":"ok"}
```

```json
{"data":{"xdt_api__v1__feed__saved__posts":{
  "edges":[{"node":{"media":{"code":"DAbCdEfGhIl","pk":"3100000000000000003","media_type":8,
    "product_type":"carousel_container","user":{"username":"x"},"caption":{"text":"..."},
    "carousel_media":[{"code":"DAbCdEfGhIl","media_type":2,"user":{"username":"x"}}]}}}],
  "page_info":{"has_next_page":false,"end_cursor":null}}},"status":"ok"}
```

**Playwright mechanics:** `page.on("response", …)`, filter by `response.url` against the patterns above and by `request.resource_type in ("xhr","fetch")`, then `await response.json()` in a try/except. Non-JSON and unrelated bodies are ignored silently. Register the listener **before** `page.goto(...)`. Always do a fresh `goto`, not back/forward navigation: a bfcache or client-side route restore can paint tiles from memory with no network call, which is why the DOM fallback exists.

**End of list:** `more_available == false` (REST) or `has_next_page == false` (GraphQL). Secondary signal: N (≈ 3) consecutive scrolls that produce no new response and no new tile.

### 2. DOM fallback

- Anchors inside `<main>` only (otherwise "more from this creator" strips and profile grids get scraped): `a[href^="/p/"], a[href^="/reel/"], a[href^="/tv/"]`, shortcode regex `^/(?:p|reel|tv)/([A-Za-z0-9_-]{5,})` on the anchor's pathname ([saved-post-analyzer `dom-scrape.ts`](https://github.com/dipscoder/instagram-saved-post-analyzer)). Hrefs may carry a `/<username>/` prefix (yt-dlp's URL regex allows `instagram.com/<user>/p/<id>`), so match `/(?:p|reel|tv)/<code>` anywhere in the path.
- Video/reel hint: an `svg[aria-label*="Reel" i]`, `svg[aria-label*="Video" i]` or `<video>` inside the tile. Caption is not in the DOM. The `img alt` is an auto-description (`"Photo by @handle on …"`), useful only for the handle.
- Lazy loading: tiles are appended as the page scrolls and each new batch triggers one feed request. Collect anchors **after every scroll** into a set, not once at the end, because whether off-screen rows are removed from the DOM (virtualization) is unconfirmed. Verify on the laptop.
- Only run the DOM parser when the URL path is still `/<user>/saved/…`.

### 3. Stop signals (end the platform's run cleanly, don't retry)

| Signal | Where to see it | Source |
|---|---|---|
| Redirect to `/accounts/login` (or bare `/`) | `page.url` after `goto`/scroll; a 30x `location` header on an API response | Instaloader `_raise_if_login_redirect`; yt-dlp `_is_login_redirect` ([`instagram.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/instagram.py)) |
| URL contains `/challenge/`, `/checkpoint/`, `/accounts/suspended/`, or `/auth_platform/` | `page.url` | `checkpoint_url` handling in Instaloader login; the URL forms are commonly reported and should be confirmed on the laptop |
| HTTP **429** on *any* `instagram.com/api` or `/graphql` call | response listener | Instaloader `TooManyRequestsException`; saved-post-analyzer halts auto-scroll on any 429 |
| HTTP **400** with JSON `message` in `feedback_required`, `checkpoint_required`, `challenge_required` (often with `"status":"fail"`, plus `checkpoint_url` / `spam: true`) | response JSON | Instaloader `_raise_for_status` treats these as abort, not retry ([`instaloadercontext.py`](https://github.com/instaloader/instaloader/blob/master/instaloader/instaloadercontext.py)) |
| JSON `"status":"fail"` with a "Please wait a few minutes before you try again" style `message`, or the page showing "Try again later" | response JSON / page text | widely reported; treat any `status != "ok"` on a saved-feed response as stop |
| 401/403 on the saved feed | response listener | treat as logged out |

### 4. Pacing and depth

- ~300 items ≈ **25 feed pages** at ~12/page. Ticket 15's randomized 1.5–4 s pause per scroll step (a fixed cadence is itself a bot signal) gives roughly 3–6 minutes for 300 items. That is far below Instaloader's own self-imposed limits (75 non-GraphQL requests or 200 per GraphQL query type per 11-minute window, 275 GraphQL total per 10 minutes: `RateController` in `instaloadercontext.py`). Saved-post-analyzer uses 800–2000 ms and stops on the first 429. Recommended defaults: 1.5–4 s between scrolls, plus a longer 20–60 s pause every ~10 pages, and a per-session cap of ~40 feed pages (~500 items) from settings.
- **Resume:** don't store `next_max_id` / `end_cursor` across sessions. They are opaque and may expire. Store the most recent few shortcodes already seen (newest-saved first). On re-sync, stop after ~5 consecutive already-known shortcodes. A single known one could be a re-save. For an interrupted *first* full sync, re-scroll from the top and skip known items. The page cost is small.
- **How far back:** no source documents a cap on the saved feed. Instaloader iterates it to the end. Unconfirmed: compare the collected count against the app (already the ticket's manual check).

### 5. yt-dlp metadata for a single post/reel

Current release is **2026.10.26**. Behaviour from [`yt_dlp/extractor/instagram.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/instagram.py):

- `/p/<code>`, `/reel/<code>`, `/reels/<code>`, `/tv/<code>` (optionally `/<user>/` prefixed) are all handled by `InstagramIE`.
- **With cookies** (a `sessionid` cookie in `cookiefile`): it converts the shortcode to a media pk and calls `GET https://www.instagram.com/api/v1/media/<pk>/info/` with `X-IG-App-ID: 936619743392459`, then reads `items[0]`. Output: `description` (caption), `channel` (username), `uploader` (full name), `uploader_id`, `timestamp`, `duration`, `thumbnails`, `like_count`, `comment_count`, `view_count`. If the cookie is rejected (login redirect) it warns "account cookies are no longer valid" and falls back to logged-out extraction. **Detect that warning or a `login required` error and treat it as the "re-export cookies" stop signal.**
- **Impersonation:** install `yt-dlp[curl-cffi]` (pinned `curl-cffi==0.17.0` in yt-dlp's `pin-curl-cffi` extra; has Windows wheels). No `impersonate` option needs to be passed: the extractor checks `_impersonate_target_available(ImpersonateTarget())` and impersonates automatically. The logged-out GraphQL path only runs at all when impersonation is available. Without cookies, "rate-limit reached or login required" is still the common 2026 failure ([yt-dlp#16311](https://github.com/yt-dlp/yt-dlp/issues/16311), [#11166](https://github.com/yt-dlp/yt-dlp/issues/11166)), so cookies are required.
- **Image posts:** an image-only post raises "There is no video in this post" (`raise_no_formats`). Pass **`ignore_no_formats_error: True`** to keep the caption/uploader metadata. Image recipe posts count, as ticket 15 requires. Carousels come back as `_type: "playlist"` with one entry per slide. Take the post-level fields from the playlist dict.
- **Location** is in the raw `media/info` JSON but yt-dlp **does not output it**. Take `location` from the saved-feed media node captured during enumeration (§1). This differs from ticket 15's text ("location … comes from yt-dlp"); the collector ticket should follow this finding.
- **Recommended `YoutubeDL` options:** `{"cookiefile": <cookies.txt>, "skip_download": True, "ignore_no_formats_error": True, "quiet": True, "no_warnings": False}` plus a logger that captures warnings. Optional: `"extractor_args": {"instagram": {"app_id": ["web"]}}`, which is already the default. Rate: one `media/info` call per post, so ≤ 60 Videos/hour (the ticket's default) is very conservative.
- The enumeration response already contains caption, uploader, duration and thumbnail for most items. The collector can store them right away and call yt-dlp only to fill gaps or refresh. That cuts yt-dlp calls (and risk) a lot. This is an option for ticket 15, not a requirement.

### Still to confirm on the laptop (user, manual)

1. Open `https://www.instagram.com/<you>/saved/all-posts/` in the pipeline Chrome profile, then DevTools → Network → Fetch/XHR, and scroll. Note which of the two shapes appears (REST `feed/saved…` or GraphQL with `xdt_api__v1__feed__saved__posts`) and the page size. Save one response, anonymize it, and replace the illustrative fixtures above if it differs.
2. Scroll a long way and check whether early tiles leave the DOM (virtualization).
3. Compare the final tile count against the app.
4. `uv run yt-dlp --cookies cookies.txt -J --skip-download --ignore-no-formats-error https://www.instagram.com/p/<an image post>/` and the same for a reel. Both should print caption and uploader.

### Sources

- yt-dlp Instagram extractor, master at release 2026.10.26: https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/instagram.py
- yt-dlp issues: https://github.com/yt-dlp/yt-dlp/issues/16311, https://github.com/yt-dlp/yt-dlp/issues/11166, https://github.com/yt-dlp/yt-dlp/issues/10462
- Instaloader: `structures.py` (`get_saved_posts`), `instaloader.py` (`get_feed_posts`), `instaloadercontext.py` (stop signals, `RateController`): https://github.com/instaloader/instaloader ; doc_id deprecation: https://github.com/instaloader/instaloader/pull/2706
- instagram-private-api saved feed: https://github.com/dilame/instagram-private-api/blob/master/src/feeds/saved.feed.ts
- saved-post-analyzer (response interception on the saved page, shapes, DOM fallback, 429 halt): https://github.com/dipscoder/instagram-saved-post-analyzer
