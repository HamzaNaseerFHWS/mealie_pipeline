# 33: Worker: take links from the Telegram inbox through the pipeline and report back

**What to build:** `mp inbox-worker` (a loop, run by the `pipeline` container): every N seconds it asks the bot for pending links, runs each one through the pipeline, then tells the bot how it went.

1. `GET <INBOX_URL>/pending` with `Authorization: Bearer <INBOX_API_TOKEN>` (settings `inbox.url`, `inbox.token`).
2. Each URL goes through the URL Normalizer. A YouTube/Instagram/Facebook video becomes a Video in a Saved List `inbox:telegram`; a recipe-website link becomes a Recipe Request (ticket 26 path).
3. Run all stages up to and including upload for those Videos only (`only_videos`).
4. `POST /items/<id>/result` with `{"status": "done"|"not_recipe"|"failed", "mealie_urls": [...], "note": "..."}`: `done` with the Mealie link(s) (several for a multi-recipe video), `not_recipe` when classify says so (the label as note), `failed` with a short reason (for example "download failed"); a video with no usable text is `done` with the link-only stub's Mealie link.
5. Unreachable bot or Mealie: wait and retry; never lose an item. An item already posted is not posted twice.

The bot already accepts several chats (comma-separated `TELEGRAM_CHAT_ID`); each person gets the reply for their own link. A link queued twice by two people is one item: only the first sender gets the reply (known limit, note it in the README).

**Blocked by:** None for the code (the bot's API is built); 31 to run it in Docker.

**Status:** done

**Read first:** `inbox_bot/README.md` (API table), `inbox_bot/bot.py`, `src/mealie_pipeline/pipeline.py` (`run`, `only_videos`), `src/mealie_pipeline/recipe_requests.py`, `url_normalizer.py`.

- [x] Pipeline-seam test with the fakes and a local fake of the bot API: a YouTube link ends as `done` with the Mealie URL; a non-recipe link as `not_recipe`; a failure as `failed` with a reason; a down bot loses nothing; a result is never posted twice.
- [x] A multi-recipe video returns all its Mealie URLs.
- [x] The loop stops cleanly on SIGTERM (container stop) and resumes at the next start.
- [x] README: the settings and the known limit above.

**Manual check (user):** send the bot a recipe link in Telegram; within a few minutes the bot replies with the Mealie link.

## Comments

**Built** (`inbox_worker.py`, `mp inbox-worker [--once]`):
- `HttpInboxClient` calls the bot's API (`GET /pending`, `POST /items/<id>/result`) with the bearer token.
- Settings: `inbox.url` / `inbox.token` come from the secrets `INBOX_URL` / `INBOX_API_TOKEN`. `inbox.poll_seconds` defaults to 60 and `inbox.list_key` to `inbox:telegram`.
- Each new link is first saved to `data/inbox_items.json` (atomic write), then registered:
  - a YouTube/Instagram/Facebook link goes through `resolve` (which follows fb.watch and share links) and becomes a Video in the Saved List `inbox:telegram`;
  - any other http(s) link becomes a `web` recipe-page item, the same item a found Recipe Request makes (the page is the only Source). It skips `find`, because the page is already given;
  - anything else is reported `failed` straight away.
- The pipeline then runs all stages for the open items only (`only_videos`).
- Outcomes:
  - `done` with every part's Mealie link: uploaded, already in Mealie, a link-only stub, or a dedupe duplicate (resolved through its canonical Video);
  - `not_recipe` with the label as note;
  - `failed` with a short reason (≤300 chars): download failed, or a stage that failed or held the item for review.
- An item still on its way (Mealie down, usage limit) is reported on a later cycle.
- If the bot is unreachable, the worker waits. A result is marked posted only after the bot accepted it, so nothing is posted twice, also across restarts.
- SIGTERM and SIGINT stop the loop: the item in progress finishes, and the wait between cycles ends at once.
- `YtDlpVideoSource` now sends `secrets/cookies.txt` with every request (metadata, subtitles, frames, comments) whenever the file exists. Instagram/Facebook links that need a login then work in the container. A login error reads "login needed (refresh secrets/cookies.txt)".
- `inbox_bot/README.md` has the settings, the result table and the known limit (two senders, one item, one reply).

**Tests:** `tests/test_inbox_worker.py`, against the real bot API on a local port and a fake inbox that can go down.

**Manual check (user):** with the compose project running (ticket 31), send the bot a recipe link in Telegram. Within a few minutes it replies with the Mealie link. Watch it work with `docker compose -f deploy/compose.yml logs -f pipeline`.
