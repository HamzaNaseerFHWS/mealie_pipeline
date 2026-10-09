# 22: Never re-upload a recipe that's already in Mealie (incl. earlier manual and Mealie-import recipes)

**What to build:** The user has already imported recipes into Mealie by hand and with Mealie's own import, mostly from Instagram. Before the pipeline spends Claude usage on a Video, and again just before it uploads, it checks whether that recipe already exists in Mealie and **doesn't upload a duplicate**.

**How it works:**
- **Index at run start:** build an **Existing Recipe Index** from `GET /api/recipes?perPage=-1`. Each recipe summary has `name`, `slug`, `orgURL`, `tags`, `dateAdded`.
- **Normalize `orgURL`:** every `orgURL` goes through the URL Normalizer, so `https://www.instagram.com/reel/ABC/?igsh=…`, `/p/ABC/` and `/reels/ABC` all become `instagram:ABC`. Website URLs are normalized too (scheme, `www.`, trailing slash, tracking parameters removed).
- **Check 1, before extraction** (cheap, saves usage): when a Video's Video Key or chosen Recipe Website URL matches an existing recipe's normalized `orgURL`, the Video is marked `already_in_mealie` with the existing slug/link and **skips all AI stages**.
- **Check 2, before upload** (catches recipes whose `orgURL` is empty, different, or points elsewhere): compare the extracted recipe's name with existing names (normalized: lowercase, accents and emoji stripped, filler words like "easy", "best", "recipe" and "the" removed). For candidates with fuzzy name similarity ≥ 90 (settings), fetch the full recipe and compute ingredient overlap. Existing recipes from Mealie's own import usually hold unparsed note text, so compare English food words from our Parsed Ingredients against the existing recipe's food names *and* note text.
  - **name ≥ 90 and ingredient overlap ≥ 0.5:** probable duplicate. **Don't upload.** Mark `possible_duplicate`, write both links into the Review Queue file and a `reports/existing_matches.csv` row with an `override` column (`upload` / `skip` / `replace`).
  - **Name match but low overlap:** treat as a different recipe and upload (for example two different "Chicken Karahi" recipes), noted in the report.
- **Recipes the pipeline created** (they carry `extras.item_key`) keep the existing `--mode skip|update` behaviour from ticket 02.
- **Recipes the pipeline did *not* create** are never modified by default. An explicit opt-in, `--upgrade-existing` (or `override=replace` per row), PATCHes the old, badly imported recipe in place with the pipeline's parsed version: ingredients, steps, tags, `extras`. Slug, rating, comments, `dateAdded` and the existing image stay unless the old recipe has no image. This turns old Mealie imports into properly parsed recipes without creating a second copy.

**Blocked by:** 04 (URL Normalizer), 03

**Status:** ready-for-agent

**Read first:** `spec.md` modules 4, 13 and 14; wayfinder ticket `03-mealie-api-contract.md` (recipe listing, `org_url` filter, PATCH-only); ticket 18 (which reuses this index for cross-platform dedupe).

- [ ] `MealieGateway.list_recipe_summaries()` returns all summaries (paginated or `perPage=-1`). It's contract-tested in the shared suite, and `FakeMealie` supports it.
- [ ] The Existing Recipe Index is built once per run (refreshed after each upload batch). It maps normalized Video Keys, normalized website URLs and normalized names to slugs. It's a pure module, table-tested with real-looking `orgURL` variants: Instagram `/p/`, `/reel/`, `/reels/`, `igsh`, `utm_*`, `m.instagram.com`; YouTube `youtu.be`, `shorts`, `si`; Facebook share links already resolved; website URLs with and without `www.`/trailing slash/`?utm_`.
- [ ] Name normalization and the duplicate decision (name score + ingredient overlap) are pure and table-tested with hand-written cases: same reel imported earlier with a different title, same title but a different recipe, an old import with note-only ingredients, and a German/Roman-Urdu name vs an English old name (no match, by design).
- [ ] Check 1 runs before the `extract` stage. A pipeline-seam test confirms that a Video whose URL matches an existing `orgURL` (with different tracking parameters) makes **zero** LLM calls (`FakeLLM` call log) and no Mealie writes, and appears in `report.csv` as `already_in_mealie` with the existing Mealie link.
- [ ] Check 2 runs right before upload. Pipeline-seam tests:
  - (a) an existing recipe with the same name and overlapping ingredients but an empty `orgURL` → no upload, `possible_duplicate`, review file shows both
  - (b) the user sets `override=upload` in `existing_matches.csv` → the next run uploads
  - (c) `override=replace` / `--upgrade-existing` → the old recipe is PATCHed in place (same slug), and rating/comments/dateAdded are untouched
- [ ] Existing recipes not created by the pipeline are never PATCHed or deleted without the explicit opt-in. A test asserts no write happens to them in default mode.
- [ ] `mp status` and the run summary show the counts `already_in_mealie`, `possible_duplicate` and `upgraded_existing`.

**Manual check on the laptop (user):** run `uv run mp run --stages metadata,classify --dry-run` on a list that contains reels you already imported. Check that `reports/report.csv` marks them `already_in_mealie` with links to your existing recipes, and look through `reports/existing_matches.csv` for name-only matches.
