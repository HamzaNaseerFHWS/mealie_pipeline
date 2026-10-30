# 10: Trustworthy tags from the full tag list plus rules

**What to build:** Upgrade the `tag` stage:
- **LLM choices:** the full Catalog tag list (no 200 cap) is passed as an enum, so only existing tags can come back.
- **Rule Tags** (`config/tag_rules.yaml`), evaluated on parsed Foods, times, Recipe Language and drink-ness. For example: no meat/fish Foods → the user's vegetarian tag; total ≤ 30 min → quick; drink → the drinks tag. Rules only name tags that exist, and a rule naming a missing tag is reported by `mp doctor`.
- **Contradiction removal:** for example, drop a vegetarian tag when a meat Food is present, and flag it.
- **Tag count:** keep 1–6 tags. If none survive, retry once, then fall back to `To Review`.
- **New tags:** suggestions go only to `reports/suggested_tags.csv`.

**Blocked by:** 09, 25

**Status:** done

**Read first:** `spec.md` module 11; `PIPELINE_SPEC.md` §8. The real rule mapping is confirmed in wayfinder ticket 19. Ship `tag_rules.yaml` with commented examples that use placeholder tag names, and validate at startup that every named tag exists.

- [x] Tag matching is case-, whitespace- and punctuation-insensitive (and compares slugs), so "Quick ", "quick" and "Quick!" resolve to the one existing tag. The pipeline never creates a tag that differs from an existing one only in case or spacing. Pure and table-tested.
- [x] Categories are **not** set in v1 (tags only, pending wayfinder 19). The payload never includes `recipeCategory`.
- [x] Protein Tags (ticket 25) are one of the Rule Tag families: the tagger calls ticket 25's detection on the parsed Foods and adds the matching Protein Tags. A newly uploaded chicken recipe carries `Chicken`.
- [x] Rule evaluation and contradiction removal are pure and table-tested (meat/fish/egg/dairy Food lists in config; vegetarian vs vegan handled separately).
- [x] Tag choice ranking: rule tags first, then LLM tags by rank, deduped, capped at 6.
- [x] `mp doctor` lists rules whose tag is missing from Mealie.
- [x] Pipeline-seam tests:
  - (a) the LLM suggests a non-existent tag: it is not applied and lands in `suggested_tags.csv`
  - (b) a chicken recipe the LLM tagged vegetarian loses that tag
  - (c) nothing applies, so `To Review` is created once and applied

## Comments

**Built**
- `src/mealie_pipeline/tagging.py` (pure): `TagRules` loaded from `config/tag_rules.yaml` (food groups, drink words, `rules` with `when` conditions `no_foods_in` / `any_foods_in` / `max_total_minutes` / `language` / `drink`, and `contradictions`), `rule_tags`, `contradictions`, `match_existing` (case/space/punctuation-insensitive, via ticket 25's `tag_key`), and `choose` (rule tags first, then LLM tags by rank, deduped).
- Tag stage (`pipeline.py`): rule tags + Protein Tags (ticket 25) first, LLM tags after, contradictions removed and flagged as a run warning, capped at 6 after removal. If nothing survives: one re-extraction at the strongest tier, then the `To Review` tag (created once). LLM tags that match no existing tag go to `reports/suggested_tags.csv` (once per tag). The full tag list was already passed as the enum with no cap.
- `mp doctor` warns about rules naming a tag missing from Mealie ("Tag rules" check). Such a rule never applies.
- `config/tag_rules.yaml` ships with food groups and drink words, and the rules and contradictions as commented examples with placeholder tag names (real mapping is wayfinder 19/20).
- No category is ever set (nothing in the payload builder writes `recipeCategory`; a seam test asserts it).
- Tests: `tests/test_tag_rules_pure.py`, `tests/test_tagging_seam.py` (a, b, c from the ticket plus matching and no-category), doctor test.

**Behaviour changes to older tests (deliberate, per this ticket)**
- `test_no_matching_tag_fails_the_item` became `test_no_matching_tag_uploads_with_the_review_tag` (no tag no longer fails the item).
- The ticket-25 chicken test now expects `["Chicken", "Dinner"]` (rule tags rank first).

**Deferred**
- Real rules are not enabled: `rules` and `contradictions` are empty until the user picks tag names (wayfinder 19/20).
- Drink-ness is by words in the recipe name only.
- I did not run the `code-review` skill; lint, types and the full test suite pass.

**Manual verification (on the laptop)**
1. In `config/tag_rules.yaml`, uncomment the examples and rename tags to ones that exist in your Mealie. Run `uv run mp doctor`: the "Tag rules" line should be OK. Rename one to a nonexistent tag and confirm it shows WARN naming it.
2. `uv run mp run --limit 3` on a vegetarian and a meat video: the meat recipe must not carry Vegetarian, and the run output shows `removed tag ...` warnings. Check the recipes in Mealie.
3. Check `reports/suggested_tags.csv` appears only when the LLM names a tag Mealie lacks, and that no new tags were created in Mealie other than `To Review`.
