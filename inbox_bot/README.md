# Recipe inbox bot

A Telegram bot for the Mealie PC. Share a recipe link to it from any app. It queues the link and replies
"Saved ✅". The laptop collects queued links over Tailscale, runs them through the pipeline and reports back,
and the bot then replies with the Mealie link (or "not a recipe").

Standard library only. The whole bot is [bot.py](bot.py).

## Run it on the Mealie PC

1. Copy this folder to the Mealie PC.
2. `cp .env.example .env` and fill in `TELEGRAM_BOT_TOKEN` and `INBOX_API_TOKEN`. Leave `TELEGRAM_CHAT_ID` empty.
3. `docker compose up -d --build`
4. Send the bot any message. It replies with your chat ID. Put it in `.env` as `TELEGRAM_CHAT_ID`.
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
