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

**Status:** done

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

## Comments

### Live findings from a hand-run smoke test against the real instance (2026-10-10)

Run from a Windows box over Tailscale with a user token, by hand (PowerShell), before this ticket is built. Evidence for the gateway and its contract suite; none of it changes the acceptance criteria above, but the live-run and `FakeMealie` behaviour should match it.

- **Instance version is v3.22.0** (`GET /api/app/about`), not v3.28.0. Wayfinder ticket 03 was written from v3.28.0 source. The calls below all worked on v3.22.0, but `doctor` should report the version and the live contract run should be done against a container of the user's version (v3.22.0), as the ticket already suggests.
- **Verified working on the real instance:** Bearer auth with `GET /api/users/self`; `POST /api/recipes {"name"}` returns the slug; `GET` the recipe, set fields on it, and `PATCH /api/recipes/{slug}` with the whole object back works; `orgURL`, `prepTime`, `performTime`, `recipeYield`, `description` persist.
- **Structured ingredients verified:** `recipeIngredient` items of `{quantity, unit:{id,name}, food:{id,name}, note, originalText, referenceId}` read back correctly (quantity, unit, food, note). Ingredients with no unit send `unit: null`; ingredients with no quantity (e.g. "salt, to taste") send `quantity: 0`.
- **`POST /api/units` rejects `abbreviation: null`** with 422 (`string_type`). `create_unit(name, abbreviation?)` must send `""` when there is no abbreviation. `FakeMealie` should reject null the same way, and the contract suite should cover creating a unit without an abbreviation.
- **Catalog names are not normalised.** The real catalog already had `Salt` (capital S) while the pipeline's name was `salt`. Lookups must be case-insensitive on name and plural name, and units should also match on abbreviation (`tbsp` = `tablespoon`). Exact-match lookup would have created duplicates. Unit Normalizer in ticket 09 depends on this.
- Spelling choice: the live catalog uses `okra` (the video called it "lady finger / bhindi"). The original name went into the ingredient `note`.
- **Side effects left on the live instance by the test:** recipe `chatpata-bhindi-aloo` (source: youtube.com/watch?v=de1ppj9L4Hk), foods `cumin seeds`, `green chilli`, `turmeric powder`, `Kashmiri red chilli powder`, `cumin powder`, `dry mango powder`, `kasuri methi`, `fresh coriander`, and unit `handful`. Ticket 22's existing-recipe count and `GET /api/foods/empty` will see these.
- Not tested: tags, images (file and URL), `org_url` queryFilter lookup, `DELETE`.

### Built (implementation session)

- **Skeleton:** `pyproject.toml` (Python 3.12, `mp` entry point, ruff/pyright/pytest config, `mealie_live` marker), `.env.example`, `config/settings.yaml`, `uv.lock`. `uv sync` then `uv run mp --help` works. Dependencies added now so `mp doctor` can check them: `yt-dlp`, `playwright`, `python-dotenv`. `pydantic-settings` was left out because settings are merged by hand (yaml, then `.env`, then environment), which is simpler to test.
- **Settings** (`settings.py`): `config/settings.yaml` < `.env` < environment. Nested keys use `__` (`MEALIE__TIMEOUT_SECONDS`). The token is a `SecretStr`, so it is hidden in `repr`/`str`.
- **`MealieGateway`** (`adapters/mealie.py`) with `MealieHttpGateway` (httpx, timeouts, up to 3 connection retries with 1/2/4 s backoff, 401 → "token invalid", connection failure → "cannot reach Mealie at <url>: is Tailscale connected?") and `FakeMealie`. Typed errors in `errors.py` carry method, path, status and the body (redacted of the token, cut to 2 000 chars).
- **`FakeMealie` enforces the live rules:** a PATCH with an unknown food or unit id fails, a `null` unit abbreviation is rejected (`create_unit` sends `""`), slugs are generated, tokens are checked.
- **Test conventions for later tickets:** `tests/conftest.py` has the parametrised `gateway` fixture (fake / http / live). `tests/mealie_server.py` is a local HTTP stand-in for Mealie backed by `FakeMealie`; it records requests so tests can assert exact shapes. `Adapters(mealie=…, system=…)` is the injection bundle: the CLI uses the click context object when it is an `Adapters`, otherwise `build_adapters(settings)`. CLI tests use `CliRunner().invoke(app, ["--workspace", tmp, "doctor"], obj=Adapters(...))` with a `.env` in a temp workspace.
- **`mp doctor`:** Python, ffmpeg, `claude` (must report `authMethod: claude.ai`), Playwright Chrome, yt-dlp, NVIDIA GPU (warning only), Mealie reachability + version, token owner, catalog counts. Exits 1 on a required failure, with a `fix:` line per failure. Tests cover all green, Mealie unreachable, bad token, `claude` missing, API-key login, no GPU, missing ffmpeg, old Python, missing settings.
- **Live contract run:** the same contract tests run with `-m mealie_live` when `MEALIE_IT_URL` and `MEALIE_IT_TOKEN` are set, using `zz-it-…` names and cleaning up catalog entries afterwards. Run: `MEALIE_IT_URL=… MEALIE_IT_TOKEN=… uv run pytest -m mealie_live`.
- ruff, ruff format, pyright and pytest all pass (65 tests, 18 live tests deselected).

### Deferred / notes

- **`find_recipe(item_key=…)` is unverified against real Mealie.** It uses `queryFilter=extras.key="item_key" AND extras.value="…"`. The `org_url` filter is documented; the extras one is my assumption about Mealie's relationship filtering. The live contract test `test_find_recipe_by_item_key` will show whether it works. If not, the fallback is the State Store slug plus `org_url` (ticket 22 already relies on `org_url`).
- `image_from_url` and the multipart upload are only verified against the local stand-in until the live run.
- `ruff` excludes `scripts/`, `mealie_test.py` and `PIPELINE_SPEC.md` so those pre-existing files stay as they are.
- The `code-review` skill was not run (it spawns sub-agents); a self-review was done instead.

### Manual verification (user, on the laptop)

1. `uv sync`, copy `.env.example` to `.env`, fill in `MEALIE_URL` and `MEALIE_TOKEN`.
2. `uv run mp doctor`, and paste the output here. Expect all `[ OK ]` (the GPU line is a warning only if no NVIDIA GPU is seen).
3. Optional: `docker run -p 9925:9000 ghcr.io/mealie-recipes/mealie:v3.22.0`, create a user and token, then `MEALIE_IT_URL=http://localhost:9925 MEALIE_IT_TOKEN=… uv run pytest -m mealie_live`.
