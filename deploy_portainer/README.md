# Running the pipeline as a Portainer stack

For the Mealie PC when you manage Docker through Portainer. The images are prebuilt by GitHub Actions
(`.github/workflows/build-images.yml`) and pulled from GHCR, so nothing is built and no source is needed.
The command-line route (compose + `.env`) is in [../deploy/README.md](../deploy/README.md).

`compose.yml` here differs from `deploy/compose.yml`: no `build:`, no `env_file`, no `./folders`. Secrets
come from Portainer's environment variables, and `imports` / `secrets` are named volumes.

## 1. Let Portainer pull from GHCR

1. GitHub: Settings, Developer settings, Personal access tokens, **Tokens (classic)**
   (https://github.com/settings/tokens/new). Tick only `read:packages` (or `write:packages`, which includes it).
2. Check the two packages (`mealie_pipeline-pipeline`, `mealie_pipeline-inbox`) exist under the repo's
   Packages and are private. If the Actions run hasn't passed yet, they don't exist.
3. Portainer: Registries, Add registry, **Custom registry**. URL `ghcr.io`, turn on authentication, enter your
   GitHub username and the token.

## 2. Create the stack

Stacks, Add stack, Web editor, paste [compose.yml](compose.yml). Under **Environment variables** add:

| Variable | Value |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | from @BotFather |
| `TELEGRAM_CHAT_ID` | your chat id(s), comma-separated |
| `INBOX_API_TOKEN` | long random string shared by the bot and the pipeline |
| `MEALIE_TOKEN` | Mealie, Profile, API Tokens |
| `CLAUDE_CODE_OAUTH_TOKEN` | from `claude setup-token`; leave empty to log in inside the container (step 3) |
| `MEALIE_URL` | leave unset: defaults to `http://host.docker.internal:9000` (Mealie published on port 9000 on this PC) |

Deploy the stack. Stop the stack on the laptop first: only one process may poll the Telegram token.

## 3. Claude login (only if `CLAUDE_CODE_OAUTH_TOKEN` is empty)

Portainer, Containers, `recipe-pipeline-pipeline-1`, Console, Connect (command `/bin/bash`). Run `claude`,
then `/login`, and finish in a browser. The login is kept in the `claude-login` volume and survives restarts
and image updates.

## 4. Check

In the same console run `mp doctor`. It should show Claude logged in with a subscription and Mealie reachable.
Then send a link to the Telegram bot.

## Updating

Stacks, the stack, **Update the stack**, turn on "Re-pull image", Update. To go back to an older build, change
the image tags in the editor from `:latest` to a commit tag (every build is also tagged `:<commit>`).

## Instagram / Facebook exports

Copy the export into the `imports` volume, for example
`docker cp export.zip recipe-pipeline-pipeline-1:/workspace/imports/`. Cookies for private lists go in the
`secrets` volume the same way.
