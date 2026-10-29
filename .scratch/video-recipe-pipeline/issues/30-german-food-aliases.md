# 30: Keep the source's food names and store them as Mealie Food aliases

**What to build:** When an Ingredient Line is not English, the extraction also returns the food's name exactly as the source wrote it (`food_original`, e.g. "Muschelnudeln" for "500 g Muschelnudeln"). The Parse stage uses it two ways, and the Gate's ingredients-vs-steps check (S2) reads it:

1. **Link through an alias first.** If `food_original` already is the name or an alias of a Mealie Food, that Food is used, whatever the English translation said.
2. **Otherwise record the alias.** The Food found or created for the English name gets `food_original` added to its aliases in Mealie (`PUT /api/foods/{id}`), so the next German recipe with that word links straight to it. Each added alias is logged in `reports/created_aliases.csv`.
3. **S2 accepts either language.** An ingredient counts as "used in a step" when its English food name *or* its `food_original` appears in a step, and a step word that matches a `food_original` counts as listed. German recipes stop scoring around 58 just because the ingredient list is English and the steps are German.

This keeps ADR 0003: one Food per thing (an onion is one Food, shopping lists still merge); the German word is only an alias on the English Food. The recipe text and `originalText` stay as before.

**Blocked by:** None (tickets 03 and 28 are done)

**Status:** in-progress

**Read first:** `docs/adr/0003-*.md`, `src/mealie_pipeline/matching.py`, `pipeline.py` (`_parse_ingredients`), `checks.py`, `prompts/extract.md`.

- [ ] `ExtractedIngredient.food_original` and `ParsedIngredient.food_original` exist (default empty); old stored extractions still load.
- [ ] `prompts/extract.md` asks for `food_original` only for non-English ingredient lines, as the bare food name without amount, unit or preparation.
- [ ] `FoodMatcher.match(name, foods, original=...)` returns the Food that has `original` as name, plural or alias before trying the English name (kind `alias`); when the English name matches a Food that lacks the alias it returns `new_alias=original`; the same for a Food that has to be created. Nothing is aliased when `original` equals the English name, is empty, or is longer than 4 words. Table-tested.
- [ ] The Mealie port gets `add_food_alias(food_id, alias)`: the HTTP adapter reads the Food and writes it back with the alias appended (keeping all its other fields); the fake and the fake Mealie server do the same. Contract-tested against the local fake server.
- [ ] Pipeline-seam test with the fakes: a German recipe adds the alias to the English Food, a second German recipe with the same word links through the alias without a second add, an English recipe adds nothing, an ungrounded ingredient adds nothing, and a dry run writes nothing to Mealie.
- [ ] `reports/created_aliases.csv` lists alias, Food and the Video Key it came from.
- [ ] S2: table tests for an English ingredient list with German steps (score 1.0) and for a step food listed only through its `food_original`.

**Manual check on the laptop (user):** `mp retry <item> --stage extract` for a held German recipe, `mp run`; open the Food list in Mealie and look at the aliases that were added, and at the recipe's score.
