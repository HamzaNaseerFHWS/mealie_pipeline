# 01: Walking skeleton: `mp doctor` checks the setup and talks to Mealie

**What to build:** The project skeleton and the first end-to-end path. The user runs `mp doctor` and sees, check by check, whether everything is in place:
- Python version
- ffmpeg on PATH
- `claude` CLI found and logged in with a subscription (`claude auth status` reports `authMethod: claude.ai`)
- Playwright's Chrome channel available
- yt-dlp version
- NVIDIA GPU visible (informational until ticket 07)
- Mealie reachable at `MEALIE_URL`, with its version
- the token valid (who it belongs to)
- Catalog counts (tags, foods, units)

It exits non-zero if a required check fails, with a one-line fix hint per failure (for example "Tailscale not connected?" or "run `claude` once and log in"). This ticket also introduces settings loading (`config/settings.yaml` + `.env`) and the `MealieGateway` port with its real HTTP implementation and in-memory fake, both passing one shared contract suite. That establishes the test conventions every later ticket follows: the adapter factory for injecting fakes, temp workspaces, and the fixture layout.

**Blocked by:** None (can start immediately)

**Never use** `POST /api/recipes/create/*` (incl. `create/html-or-json`) or `/api/parser/*`; see ADR 0001 *Considered Options*. Always PATCH, never PUT, on recipes.

**Status:** ready-for-agent

**Read first:** `spec.md` (Implementation Decisions: platform/tooling, workspace/config, Adapters → `MealieGateway`; Testing Decisions), wayfinder ticket `03-mealie-api-contract.md` (exact endpoints and rules), `scripts/check_mealie.py` (a stdlib prototype of the same checks; keep it working as a no-install fallback).

- [ ] `uv sync` then `uv run mp --help` works on a clean checkout. `pyproject.toml` declares Python 3.12, the `mp` entry point, and ruff/pyright/pytest config. `.env.example` lists `MEALIE_URL`, `MEALIE_TOKEN`, `OPENAI_API_KEY`, `OPENAI_MAX_USD` with comments. `config/settings.yaml` exists with documented defaults.
- [ ] `MealieGateway` exposes: about, whoami (incl. `group_slug`), catalog, create_food, create_unit, create_tag, find_recipe (by item key or org_url), create_recipe, patch_recipe, get_recipe, upload_image (file), set_image_from_url, delete_recipe, and `recipe_url(slug)` → `<MEALIE_URL>/g/<group_slug>/r/<slug>`.
- [ ] `upload_image` sends multipart with the file field `image` and the form field `extension` (`jpg`/`png`/`webp`), as `PUT /api/recipes/{slug}/image`. `set_image_from_url` sends `POST /api/recipes/{slug}/image {"url": …}`.
- [ ] Contract tests run the same scenarios against `FakeMealie` and against `MealieHttpGateway` pointed at a local `pytest-httpserver`. They assert the exact HTTP shapes: Bearer header, `perPage=-1` listing, `POST /api/recipes` returning a slug, PATCH payload keys in camelCase incl. `orgURL`, `queryFilter=org_url="…"`, multipart image upload.
- [ ] `FakeMealie` rejects a PATCH whose ingredient references an unknown food or unit id, the same way the real Mealie would (wayfinder 03), so later tickets can't accidentally rely on auto-creation.
- [ ] Every non-2xx response raises a typed error that carries the method, path, status and response body (truncated to 2 000 chars, token redacted).
- [ ] The real gateway uses timeouts and retries connection errors with backoff (max 3). A 401 produces a clear "token invalid" error. A DNS/connection failure produces "cannot reach Mealie at <url>: is Tailscale connected?".
- [ ] `mp doctor` is tested at the pipeline seam with fakes: all-green, Mealie unreachable, bad token, and `claude` missing. Each produces the expected lines and exit code.
- [ ] The token never appears in logs, errors or reports.
- [ ] **Opt-in live contract run:** the same contract suite runs against a real Mealie when `MEALIE_IT_URL` and `MEALIE_IT_TOKEN` are set (pytest marker `mealie_live`, skipped otherwise, never in CI). Every test makes its own uniquely named recipe/food/tag (`zz-it-<uuid>`) and deletes it afterwards, even on failure. It covers create + PATCH with parsed ingredients and tags, image upload by file and by URL, an `org_url` lookup, and tag creation. Intended targets are a throwaway Mealie container (`docker run -p 9925:9000 ghcr.io/mealie-recipes/mealie:<user's version>`) or, with care, the user's own instance.
- [ ] ruff, pyright and pytest all pass.

**Manual check on the laptop (user):** put the real values in `.env`, run `uv run mp doctor`, and paste the output into this ticket's Comments. Optional: run the live contract suite against a throwaway Mealie container of the same version as your instance.
