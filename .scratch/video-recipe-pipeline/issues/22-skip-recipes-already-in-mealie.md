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

**Status:** in-progress

**Read first:** `spec.md` modules 4, 13 and 14; wayfinder ticket `03-mealie-api-contract.md` (recipe listing, PATCH-only).

- [ ] `MealieGateway.list_recipe_summaries()` returns all summaries (`perPage=-1`). It's contract-tested in the shared suite, and `FakeMealie` supports it.
- [ ] Building the Existing Link Set is pure and table-tested with real-looking `orgURL` variants:
  - Instagram `/p/`, `/reel/`, `/reels/`, `igsh`, `utm_*`, `m.instagram.com`
  - YouTube `youtu.be`, `/shorts/`, `si`, `&t=` timestamps (multi-recipe parts)
  - Facebook `/reel/`, `/watch/?v=`
  - website URLs with and without `www.`, trailing slash and `?utm_`
  - empty and garbage values, which are ignored
- [ ] Multi-recipe Videos: a key match on the Video Key counts as "this Video is already in Mealie". Parts that are already present (`extras.item_key` / timestamped `orgURL`) are skipped individually once ticket 12 exists.
- [ ] Pipeline-seam test: `FakeMealie` holds a recipe whose `orgURL` is the same reel with different tracking parameters. The Video makes **zero** LLM calls (`FakeLLM` call log) and no Mealie writes, and `report.csv` shows `already_in_mealie` with the existing recipe's link.
- [ ] Pipeline-seam test for the pre-upload re-check: the recipe appears in `FakeMealie` between extraction and upload, so there's no upload and the status is `already_in_mealie`.
- [ ] Recipes the pipeline didn't create are never written to without `--upgrade-existing`. One test asserts no write in default mode, and another asserts an in-place PATCH (same slug, rating/comments/dateAdded untouched) with the flag.
- [ ] `mp status` and the run summary show the `already_in_mealie` and `upgraded_existing` counts.

**Manual check on the laptop (user):** run `uv run mp run --stages metadata,classify --dry-run` on a list that contains reels you already imported. Check that `reports/report.csv` marks them `already_in_mealie` with links to your existing recipes.
