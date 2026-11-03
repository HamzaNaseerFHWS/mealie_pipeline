# 31: Docker image and compose file for the pipeline and the inbox bot

**What to build:** A new, separate Docker Compose project (`deploy/compose.yml`) for the Mealie PC with two services: `inbox` (the Telegram bot in `inbox_bot/`) and `pipeline` (the worker from ticket 33). The existing Mealie compose project is **not touched**: the pipeline reaches Mealie only through its REST API and token.

- `deploy/Dockerfile.pipeline`: Python 3.12, `uv`, `ffmpeg`, `yt-dlp`, the Claude Code CLI (`claude`), NLTK data (what `.tools/` holds on the laptop). No GPU in this ticket (see ticket 34).
- Volumes: `inbox-data` (`inbox.db`), `pipeline-data` (`pipeline.db`, `work/`, `reports/`, `logs/`), `claude-login` (the CLI's login, see ticket 32), and a bind mount `./imports` for the Instagram/Facebook exports.
- `pipeline` reaches `inbox` by its service name; the bot's port is not published (or only on the Tailscale address).
- `pipeline` reaches Mealie through a setting (`MEALIE__URL`), by default `http://host.docker.internal:9000` (add `extra_hosts: host.docker.internal:host-gateway` on Linux). Nothing in the code changes.
- Secrets (`TELEGRAM_BOT_TOKEN`, `INBOX_API_TOKEN`, `TELEGRAM_CHAT_ID` with comma-separated ids, `MEALIE__TOKEN`) come from a git-ignored `deploy/.env`; ship a `deploy/.env.example` with empty values.

**Blocked by:** None for the build; ticket 32 decides whether `claude` works in the container, and ticket 33 supplies the worker command.

**Status:** in-progress

**Read first:** `inbox_bot/README.md`, `inbox_bot/docker-compose.yml`, `inbox_bot/Dockerfile`, `.gitignore`, `src/mealie_pipeline/settings.py`.

- [ ] `docker compose -f deploy/compose.yml config` validates; the image builds on a Linux host.
- [ ] Inside the image: `mp --help`, `yt-dlp --version`, `ffmpeg -version` and `claude --version` all run.
- [ ] `uv run pytest` passes on Linux (the suite must not depend on Windows paths).
- [ ] No secret is in the image or the repo; `deploy/.env` is ignored.
- [ ] `deploy/README.md`: start, stop, update, where the data lives, how to back up `pipeline-data`.

**Manual check on the Mealie PC (user):** `docker compose -f deploy/compose.yml up -d --build`, then `docker compose exec pipeline mp doctor` reports Mealie reachable.
