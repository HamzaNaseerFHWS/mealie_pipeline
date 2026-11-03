# 33: Worker: take links from the Telegram inbox through the pipeline and report back

**What to build:** `mp inbox-worker` (a loop, run by the `pipeline` container): every N seconds it asks the bot for pending links, runs each one through the pipeline, then tells the bot how it went.

1. `GET <INBOX_URL>/pending` with `Authorization: Bearer <INBOX_API_TOKEN>` (settings `inbox.url`, `inbox.token`).
2. Each URL goes through the URL Normalizer. A YouTube/Instagram/Facebook video becomes a Video in a Saved List `inbox:telegram`; a recipe-website link becomes a Recipe Request (ticket 26 path).
3. Run all stages up to and including upload for those Videos only (`only_videos`).
4. `POST /items/<id>/result` with `{"status": "done"|"not_recipe"|"failed", "mealie_urls": [...], "note": "..."}`: `done` with the Mealie link(s) (several for a multi-recipe video), `not_recipe` when classify says so (the label as note), `failed` with a short reason (for example "needs transcription").
5. Unreachable bot or Mealie: wait and retry; never lose an item. An item already posted is not posted twice.

The bot already accepts several chats (comma-separated `TELEGRAM_CHAT_ID`); each person gets the reply for their own link. A link queued twice by two people is one item: only the first sender gets the reply (known limit, note it in the README).

**Blocked by:** None for the code (the bot's API is built); 31 to run it in Docker.

**Status:** ready-for-agent

**Read first:** `inbox_bot/README.md` (API table), `inbox_bot/bot.py`, `src/mealie_pipeline/pipeline.py` (`run`, `only_videos`), `src/mealie_pipeline/recipe_requests.py`, `url_normalizer.py`.

- [ ] Pipeline-seam test with the fakes and a local fake of the bot API: a YouTube link ends as `done` with the Mealie URL; a non-recipe link as `not_recipe`; a failure as `failed` with a reason; a down bot loses nothing; a result is never posted twice.
- [ ] A multi-recipe video returns all its Mealie URLs.
- [ ] The loop stops cleanly on SIGTERM (container stop) and resumes at the next start.
- [ ] README: the settings and the known limit above.

**Manual check (user):** send the bot a recipe link in Telegram; within a few minutes the bot replies with the Mealie link.
