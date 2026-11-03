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

**Status:** done

**Read first:** `ADR 0007`, `src/mealie_pipeline/pipeline.py` (extract, verify and upload stages), `verify.py`, `images.py`, `uploader`, `prompts/` (extract prompt), ticket 08.

- [x] Pure tests: "has usable text" rule (ingredients present vs. hashtags/emoji only/promo text); stub-name builder; Gate with empty steps passes when ingredients are grounded and fails when they aren't.
- [x] Pipeline-seam tests with `FakeMealie`, `FakeLLM`, fake `VideoSource`: (a) ingredients-only caption → recipe with parsed ingredients, no steps, tag `partial-recipe`, source link; (b) ingredients + link to a page with a recipe → the page wins and no `partial-recipe` tag; (c) hashtags-only caption → stub with name, thumbnail, link, `link-only` and platform tags, and no LLM extraction call; (d) a `restaurant_or_place` video → still skipped.
- [x] Stub upload sets the thumbnail image; if the thumbnail download fails the stub still uploads without one and the report says so.
- [x] Tags `partial-recipe` and `link-only` are created in Mealie if missing (check how ticket 10's tag creation rules apply; these two are the only tags the pipeline may create).
- [x] `mp report` and the inbox result reflect both outcomes.

**Manual check on the laptop (user):** run 5 Instagram posts with ingredient-only captions and 5 with nothing useful; open them in Mealie and check the ingredients list, thumbnail, source link and tags.

## Comments

**Built**
- `partial.py` (pure):
  - `has_usable_text`: true when there are at least 2 ingredient-like lines (an amount and unit, or bullets under an "Ingredients/Zutaten" heading) or a method (3+ cooking verbs in 25+ words). Hashtags, @mentions, links, emoji and promo text are stripped first.
  - `stub_name`: the title, else the first caption line. Hashtags, emoji, "shorts/reels" and a trailing " | Channel" are cleaned off, and the result is capped at 80 characters.
  - `recipe_kind`: full, partial or stub, derived from the extraction itself, so no new database column.
- **Partial recipes:** extract keeps an extraction with ingredients and no steps. The prompt now says an ingredient list without a method is a recipe and that steps must never be invented. In the Gate (`evaluate(..., partial=True)`), H2 needs 2 ingredients and 0 steps, and S2 is left out of the average. Ungrounded ingredients still fail H3. The judge is told missing steps are expected. The recipe gets the tag `partial-recipe`.
- **Link-only stubs:** when no website recipe was found and the caption, pinned comment and subtitles fail `has_usable_text`, extract builds the stub with **no LLM call**: name, plus a description "Saved from <Platform>. Open the original link for the recipe."
  - Tags: Rule Tags, the platform and Creator tags when Mealie has them, and `link-only`.
  - The Gate runs only the hard checks (name, link, tag); `verify.outcome = link_only`.
  - Upload sets the thumbnail. If the image fails, the stub still uploads and the run reports `image_missing`.
  - If no name can be built, the item goes to review.
  - A stub is never redone unless reset.
- The pipeline creates `partial-recipe` and `link-only` the first time they're needed. Apart from the review tag, these are the only tags it creates.
- The pinned comment is now saved by scrape (`data/<platform>/<id>/comment.txt`) and is a Source `[SRC:cmt]` for extraction and grounding.
- `report.csv` has a new `recipe_kind` column (`recipe` / `partial-recipe` / `link-only`). `mp run` marks uploads `(partial-recipe)` / `(link-only)`.
- Recipe Requests (website links) never become stubs.
- If the text looks usable but the extraction says "not a recipe", the item still **fails** as before (existing test) rather than becoming a stub.
- GLOSSARY: Partial Recipe, Link-only Stub.

**Deferred:** the `sub` (subtitles) Source is added by ticket 34, which plugs into the same `has_usable_text` check. The inbox result for stubs is part of ticket 33.

**Manual check on the laptop (user):** run 5 Instagram posts whose captions list only ingredients and 5 with nothing useful. In Mealie check:
- the ingredient-only ones have parsed ingredients, no steps, the `partial-recipe` tag and the source link;
- the empty ones are link-only stubs with the thumbnail, the source link and the `link-only` tag;
- `uv run mp report` shows the `recipe_kind` column.
