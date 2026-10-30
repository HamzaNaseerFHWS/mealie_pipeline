# 09: Two ingredient parsers must agree

**What to build:** Upgrade the `parse` stage so every English Ingredient Line is parsed by two engines: engine A is `ingredient-parser-nlp`; engine B is the LLM parse that the extraction call already returns. They are reconciled per the rules in `PIPELINE_SPEC.md` §7:
- `agreed`: accept
- `nlp_preferred`: one field differs and NLP confidence for it is ≥ 0.9
- `conflict`: LLM result used, flagged
- `unparsed`: note-only line, sent to review

Add Sanity Checks (implausible quantity per unit, a unit used as the food, count units with liquids) and feed the parse agreement (S3) and sanity (S5) results into the verification score. Ingredients get linked to steps through `ingredientReferences`.

**Blocked by:** 08

**Status:** done

**Read first:** `spec.md` module 10 and the payload builder in module 13; `PIPELINE_SPEC.md` §7.

- [x] Reconcile is pure and table-tested with hand-written cases for each outcome, including ranges ("1–2 tbsp"), fractions ("½ cup", "1 1/2 tsp"), "to taste" lines, and size words ("1 large onion": the size goes into the note).
- [x] `units.yaml` covers English units and abbreviations plus German and desi originals (EL, TL, Prise, Bund, Zehe, Msp., chammach, katori, pao, chutki) mapped to English Mealie unit names. The Unit Normalizer resolves to Catalog ids or flags `new`.
- [x] Sanity Checks are pure and table-tested, with limits in settings.
- [x] Step linking (pure): each step lists the `referenceId`s of ingredients whose Food name (or plural/alias) appears in it.
- [x] Pipeline-seam test: a recipe where the engines disagree on one line uploads with that line taken from the right engine, S3 lowers the score as configured, and an `unparsed` line sends the Recipe Part to review.
- [x] `report.csv` gains the number of lines per parse status and the suspicious-line count.

## Comments

**Built**

- `reconcile.py` (pure): per line, engine A (`ingredient-parser-nlp`) against engine B (the `llm_parse` the extraction call returns), giving `agreed`, `nlp_preferred` (one field differs and NLP's confidence for it is ≥ `parse.nlp_preferred_confidence`, default 0.9), `conflict` (LLM result used, flagged) or `unparsed` (no food from either engine: kept as a note line). Lines without an `llm_parse` (older extractions) are `nlp_only`. Table tests cover ranges, fractions, "to taste" and size words going to the note.
- `config/units.yaml` extended with English abbreviations plus German and desi originals (EL, TL, Prise, Bund, Zehe, Msp., chammach, katori, pao, chutki) mapped to English Mealie unit names. The Unit Normalizer resolves to Catalog ids or flags `new`.
- `sanity.py` (pure): quantity limits per unit, seasoning limits ("5 kg salt"), a unit used as the food, a liquid counted in pieces. Limits are in `ParseSettings` (`parse:` in settings). Findings go on `ParsedIngredient.suspicious`.
- Gate: S3 (parse agreement = share of compared lines that are `agreed`/`nlp_preferred`, `None` when nothing was compared) and S5 (share of lines with no sanity findings), weights 15 and 10. An `unparsed` line fails H4, so the Recipe Part goes to review.
- Step linking (pure, in the payload builder): each step's `ingredientReferences` lists the `referenceId`s of ingredients whose Food name, plural or alias appears in the step text.
- `report.csv` gains `lines_agreed`, `lines_nlp_preferred`, `lines_conflict`, `lines_unparsed` and `suspicious_lines` (empty for a Video with no Recipe Part yet; `nlp_only` lines are not counted in a column).
- `prompts/extract.md` rule 13 asks for `llm_parse` on every ingredient (the JSON schema already carries the field).
- Tests: two assertions in `tests/test_dual_engine_seam.py` were corrected because the test was wrong, not the behaviour. (1) The `unparsed` test looked the line up by its cleaned `line` ("salt, to taste"), but parsed records and H4 details use `original_line` ("Salt, to taste"), as Mealie's `originalText` does everywhere. (2) The step-link test searched for a step mentioning "mustard oil", but the fixture's step says only "the oil". It now checks that the cumin step links both "1/2 tsp cumin seeds" and "2 small onions" (Food name and plural). `tests/test_gate_seam.py` hand-computed scores were updated for S5 (95.2, 70.7, 85.7). `tests/test_batch_runs.py` now expects the five new report columns.

**Deferred**

- Step linking matches whole Food names and aliases only: "the oil" does not link to "mustard oil". A looser head-noun match would need care to avoid false links.
- German lines are reconciled on the English `line` only; `food_original` is used for Food matching, not for parsing.

**Manual verification (on the laptop)**

1. `uv sync`, then `uv run mp add <a YouTube recipe URL with a clear ingredient list>` and `uv run mp run`.
2. In Mealie, open the recipe: every ingredient has quantity, unit and Food set, and opening a step shows its linked ingredients.
3. `uv run mp report`, open `reports/report.csv`: the `lines_*` columns add up to the ingredient count (most lines `agreed`), `suspicious_lines` is 0 for a normal recipe.
4. Check the real `claude -p` extraction returns `llm_parse` per ingredient: in the State Store (or a `--dry-run` payload), lines show `parse_status` other than `nlp_only`.
5. Try a German recipe (EL/TL units) and a desi one (chammach, katori): units resolve to English Mealie units, not new ones.
