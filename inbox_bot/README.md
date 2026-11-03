# Recipe inbox bot

A Telegram bot for the Mealie PC. Share a recipe link to it from any app. It queues the link and replies
"Saved ✅". The laptop collects queued links over Tailscale, runs them through the pipeline and reports back,
and the bot then replies with the Mealie link (or "not a recipe").

Standard library only. The whole bot is [bot.py](bot.py).

## Run it on the Mealie PC

1. Copy this folder to the Mealie PC.
2. `cp .env.example .env` and fill in `TELEGRAM_BOT_TOKEN` and `INBOX_API_TOKEN`. Leave `TELEGRAM_CHAT_ID` empty.
3. `docker compose up -d --build`
4. Send the bot any message. It replies with your chat ID. Put it in `.env` as `TELEGRAM_CHAT_ID`. For two people, have your partner message the bot too, then list both IDs separated by a comma: `TELEGRAM_CHAT_ID=111111111,222222222`. Each person gets the replies for their own links.
5. `docker compose up -d` again (restarts with the new env). From now on the bot only listens to you.

Check it: `docker compose logs -f`, and from the laptop `curl http://<mealie-pc>:8765/health`.

The queue lives in `./data/inbox.db`, so it survives restarts and rebuilds.

## Bot commands

- Any message with links: queues every link in it.
- `/queue`: lists links still waiting for the laptop.

## HTTP API (for the laptop)

All routes except `/health` need `Authorization: Bearer <INBOX_API_TOKEN>`.

| Route | Purpose |
|---|---|
| `GET /health` | `{"ok": true}` |
| `GET /pending` | `{"items": [{"id", "url", "received_at"}]}` |
| `POST /items/<id>/result` | Body `{"status": "done" \| "not_recipe" \| "failed", "mealie_urls": [...], "note": "..."}`. Marks the item finished and replies on Telegram. |

Port 8765 is published on all of the PC's interfaces. The token protects it. To make it reachable over
Tailscale only, change the port line in `docker-compose.yml` to `"<tailscale-ip>:8765:8765"`.

## The pipeline side: `mp inbox-worker`

The `pipeline` container of `deploy/compose.yml` (or the laptop) runs `mp inbox-worker`. Every
`inbox.poll_seconds` (default 60) it asks `GET /pending`, runs each new link through the pipeline and
posts the result:

| Result | When |
|---|---|
| `done` + Mealie link(s) | uploaded, already in Mealie, or a link-only stub; a multi-recipe video lists every recipe |
| `not_recipe` + label | `classify` skipped it (`restaurant_or_place`, `not_food`, ...) |
| `failed` + reason | download failed, the page held no single recipe, or held for review in the pipeline |

A YouTube/Instagram/Facebook link becomes a Video of the Saved List `inbox:telegram`. Any other web
link is read as a recipe page. A link stays "on its way" while Mealie is down or Claude's usage limit
is hit, and is reported once it is through. Taken links are remembered in `data/inbox_items.json`, so a
restart or an unreachable bot loses nothing, and a result is never posted twice.

Settings (in `deploy/.env` or the pipeline's `.env`):

| Variable | Meaning |
|---|---|
| `INBOX_URL` | the bot's API, e.g. `http://inbox:8765` inside the compose project |
| `INBOX_API_TOKEN` | the same token the bot uses |
| `INBOX__POLL_SECONDS` | seconds between two looks at the queue (default 60) |

`mp inbox-worker --once` runs one cycle and exits. SIGTERM (`docker compose stop`) or Ctrl+C lets the
item in progress finish, then stops.

**Known limit:** the queue keeps one item per link. If two people send the same link, only the first
sender gets the reply.
