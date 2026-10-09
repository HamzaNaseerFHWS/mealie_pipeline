# 02: Tracer bullet: import one YouTube Video whose description holds the recipe

**What to build:** The thinnest complete path from a Video URL to a parsed, tagged recipe in Mealie.

1. `mp add <youtube url>` registers the Video in a new State Store (SQLite in the workspace) under its Video Key.
2. `mp run` takes it through: `metadata` (yt-dlp, no download), then `extract` (one LLM call through `ClaudeCliBackend` using the description as the only Source, returning an `ExtractedRecipe` with Evidence and English Ingredient Lines), then `parse` (engine A only, `ingredient-parser-nlp`, plus Unit Normalizer, Food Matcher and creating missing English Foods/Units), then `tag` (the LLM's choices restricted to existing tags; at least one, else fail the item), then `upload` (payload builder, create + PATCH, thumbnail image, read-back comparison).
3. Running `mp run` again changes nothing (idempotent by Item Key `youtube:<id>#1`).

The full Gate, the second parse engine, rule tags, multi-recipe and languages come in later tickets. Keep their seams in mind but don't build them.

**Blocked by:** 01

**Status:** ready-for-agent

**Read first:** `spec.md` modules 1, 2, 3 (`LLMBackend`, `VideoSource`), 9, 10, 13; `PIPELINE_SPEC.md` §2b "AI backend" for the exact `claude -p` flags; `docs/adr/0002`, `0003`.

- [ ] The State Store holds Videos, Recipe Parts and Stage Records with versioned migrations. Its public queries are what tests assert on.
- [ ] `LLMBackend` port with `ClaudeCliBackend` and `FakeLLM`:
  - The backend builds the `claude -p` argument list exactly as specified: `--safe-mode`, `--tools ""`, `--output-format json`, `--json-schema`, `--no-session-persistence`, `--system-prompt-file`, `--model` from the tier. It never passes `--bare`.
  - The prompt goes on UTF-8 stdin, and the JSON Schema is generated from the pydantic model.
  - It parses `structured_output` and raises `LLMError` on `is_error` or a non-zero exit.
  - It is contract-tested against a stub `claude` executable placed first on PATH that replays recorded JSON (success and error cases).
- [ ] The extraction prompt (`prompts/extract.md`) states the rules: never invent quantities (use "to taste" + `quantity_stated=false`), one ingredient per line, English Ingredient Lines with `original_line` kept, Sections preserved, verbatim Evidence quotes, and tag choices only from the provided enum.
- [ ] The Food Matcher and Unit Normalizer are pure and table-tested: exact, plural, alias, singularized, fuzzy ≥ 92, new. Creating Foods/Units is serialised and logged to `reports/created_foods.csv` / `created_units.csv`.
- [ ] The payload builder is pure and tested:
  - ISO-8601 durations, Section `title` on the first ingredient of each Section, a fresh `referenceId` per ingredient
  - `orgURL` = canonical Video URL
  - `extras` = `{item_key, video_key, part: 1, of: 1, platform, pipeline_version}`
- [ ] **Recipe image** (the pipeline fetches it itself; Mealie never scrapes the Video page):
  - **YouTube:** download `https://i.ytimg.com/vi/<id>/maxresdefault.jpg`, falling back to `hqdefault.jpg` on 404 or the tiny placeholder image (≤ 120 px wide).
  - **Other platforms:** the `thumbnail` from yt-dlp metadata.
  - **Order of attempts:** upload the local file with `upload_image`. If that fails, try `set_image_from_url` with the thumbnail URL. If that fails too, the recipe **stays uploaded**: the item is marked `image_missing` in the report (a warning, not a failure) and the run continues.
  - **Tests:** the pure fallback logic is table-tested, and a pipeline-seam test covers "file upload fails, URL works" and "both fail, recipe still present".
- [ ] The upload stage records the Mealie slug and the recipe link (`recipe_url(slug)`) in the State Store, and prints the link.
- [ ] Upload reads the recipe back and fails the item (Stage Record `failed`, reason recorded) if the ingredient count, any food id, or the tags differ from what was sent.
- [ ] Pipeline-seam test: a fake `VideoSource` returns an `info.json` fixture whose description holds a full recipe, `FakeLLM` returns a recorded extraction, and `FakeMealie` starts with tags and some foods. After `mp add` + `mp run`, `FakeMealie` holds exactly one recipe with all ingredients linked to food ids, ≥ 1 existing tag and the thumbnail. A second `mp run` makes no new writes.
- [ ] `--dry-run` writes the payload JSON under `work/` and makes no Mealie writes.

**Manual check on the laptop (user):** `uv run mp add <a YouTube recipe video with ingredients in its description>` then `uv run mp run`. Open the recipe in Mealie and confirm the ingredients show amount, unit and food, and that it has a tag. Paste the Mealie link into Comments.

## Comments

### Live evidence for the Food Matcher / Unit Normalizer (hand-run, 2026-10-10, Mealie v3.22.0)

A hand-built structured ingredient list was written to the real instance (recipe `chatpata-bhindi-aloo`, 18 lines) by looking each unit and food up in the existing Catalog first and creating only what was missing. It confirms the order this ticket already specifies, and sharpens a few points:

- **Reuse first, create last.** Each line resolved against the fetched Catalog (`perPage=-1`); `POST /api/foods` / `POST /api/units` was called only when nothing matched. Of 18 lines, 10 foods and 4 units (gram, tablespoon, teaspoon, pinch) already existed and were reused; 8 foods and 1 unit (`handful`) were created.
- **Matching must be case-insensitive.** `salt` matched the existing `Salt`. A case-sensitive exact match would have created a duplicate. Match on name and plural name for foods; on name, plural name and abbreviation for units (`tbsp` → `tablespoon`).
- **Created Foods keep the pipeline's own spelling**, lower case (`green chilli`, `kasuri methi`). Reuse always keeps the catalog's spelling (`Salt`), never the pipeline's.
- **Specific names stay separate foods.** `turmeric powder`, `cumin powder`, `dry mango powder` and `cumin seeds` were new foods rather than being folded into `turmeric`, `cumin` etc. Only matches that are exact, plural, alias or singularized should reuse; fuzzy ≥ 92 on short names can merge things that differ ("cumin seeds" vs "cumin powder"), so the fuzzy threshold needs a test case for that.
- **Qualifiers go in the note, not the food name.** "2 small onions" → food `onion`, note `small`; "garlic, roughly chopped" → food `garlic`, note `roughly chopped`; "lady finger" → food `okra`, note `lady finger / bhindi`.
- **Unit-less and quantity-less lines are valid.** `unit: null`; `quantity: 0` for "to taste" / "as required".
- Unit creation needs `abbreviation: ""`, not null (422 otherwise); see ticket 01's Comments.
- The new-Food/Unit log (`created_foods.csv`, `created_units.csv`) should record the video the name first came from, so a bad auto-created entry can be traced and merged (`PUT /api/foods/merge`).
