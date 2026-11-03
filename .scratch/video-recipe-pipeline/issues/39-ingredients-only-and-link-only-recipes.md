# 39: Ingredients-only captions are recipes; no-text videos become link-only stubs

**What to build:** Two changes so that every Video `classify` keeps ends up in Mealie (ADR 0007: no audio transcription).

1. **Partial recipes.** Many Instagram/Facebook captions list only ingredients, or ingredients plus a link, with no steps. That is a valid recipe, not a failure and never something to transcribe.
   - Extract accepts a Recipe Part with ingredients and **no steps** when the ingredients are grounded in a Source (caption, pinned comment, subtitles or website).
   - Ingredients are parsed and tagged as usual. The source link goes in as the recipe's original URL, and the recipe gets the tag `partial-recipe`.
   - A linked page is still followed first (ticket 06/17). The caption-only path applies when no page yields a recipe.
   - The Gate (ticket 08) stops treating empty steps as a failure for these; S2's "ingredients used in steps" direction is left out of the average, as for any check that doesn't apply. Ungrounded ingredients still fail.
2. **Link-only stubs.** A Video that `classify` kept (`recipe` or `recipe_partial`) but that has no usable text (no ingredients in caption, comment, subtitles or any linked page) is uploaded as a stub: **name** (from the title, or the first caption line, cleaned), **thumbnail** (`images.py`), **source link** as original URL, and **tags** (platform, Creator and any Rule Tags that apply, at least one existing tag, plus `link-only`). No ingredients, no steps, no extraction call for the recipe body.
   - Videos labelled `restaurant_or_place`, `ad_or_product`, `eating_or_review`, `not_food` or `uncertain` stay skipped.
   - A stub skips the Gate's grounding and quality checks (nothing to ground) but keeps the hard checks: it has a name, a link and a tag. If the name can't be built, hold it for review.
   - No automatic upgrade later. A stub re-runs only if the user resets it.
3. `mp report` shows `partial-recipe` and `link-only` as outcomes. The Telegram inbox (ticket 33) reports a stub as `done` with its Mealie link.

**Blocked by:** 02, 08. Interacts with 34 (subtitles are tried before a stub) and 36 (a multi-recipe-looking title with nothing to split goes to review, unless there is no text at all, then a stub).

**Status:** ready-for-agent

**Read first:** `ADR 0007`, `src/mealie_pipeline/pipeline.py` (extract, verify and upload stages), `verify.py`, `images.py`, `uploader`, `prompts/` (extract prompt), ticket 08.

- [ ] Pure tests: "has usable text" rule (ingredients present vs. hashtags/emoji only/promo text); stub-name builder; Gate with empty steps passes when ingredients are grounded and fails when they aren't.
- [ ] Pipeline-seam tests with `FakeMealie`, `FakeLLM`, fake `VideoSource`: (a) ingredients-only caption → recipe with parsed ingredients, no steps, tag `partial-recipe`, source link; (b) ingredients + link to a page with a recipe → the page wins and no `partial-recipe` tag; (c) hashtags-only caption → stub with name, thumbnail, link, `link-only` and platform tags, and no LLM extraction call; (d) a `restaurant_or_place` video → still skipped.
- [ ] Stub upload sets the thumbnail image; if the thumbnail download fails the stub still uploads without one and the report says so.
- [ ] Tags `partial-recipe` and `link-only` are created in Mealie if missing (check how ticket 10's tag creation rules apply; these two are the only tags the pipeline may create).
- [ ] `mp report` and the inbox result reflect both outcomes.

**Manual check on the laptop (user):** run 5 Instagram posts with ingredient-only captions and 5 with nothing useful; open them in Mealie and check the ingredients list, thumbnail, source link and tags.
