# 09: Two ingredient parsers must agree

**What to build:** Upgrade the `parse` stage so every English Ingredient Line is parsed by two engines: engine A is `ingredient-parser-nlp`; engine B is the LLM parse that the extraction call already returns. They are reconciled per the rules in `PIPELINE_SPEC.md` §7:
- `agreed`: accept
- `nlp_preferred`: one field differs and NLP confidence for it is ≥ 0.9
- `conflict`: LLM result used, flagged
- `unparsed`: note-only line, sent to review

Add Sanity Checks (implausible quantity per unit, a unit used as the food, count units with liquids) and feed the parse agreement (S3) and sanity (S5) results into the verification score. Ingredients get linked to steps through `ingredientReferences`.

**Blocked by:** 08

**Status:** ready-for-agent

**Read first:** `spec.md` module 10 and the payload builder in module 13; `PIPELINE_SPEC.md` §7.

- [ ] Reconcile is pure and table-tested with hand-written cases for each outcome, including ranges ("1–2 tbsp"), fractions ("½ cup", "1 1/2 tsp"), "to taste" lines, and size words ("1 large onion": the size goes into the note).
- [ ] `units.yaml` covers English units and abbreviations plus German and desi originals (EL, TL, Prise, Bund, Zehe, Msp., chammach, katori, pao, chutki) mapped to English Mealie unit names. The Unit Normalizer resolves to Catalog ids or flags `new`.
- [ ] Sanity Checks are pure and table-tested, with limits in settings.
- [ ] Step linking (pure): each step lists the `referenceId`s of ingredients whose Food name (or plural/alias) appears in it.
- [ ] Pipeline-seam test: a recipe where the engines disagree on one line uploads with that line taken from the right engine, S3 lowers the score as configured, and an `unparsed` line sends the Recipe Part to review.
- [ ] `report.csv` gains the number of lines per parse status and the suspicious-line count.
