# Running the pipeline in Docker

This is a separate Docker Compose project (`recipe-pipeline`) with two services:

- **`inbox`**: the Telegram inbox bot (`inbox_bot/`). It queues the links you share to it.
- **`pipeline`**: `mp inbox-worker`. It takes those links through the pipeline into Mealie and tells the bot how each one went.

Mealie's own compose project is not touched. The pipeline reaches Mealie only through its REST API and token.

All commands below run from the repository root.

## First start

1. Create the folders the compose file mounts, and the settings file:

   ```
   mkdir -p deploy/secrets deploy/imports
   cp deploy/.env.example deploy/.env
   ```

   Fill in `deploy/.env`. It is git-ignored and never goes into the image:
   - `TELEGRAM_BOT_TOKEN`
   - `INBOX_API_TOKEN` (any long random string)
   - `MEALIE_TOKEN`
   - on the laptop only, `MEALIE_URL` (see [Testing on the laptop](#testing-on-the-laptop)).

2. Choose how Claude logs in: [Claude login](#claude-login), option A or B.
3. Optional: put `cookies.txt` in `deploy/secrets/` for Instagram and Facebook links that need a login (see [Instagram and Facebook cookies](#instagram-and-facebook-cookies)).
4. Build and start:

   ```
   docker compose -f deploy/compose.yml up -d --build
   ```

5. Check it:

   ```
   docker compose -f deploy/compose.yml exec pipeline mp doctor
   ```

   "Mealie reachable" and "claude CLI" must be OK. "Playwright Chrome" is OK unless you built with `WITH_CHROME=false`. The "session" lines are warnings until `secrets/cookies.txt` exists.

6. The first time, message the bot in Telegram: it replies with your chat id. Put the id in `TELEGRAM_CHAT_ID` in `deploy/.env` (comma-separated for two people), then `docker compose -f deploy/compose.yml up -d` again.

## Everyday use

| What | Command |
|---|---|
| Start | `docker compose -f deploy/compose.yml up -d` |
| Stop | `docker compose -f deploy/compose.yml stop` (the worker finishes the item in progress, up to 10 min) |
| Logs | `docker compose -f deploy/compose.yml logs -f pipeline` (or `inbox`) |
| Update after `git pull` | `docker compose -f deploy/compose.yml up -d --build` |
| One cycle by hand | `docker compose -f deploy/compose.yml exec pipeline mp inbox-worker --once` |
| Status / report | `docker compose -f deploy/compose.yml exec pipeline mp status` (and `mp report`) |
| Any `mp` command | `docker compose -f deploy/compose.yml exec pipeline mp <command>` |

Build without Google Chrome (about 350 MB smaller) by setting `WITH_CHROME=false` in `deploy/.env` and rebuilding. Pages that need JavaScript (link-in-bio lists, blocked pages) are then reported instead of read. Chrome is only available for x86-64 machines.

## Where the data lives

| Volume / folder | Mounted at | Holds |
|---|---|---|
| `pipeline-data` (volume) | `/workspace` | `pipeline.db`, `data/` (web pages, subtitles, inbox state), `work/`, `reports/`, `logs/` |
| `inbox-data` (volume) | `/data` in `inbox` | `inbox.db`, the bot's queue |
| `claude-login` (volume) | `/home/mp/.claude` | the Claude Code login and settings (option B) |
| `deploy/imports/` (folder) | `/workspace/imports` | Instagram/Facebook data exports for `mp import-instagram` / `mp import-facebook` |
| `deploy/secrets/` (folder) | `/workspace/secrets` | `cookies.txt` for yt-dlp; git-ignored |

`config/` and `prompts/` come from the image, so an update brings the new ones. To change them, mount your own folder over `/workspace/config`.

Volumes survive `down`, `up`, and image rebuilds. Only `docker compose down -v` deletes them, so don't use `-v`.

### Backing up `pipeline-data`

```
docker compose -f deploy/compose.yml stop pipeline
```

```
docker run --rm -v recipe-pipeline_pipeline-data:/workspace -v "$PWD":/backup busybox tar czf /backup/pipeline-data-$(date +%F).tgz -C /workspace .
```

```
docker compose -f deploy/compose.yml start pipeline
```

To restore, run the same `docker run` with `tar xzf /backup/<file>.tgz -C /workspace` against an empty volume. Back up `inbox-data` the same way (`recipe-pipeline_inbox-data`, mounted at `/data`).

## Claude login

The pipeline calls `claude -p` on your **Claude Pro subscription**. It never uses an API key or `--bare`. `mp doctor` fails if `ANTHROPIC_API_KEY` is set in the container. There are two ways in. Try A first; B is the fallback (ticket 32 records which one works).

**Option A: subscription token.** Run this once, on the laptop (or in the container):

```
claude setup-token
```

It opens the browser, you log in with your Claude Pro account, and it prints a long-lived token. Put it in `deploy/.env` as `CLAUDE_CODE_OAUTH_TOKEN=...` and run `docker compose -f deploy/compose.yml up -d`. Nothing is stored in a volume, and rebuilds don't touch it. When the token expires or is revoked, make a new one the same way.

**Option B: log in inside the container.** Leave `CLAUDE_CODE_OAUTH_TOKEN` empty, then:

```
docker compose -f deploy/compose.yml run --rm pipeline claude
```

Inside Claude Code, type `/login` and choose your Claude subscription. Open the link it shows on any device, log in, paste the code back, then `/exit`. The login is stored in the `claude-login` volume (`CLAUDE_CONFIG_DIR=/home/mp/.claude`), so it survives restarts and rebuilds.

**Check either one, also after a full restart:**

```
docker compose -f deploy/compose.yml run --rm pipeline claude -p "say ok"
```

When the login expires, `claude -p` fails. Extraction then fails for the links on their way, and the bot replies "failed" with the reason; `mp retry` runs them again. Do option A or B again to fix it.

## Instagram and Facebook cookies

The container has no Chrome login window (`mp login` needs one). Export the cookies on the laptop instead: `mp login instagram` (and `facebook`) writes `secrets/cookies.txt`. Copy that file to `deploy/secrets/cookies.txt` on the PC. yt-dlp sends it with every request while the file exists. When it expires, Instagram links fail with "login needed (refresh secrets/cookies.txt)": log in on the laptop again and copy the new file over.

On Linux the container runs as uid 1000, so make the folders writable for it:

```
sudo chown -R 1000:1000 deploy/secrets deploy/imports
```

## Testing on the laptop

The same compose file works on Docker Desktop for Windows. Two differences:

- Mealie is on the other PC. Set `MEALIE_URL` in `deploy/.env` to its Tailscale address: `http://mealie.taildce5a6.ts.net:9000`. If the container cannot resolve that name, use the PC's Tailscale IP (`tailscale ip -4` on the Mealie PC), for example `http://100.x.y.z:9000`.
- Run only one bot per Telegram token. Stop the bot on the Mealie PC while you test the laptop's, or use a second test bot from @BotFather.

Then:

```
docker compose -f deploy/compose.yml up -d --build
```

```
docker compose -f deploy/compose.yml exec pipeline mp doctor
```

Send the bot a recipe link: it should reply with the Mealie link within a few minutes.
