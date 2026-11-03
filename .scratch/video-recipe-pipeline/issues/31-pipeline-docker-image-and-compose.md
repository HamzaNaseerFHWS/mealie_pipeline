# 31: Docker image and compose file for the pipeline and the inbox bot

**What to build:** A new, separate Docker Compose project (`deploy/compose.yml`) for the Mealie PC with two services: `inbox` (the Telegram bot in `inbox_bot/`) and `pipeline` (the worker from ticket 33). The existing Mealie compose project is **not touched**: the pipeline reaches Mealie only through its REST API and token.

- `deploy/Dockerfile.pipeline`: Python 3.12, `uv`, `ffmpeg`, `yt-dlp`, the Claude Code CLI (`claude`), NLTK data (what `.tools/` holds on the laptop). No GPU in this ticket (see ticket 34).
- Volumes: `inbox-data` (`inbox.db`), `pipeline-data` (`pipeline.db`, `work/`, `reports/`, `logs/`), `claude-login` (the CLI's login, see ticket 32), and a bind mount `./imports` for the Instagram/Facebook exports.
- `pipeline` reaches `inbox` by its service name; the bot's port is not published (or only on the Tailscale address).
- `pipeline` reaches Mealie through a setting (`MEALIE__URL`), by default `http://host.docker.internal:9000` (add `extra_hosts: host.docker.internal:host-gateway` on Linux). Nothing in the code changes.
- Secrets (`TELEGRAM_BOT_TOKEN`, `INBOX_API_TOKEN`, `TELEGRAM_CHAT_ID` with comma-separated ids, `MEALIE__TOKEN`) come from a git-ignored `deploy/.env`; ship a `deploy/.env.example` with empty values.

**Blocked by:** None for the build; ticket 32 decides whether `claude` works in the container, and ticket 33 supplies the worker command.

**Status:** done

**Read first:** `inbox_bot/README.md`, `inbox_bot/docker-compose.yml`, `inbox_bot/Dockerfile`, `.gitignore`, `src/mealie_pipeline/settings.py`.

- [x] `docker compose -f deploy/compose.yml config` validates; the image builds on a Linux host. (config: yes; build: not possible in the cloud sandbox, see Comments)
- [ ] (laptop) Inside the image: `mp --help`, `yt-dlp --version`, `ffmpeg -version` and `claude --version` all run.
- [x] `uv run pytest` passes on Linux (the suite must not depend on Windows paths).
- [x] No secret is in the image or the repo; `deploy/.env` is ignored.
- [x] `deploy/README.md`: start, stop, update, where the data lives, how to back up `pipeline-data`.

**Manual check on the Mealie PC (user):** `docker compose -f deploy/compose.yml up -d --build`, then `docker compose exec pipeline mp doctor` reports Mealie reachable.

## Comments

**Built**
- `deploy/compose.yml`: project `recipe-pipeline`, services `inbox` and `pipeline`. Mealie's compose project is not touched.
  - `inbox` is built from `../inbox_bot` and gets only its own variables. Its port is not published (a commented `ports:` line shows how to bind it to the Tailscale address). It has a healthcheck on `/health`.
  - `pipeline` starts once `inbox` is healthy. It runs `mp inbox-worker` with:
    - `INBOX_URL=http://inbox:8765`;
    - `MEALIE_URL` defaulting to `http://host.docker.internal:9000` (`extra_hosts: host-gateway`); `deploy/.env` overrides it;
    - `WEB__BROWSER_HEADLESS=true`;
    - `stop_grace_period: 10m`, so SIGTERM lets the item in progress finish.
  - Volumes: `inbox-data`, `pipeline-data` (the workspace `/workspace`), `claude-login` (`/home/mp/.claude`). Bind mounts: `./imports` and `./secrets` (`cookies.txt`).
- `deploy/Dockerfile.pipeline`:
  - `python:3.12-slim-bookworm`; ffmpeg, tini and curl from apt; `uv` 0.11.32 from PyPI; `uv sync --frozen --no-dev`.
  - The NLTK tagger, checked at build time.
  - Google Chrome via `playwright install --with-deps chrome` (build arg `WITH_CHROME`, default true).
  - The Claude Code CLI via the native installer (build arg `CLAUDE_VERSION=stable`), with `CLAUDE_CONFIG_DIR` set to the login volume and the auto-updater off.
  - Runs as uid 1000. No secrets in the image.
- `deploy/entrypoint.sh` creates the workspace folders and links `config/` and `prompts/` from the image. A mounted `config/` is left alone.
- `deploy/.env.example` (empty values); `deploy/README.md` covers start, stop, update, data locations, backup and restore, Claude login, cookies, and testing on the laptop.
- `.dockerignore` keeps `.env`, secrets, cookies, data, exports and tests out of the build context. `.gitignore` adds `deploy/.env` and `deploy/imports/*`; `secrets/` was already ignored everywhere.
- Code: `web.browser_headless` (the container has no screen). `YtDlpVideoSource` sends `secrets/cookies.txt` while it exists (ticket 33). `mp doctor` accepts `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) as a subscription login, and fails when `ANTHROPIC_API_KEY` is set.
- `tests/test_deploy_files.py` checks the compose, ignore and env-example files without Docker. The whole suite passes on Linux.

**What I could verify in the cloud session:**
- `docker compose -f deploy/compose.yml config` validates.
- `uv sync --frozen --no-dev` and `mp --help` work in a fresh environment, and yt-dlp 2026.10.21 imports.

**What I could not verify:** the image build. The sandbox's network policy refuses the Debian package mirrors (apt: 403 from the proxy) and GitHub's container registry, and Docker Hub rate-limited the base image. NLTK also refuses to download through the sandbox proxy. None of this applies on your network, but the build has not run end to end yet.

**Manual check (user):**
1. On the laptop first (Docker Desktop), per `deploy/README.md` "Testing on the laptop":

   ```
   docker compose -f deploy/compose.yml up -d --build
   ```

   ```
   docker compose -f deploy/compose.yml exec pipeline sh -c "mp --help && yt-dlp --version && ffmpeg -version | head -1 && claude --version"
   ```

   ```
   docker compose -f deploy/compose.yml exec pipeline mp doctor
   ```

2. Then on the Mealie PC: `docker compose -f deploy/compose.yml up -d --build`. Then `docker compose exec pipeline mp doctor` should report Mealie reachable.
