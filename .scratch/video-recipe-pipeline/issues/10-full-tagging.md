# 10: Trustworthy tags from the full tag list plus rules

**What to build:** Upgrade the `tag` stage:
- **LLM choices:** the full Catalog tag list (no 200 cap) is passed as an enum, so only existing tags can come back.
- **Rule Tags** (`config/tag_rules.yaml`), evaluated on parsed Foods, times, Recipe Language and drink-ness. For example: no meat/fish Foods → the user's vegetarian tag; total ≤ 30 min → quick; drink → the drinks tag. Rules only name tags that exist, and a rule naming a missing tag is reported by `mp doctor`.
- **Contradiction removal:** for example, drop a vegetarian tag when a meat Food is present, and flag it.
- **Tag count:** keep 1–6 tags. If none survive, retry once, then fall back to `To Review`.
- **New tags:** suggestions go only to `reports/suggested_tags.csv`.

**Blocked by:** 09

**Status:** ready-for-agent

**Read first:** `spec.md` module 11; `PIPELINE_SPEC.md` §8. The real rule mapping is confirmed in wayfinder ticket 19. Ship `tag_rules.yaml` with commented examples that use placeholder tag names, and validate at startup that every named tag exists.

- [ ] Tag matching is case-, whitespace- and punctuation-insensitive (and compares slugs), so "Quick ", "quick" and "Quick!" resolve to the one existing tag. The pipeline never creates a tag that differs from an existing one only in case or spacing. Pure and table-tested.
- [ ] Categories are **not** set in v1 (tags only, pending wayfinder 19). The payload never includes `recipeCategory`.
- [ ] Rule evaluation and contradiction removal are pure and table-tested (meat/fish/egg/dairy Food lists in config; vegetarian vs vegan handled separately).
- [ ] Tag choice ranking: rule tags first, then LLM tags by rank, deduped, capped at 6.
- [ ] `mp doctor` lists rules whose tag is missing from Mealie.
- [ ] Pipeline-seam tests:
  - (a) the LLM suggests a non-existent tag: it is not applied and lands in `suggested_tags.csv`
  - (b) a chicken recipe the LLM tagged vegetarian loses that tag
  - (c) nothing applies, so `To Review` is created once and applied
