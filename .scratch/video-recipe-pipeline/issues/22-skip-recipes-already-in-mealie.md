# 22: Never re-upload a recipe that's already in Mealie (link set check)

**What to build:** The user has already imported recipes into Mealie, mostly from Instagram, and every recipe in Mealie carries its original link in `orgURL`. Before the pipeline does any work on a Video, it checks whether that link is already in Mealie with a **set lookup**, and if so, skips the Video.

1. At run start, read all recipe summaries once: `GET /api/recipes?perPage=-1` gives `slug`, `name` and `orgURL` for every recipe.
2. Turn each `orgURL` into a key with the URL Normalizer (ticket 04):
   - Video links become a Video Key (`https://www.instagram.com/reel/ABC/?igsh=…`, `/p/ABC/` and `/reels/ABC` all become `instagram:ABC`).
   - Website links become a normalized URL (scheme, `www.` and trailing slash dropped, tracking parameters removed).
   - Store them in a `set` / `dict key → slug`. This is the **Existing Link Set**.
3. **Before extraction** (so already-imported Videos cost no Claude usage): if the Video's Video Key, or its chosen Recipe Website URL, is in the set, mark it `already_in_mealie` with the existing recipe's link and skip all later stages.
4. **Right before upload**, check again against a refreshed set, because an earlier batch or a manual import may have added it meanwhile. The refresh is one listing call per upload batch.
5. Recipes the pipeline uploads itself are added to the set immediately.
6. Recipes the user imported earlier are **never modified** by default. Opt-in `--upgrade-existing` PATCHes such a recipe in place with the pipeline's parsed version: ingredients, steps, tags and `extras`. Slug, rating, comments, `dateAdded` and the image are kept. This fixes an old, badly parsed import without making a second copy.

No name-based or fuzzy matching: the link is the identity. Recipes without an `orgURL` aren't matched, and that's accepted.

**Blocked by:** 03

**URL Normalizer:** this ticket comes before ticket 04 in the build order (Phase A). If the URL Normalizer (spec module 4) doesn't exist yet, build it here as specified in spec module 4 and ticket 04's first acceptance criterion, with those table tests. Ticket 04 then reuses it instead of building its own.

**Status:** done

**Read first:** `spec.md` modules 4, 13 and 14; wayfinder ticket `03-mealie-api-contract.md` (recipe listing, PATCH-only).

- [x] `MealieGateway.list_recipe_summaries()` returns all summaries (`perPage=-1`). It's contract-tested in the shared suite, and `FakeMealie` supports it.
- [x] Building the Existing Link Set is pure and table-tested with real-looking `orgURL` variants:
  - Instagram `/p/`, `/reel/`, `/reels/`, `igsh`, `utm_*`, `m.instagram.com`
  - YouTube `youtu.be`, `/shorts/`, `si`, `&t=` timestamps (multi-recipe parts)
  - Facebook `/reel/`, `/watch/?v=`
  - website URLs with and without `www.`, trailing slash and `?utm_`
  - empty and garbage values, which are ignored
- [x] Multi-recipe Videos: a key match on the Video Key counts as "this Video is already in Mealie". Parts that are already present (`extras.item_key` / timestamped `orgURL`) are skipped individually once ticket 12 exists.
- [x] Pipeline-seam test: `FakeMealie` holds a recipe whose `orgURL` is the same reel with different tracking parameters. The Video makes **zero** LLM calls (`FakeLLM` call log) and no Mealie writes, and `report.csv` shows `already_in_mealie` with the existing recipe's link.
- [x] Pipeline-seam test for the pre-upload re-check: the recipe appears in `FakeMealie` between extraction and upload, so there's no upload and the status is `already_in_mealie`.
- [x] Recipes the pipeline didn't create are never written to without `--upgrade-existing`. One test asserts no write in default mode, and another asserts an in-place PATCH (same slug, rating/comments/dateAdded untouched) with the flag.
- [x] `mp status` and the run summary show the `already_in_mealie` and `upgraded_existing` counts.

**Manual check on the laptop (user):** run `uv run mp run --stages metadata,classify --dry-run` on a list that contains reels you already imported. Check that `reports/report.csv` marks them `already_in_mealie` with links to your existing recipes.

## Comments

### Built (2026-10-26)

- **`MealieGateway.list_recipe_summaries()`**: all recipes' `slug`, `name`, `orgURL` in one call (`perPage=-1`). Contract-tested for the fake and the local HTTP server (and the opt-in live suite) in `tests/test_mealie_summaries.py`, including the exact request shape.
- **URL Normalizer** (`url_normalizer.py`, built here because ticket 04 comes later): YouTube (`youtu.be`, `/shorts/`, `si`, `&t=`), Instagram (`/p/`, `/reel/`, `/reels/`, `/tv/`, behind a username, `m.`, `igsh`, `utm_*`), Facebook (`/reel/`, `/watch/?v=`, `/<page>/videos/<id>`, `mibextid`, `fbclid`) and `normalize_website` (no scheme, `www.`/`m.`, fragment, trailing slash or tracking parameters; garbage -> None). `fb.watch` and `/share/` short links are left for the caller to resolve by redirect. Table tests in `tests/test_url_normalizer*.py`. `mp add` still accepts only YouTube until the other collectors exist.
- **Existing Link Set** (`existing_links.py`, pure): `link_key(orgURL)` and `build_link_set(summaries) -> {key: slug}`; the first recipe wins a key; empty and garbage `orgURL`s are ignored; no name matching.
- **New `linkcheck` stage** between `metadata` and `extract` (so nothing paid happens first): a match marks the part `already_in_mealie` (new Stage Record status) with the existing recipe's link, and all later stages are skipped. **`upload`** checks again against a fresh listing (one listing per batch, taken lazily; the pipeline's own uploads are added to the set at once). A recipe the pipeline created itself (same slug as the part's) is never mistaken for an old import, so `mp reset linkcheck` + `mp run --mode update` still works.
- **`--upgrade-existing`**: PATCHes the matching old recipe in place with parsed ingredients, steps, the pipeline's tags added to its own, and merged `extras`; read back and compared; Stage Record status `upgraded_existing`. Name, image, rating, comments and `dateAdded` are not sent, so they stay. Without the flag nothing the pipeline did not create is ever written to (tested for both default and `--mode update`).
- `mp status` shows "Already in Mealie / Upgraded existing" counts; the `mp run` summary prints the same; `report.csv` gets a `linkcheck_status` column and shows `already_in_mealie` with the existing recipe's link in `mealie_url`.

### Notes

- Website-URL matching is built and tested at the set level, but nothing feeds a website URL into the check until the Recipe Website Sources exist (tickets 06/27/17). Multi-recipe per-part skipping waits for ticket 12; a Video Key match already counts as "this Video is in Mealie".
- Upgrade tags are the old tags plus the new ones (nothing removed), which seemed safer than replacing curated tags.

### Manual verification on the laptop (user)

1. Pick 2 or 3 Instagram/YouTube links you already imported into Mealie (their recipes must have the link in the "original URL" field) and one you have not. For now `mp add` takes YouTube URLs only, so use YouTube ones.
2. `uv run mp add <those urls>`
3. `uv run mp run --stages metadata,linkcheck --dry-run` (no AI call, no Mealie write).
4. `uv run mp report`, open `reports/report.csv`: the already-imported ones show `linkcheck_status = already_in_mealie` and a `mealie_url` that opens your existing recipe; the new one shows `done`.
5. `uv run mp status` shows "Already in Mealie: N".
6. Optional: `uv run mp run --upgrade-existing --limit 1` on one old badly parsed import: the same recipe now has parsed ingredients and keeps its rating, comments and image.
