# 30: Keep the source's food names and store them as Mealie Food aliases

**What to build:** When an Ingredient Line is not English, the extraction also returns the food's name exactly as the source wrote it (`food_original`, e.g. "Muschelnudeln" for "500 g Muschelnudeln"). The Parse stage uses it two ways, and the Gate's ingredients-vs-steps check (S2) reads it:

1. **Link through an alias first.** If `food_original` already is the name or an alias of a Mealie Food, that Food is used, whatever the English translation said.
2. **Otherwise record the alias.** The Food found or created for the English name gets `food_original` added to its aliases in Mealie (`PUT /api/foods/{id}`), so the next German recipe with that word links straight to it. Each added alias is logged in `reports/created_aliases.csv`.
3. **S2 accepts either language.** An ingredient counts as "used in a step" when its English food name *or* its `food_original` appears in a step, and a step word that matches a `food_original` counts as listed. German recipes stop scoring around 58 just because the ingredient list is English and the steps are German.

This keeps ADR 0003: one Food per thing (an onion is one Food, shopping lists still merge); the German word is only an alias on the English Food. The recipe text and `originalText` stay as before.

**Blocked by:** None (tickets 03 and 28 are done)

**Status:** done

**Read first:** `docs/adr/0003-*.md`, `src/mealie_pipeline/matching.py`, `pipeline.py` (`_parse_ingredients`), `checks.py`, `prompts/extract.md`.

- [ ] `ExtractedIngredient.food_original` and `ParsedIngredient.food_original` exist (default empty); old stored extractions still load.
- [ ] `prompts/extract.md` asks for `food_original` only for non-English ingredient lines, as the bare food name without amount, unit or preparation.
- [ ] `FoodMatcher.match(name, foods, original=...)` returns the Food that has `original` as name, plural or alias before trying the English name (kind `alias`); when the English name matches a Food that lacks the alias it returns `new_alias=original`; the same for a Food that has to be created. Nothing is aliased when `original` equals the English name, is empty, or is longer than 3 words or reads like a choice, a list or a plural marker ("oder", "/", "(n)"), or when the English Food was only a fuzzy guess. Table-tested.
- [ ] The Mealie port gets `add_food_alias(food_id, alias)`: the HTTP adapter reads the Food and writes it back with the alias appended (keeping all its other fields); the fake and the fake Mealie server do the same. Contract-tested against the local fake server.
- [ ] Pipeline-seam test with the fakes: a German recipe adds the alias to the English Food, a second German recipe with the same word links through the alias without a second add, an English recipe adds nothing, an ungrounded ingredient adds nothing, and a dry run writes nothing to Mealie.
- [ ] `reports/created_aliases.csv` lists each added alias as `alias -> Food` with the Video Key it came from.
- [ ] S2: table tests for an English ingredient list with German steps (score 1.0) and for a step food listed only through its `food_original`.

**Manual check on the laptop (user):** `mp retry <item> --stage extract` for a held German recipe, `mp run`; open the Food list in Mealie and look at the aliases that were added, and at the recipe's score.

## Comments

### Built (2026-10-29)

- **Extraction:** `ExtractedIngredient.food_original` (prompt rule 4 in `prompts/extract.md`); `ParsedIngredient.food_original` carries it on. Old stored extractions load unchanged.
- **Matcher:** `FoodMatcher.match(name, foods, original)`. A Food that already has `original` as name, plural or alias wins (kind `alias`). Otherwise the English match comes back with `new_alias`. No alias is offered when `original` is empty or equal to the English name, has more than 3 words, reads like a choice/list/plural marker ("oder", "und", "/", "(n)", digits), or when the English match was only fuzzy.
- **Parse:** `Pipeline._add_food_alias` calls the new `MealieGateway.add_food_alias` (HTTP: GET the Food, PUT it back with the alias appended; the fake and `tests/mealie_server.py` do the same), keeps the Catalog's Food in step and logs `alias -> Food` in `reports/created_aliases.csv`. Ungrounded ingredients and dry runs add nothing.
- **S2:** `ingredients_vs_steps(..., original_names)`: either spelling counts as used and as listed.
- **Tests:** `tests/test_german_aliases.py` (6, pipeline seam), matcher and S2 tables, a PUT-shape test in `test_mealie_http_shapes.py`.

### Real run (user's Mealie)

The 14 held German recipes were re-extracted and uploaded (2 stayed held: Lentil Bolognese has no method, the vegan sausages page is not what was asked). Scores went from 58 or less up to 65 to 100; only the lowest still carry `To Review`. 95 aliases were added. About 16 of them were wrong or too generic ("schnittlauch" on parsley, "öl" on sunflower oil, "pita/fladenbrot oder toast", "tomate(n)", ...). The guards above were added because of them and the 16 were removed from Mealie by hand. **Review `reports/created_aliases.csv` and the Food list for the rest.**

### Deferred

- The 245 German recipes imported before this ticket were not re-extracted, so they taught no aliases. `mp retry <key> --stage extract` per recipe does it (one `claude` call each).
- Aliases are only ever added; nothing removes or corrects a wrong one.
- The Foods the English matcher creates for German words (for example "colorful pasta") are still whatever the model translated.

### Manual verification on the laptop (user)

1. Open Settings > Data Management > Foods in Mealie and search "Zwiebel": it should be an alias of "onion", not a Food.
2. Skim `reports/created_aliases.csv` for aliases that point at the wrong Food and remove them in Mealie.
3. Import another German page; its score should no longer sit around 58 just for the language mismatch.
