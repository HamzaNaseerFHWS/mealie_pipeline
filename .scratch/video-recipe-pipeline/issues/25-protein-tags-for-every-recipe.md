# 25: Give every recipe in Mealie a protein tag

**What to build:** A command that goes through **every recipe in Mealie**, including the user's earlier manual and Mealie-import recipes, not only the pipeline's own. It works out each recipe's main protein(s) and adds the matching **Protein Tag** where the recipe doesn't have it yet. The same detection then becomes a Rule Tag in the pipeline's tagger (ticket 10), so every newly uploaded recipe gets its protein tag automatically, including in Auto Sync.

**Protein Tags** are a fixed, user-approved list in `config/protein_tags.yaml`. Each entry maps one tag name to the food words that count as that protein: English names plus German and desi names, so it works on old imports whose ingredients are unparsed text. The starter list to propose (final names are confirmed in wayfinder 20):

| Tag | Matches (examples) |
|---|---|
| Chicken | chicken, murgh, Hähnchen, Huhn |
| Beef | beef, steak, ground beef, Rind, Rinderhack, gai ka gosht |
| Lamb & Mutton | lamb, mutton, goat, bakra, gosht (when not beef/chicken), Lamm |
| Fish | fish, salmon, tuna, cod, tilapia, machli, Fisch, Lachs |
| Seafood | shrimp, prawn, jhinga, crab, squid, mussels, Garnelen |
| Turkey | turkey, Pute |
| Pork | pork, bacon, ham, Schwein, Speck |
| Egg | egg, anda, Ei/Eier |
| Tofu | tofu, tempeh, Seitan (configurable) |
| Paneer | paneer |
| Cheese | cheese, halloumi, mozzarella, cheddar, Käse (incl. "grilled cheese") |
| Lentils | lentil, dal/daal, masoor, moong, urad, chana dal, Linsen |
| Beans | beans, rajma, lobia, kidney/black/white beans, Bohnen |
| Chickpeas | chickpeas, chana, chole, garbanzo, hummus base, Kichererbsen |
| Soy chunks | soya chunks, TVP |

**How detection works** (pure, deterministic, no LLM by default):
1. **Gather text per recipe:**
   - **Pipeline recipes (parsed ingredients):** the linked Food names.
   - **Older imports (unparsed):** each ingredient's `note`, `originalText` and `display`.
   - **All recipes:** the recipe name.
2. **Find candidates:** match the words against `protein_tags.yaml` (whole words, case-insensitive, plurals and simple inflections).
3. **Keep only main proteins:**
   - A protein named in the **recipe name** always counts ("Grilled Cheese", "Chana Masala").
   - Lines marked optional, for garnish or "to serve" don't count.
   - Egg, Cheese and other dairy-type proteins don't count when the recipe is a dessert/baked good (by existing tags such as Dessert, Cake, or by name), unless they're in the name. That way 2 eggs in a cake don't tag it Egg.
   - Specific beats generic: "chicken stock" / "chicken bouillon" / "fish sauce" are flavourings, not proteins. There's a configurable exclusion list.
4. **Several proteins** give several tags (chicken + chickpeas curry gets both). No protein gives no protein tag; that's fine for desserts, drinks and most sides.
5. **Optional `--llm-check`:** a batched `fast`-tier call (through `LLMBackend`) for recipes that have no candidate, or more than 3, or whose ingredients are all unparsed. It can only pick from the Protein Tag list. Off by default.

**How the command behaves:**
- `mp tags protein` is a **dry run** by default. It writes `reports/protein_tags.csv` (one row per recipe: slug, name, link, current tags, proposed protein tags, the words that triggered each one, and an `override` column the user can edit to add, remove or block). Nothing in Mealie changes.
- `mp tags protein --apply` makes the changes:
  1. It creates any Protein Tag missing from Mealie. This is the one approved exception to "the pipeline only creates `To Review`", limited to the names in `protein_tags.yaml`, with case-insensitive matching against existing tags so `chicken` never duplicates `Chicken`.
  2. It then PATCHes each recipe whose proposed set isn't already present. PATCH replaces the tag list, so the payload is the recipe's **current tags plus the new ones**. It never removes or replaces an existing tag.
- Overrides in the CSV always win and are kept across re-runs.
- Idempotent: a second `--apply` makes no writes.
- Locked recipes (`settings.locked`) and failed PATCHes are skipped and listed in the report. One failure never stops the run.

**Blocked by:** 01

**Status:** done

**Read first:** `spec.md` modules 3 (`MealieGateway`) and 11 (Tagger); ticket 10; wayfinder ticket 20 (tag taxonomy). The protein list is part of its "ingredient types" dimension. Ticket 01's Comments cover the live-instance findings (v3.22.0, case-insensitive catalog names).

- [ ] `MealieGateway` can list all recipe summaries and get a full recipe (tags, ingredients, settings). Both are covered in the shared contract suite and by `FakeMealie`.
- [ ] Protein detection is pure and table-tested with hand-written recipes:
  - (a) parsed "chicken thighs" → Chicken
  - (b) an old import with note-only "500g boneless murgh" → Chicken
  - (c) "Grilled Cheese Sandwich" → Cheese
  - (d) "Chana Masala" → Chickpeas
  - (e) "Dal Tadka" → Lentils
  - (f) "Rajma Chawal" → Beans
  - (g) a chocolate cake with 3 eggs and butter → none
  - (h) chicken stock in a vegetable soup → none
  - (i) chicken and chickpea curry → Chicken + Chickpeas
  - (j) "Paneer Tikka" → Paneer, and not Cheese unless configured
  - (k) a German "Linsensuppe mit Würstchen" → Lentils + Pork (sausage per config)
  - (l) a drink → none
- [ ] The tag-name match against Mealie is case-, space- and punctuation-insensitive (it reuses ticket 10's matcher once that exists; until then the same rule lives in one shared helper). Missing Protein Tags are created exactly once.
- [ ] Pipeline-seam tests with `FakeMealie` holding a mix of pipeline and older recipes:
  - The dry run writes the CSV and makes zero writes.
  - `--apply` adds tags while every existing tag is preserved.
  - A second `--apply` makes zero writes.
  - An override removing a proposed tag is respected.
  - A locked recipe is skipped and reported.
- [ ] `--llm-check` sends only ambiguous recipes, in batches, and can only return names from the list (enum). It's tested via `FakeLLM`'s call log.
- [ ] Ticket 10's Rule Tags use this same detection, so new uploads get their Protein Tag. If ticket 10 is already done when this lands, wire it in here; otherwise ticket 10 does it. A pipeline-seam test confirms that a newly uploaded chicken recipe carries the Chicken tag.
- [ ] `mp status` / the run summary shows how many recipes gained a Protein Tag.

**Manual check on the laptop (user):** run `uv run mp tags protein` and look through `reports/protein_tags.csv`. Fix any rows with the `override` column. Once wayfinder 20 has confirmed the tag names, run `uv run mp tags protein --apply` and spot-check a few recipes in Mealie.

## Comments

**Built**

- `config/protein_tags.yaml`: the starter Protein Tag list from the table above (15 tags), with English, German and desi words per tag, an `exclude` list (stock, broth, fish sauce, green beans, egg noodles, besan, ...), `not_main` markers (optional, garnish, to serve, zum Garnieren, ...) and a `sweet` section (dessert/baking/drink tags and name words; Egg, Cheese and Paneer don't count there unless named). Words ending in `*` match German compounds by their stem (`hähnchen*`, `linsen*`). The longest phrase wins, so "chana dal" is Lentils and "goat cheese" is Cheese.
- `src/mealie_pipeline/protein.py` (pure): `detect(RecipeText, ProteinRules) -> {tag: [trigger words]}`, `mealie_recipe_text(recipe)` (linked Food names, plus `note`/`originalText`/`display` for unparsed imports, plus the name and existing tags), and `tag_key()`, the one shared case-, space- and punctuation-insensitive tag-name rule (ticket 10 should reuse it).
- `src/mealie_pipeline/protein_backfill.py` + `mp tags protein [--apply] [--llm-check]`:
  - dry run by default: writes `reports/protein_tags.csv` (slug, name, link, current tags, proposed tags, triggers, override, result). Nothing in Mealie changes.
  - `--apply` creates only the Protein Tags some recipe needs and Mealie lacks (matched by `tag_key`, so an existing `chicken` is reused, never duplicated), each once, then PATCHes `{"tags": current + new}`. It never removes a tag and never PUTs.
  - Overrides: `-Lentils` removes, `+Egg` (or plain `Egg`) adds, `block` means no Protein Tag; separate entries with `,` or `;`. Only names from the list are accepted; others are noted in `result`. Overrides are read back and kept on every run.
  - Locked recipes (`settings.locked`) are skipped and listed; a failed read or PATCH is listed and the run goes on (exit code 1 when anything failed). A second `--apply` makes no writes.
  - `--llm-check`: recipes with no candidate, more than 3, or only unparsed ingredients go to the `fast` tier in batches of 20 (`prompts/protein_tags.md`). The schema's `tags` is an enum of the list, and answers are filtered to listed names again. They replace the rule's guess (`triggers` says `llm`), and overrides still win.
  - Applied changes are appended to `reports/protein_tags_applied.csv`. `mp status` shows "Protein Tags: N recipes gained one", and the command prints how many recipes gained (or would gain) a tag.
- Tag stage: `_choose_tags` now adds the detected Protein Tags (Rule Tags, always kept within the 6-tag cap) when the tag already exists in Mealie. LLM tag matching uses `tag_key`. The tag stage never creates Protein Tags; the backfill does.
- `FakeMealie` recipes now carry `settings.locked` like real Mealie, covered by a new shared contract test (fake, HTTP shape, opt-in live).

**Tests:** `tests/test_protein_pure.py` (cases a–l from the ticket plus exclusions, optional lines, dessert tags, compounds and the tag-name rule) and `tests/test_protein_tags_seam.py` (dry run with zero writes, apply keeps existing tags, tags created once, second apply zero writes, remove/add/block overrides kept, locked skipped, failed PATCH doesn't stop the run, `--llm-check` batching/enum through `FakeLLM`'s call log, `mp status`, a new upload carrying `Chicken`).

**Deferred / notes**

- Ticket 10 (full tagging) isn't done yet. When it lands, it should move this into its Rule Tags and contradiction logic and keep using `protein.detect` and `tag_key`.
- Tag names are still the starter list until wayfinder 20 confirms them. If names change, edit `config/protein_tags.yaml` before the first `--apply`.
- New pipeline uploads only get a Protein Tag that already exists in Mealie, so run the backfill `--apply` once to create the tags.

**Manual check on the laptop**

1. Dry run against the real Mealie: `uv run mp tags protein`. It should list every recipe and change nothing. Open `reports/protein_tags.csv` and look through `proposed_tags` and `triggers`, especially old imports, desserts (no Egg/Cheese), soups with stock (no Chicken) and desi dishes.
2. Fix wrong rows in the `override` column (`-Tag`, `+Tag`, `block`) and save. Re-run the dry run: the overrides stay and `result` reflects them. For words that are wrong for many recipes, edit `config/protein_tags.yaml` instead.
3. Optional: `uv run mp tags protein --llm-check` and check the rows whose `triggers` say `llm`.
4. Once wayfinder 20 has confirmed the names: `uv run mp tags protein --apply`. Check "created tags" in the output (only names from the list), then spot-check 3–4 recipes in Mealie: their old tags are still there, plus the Protein Tag(s).
5. Run `uv run mp tags protein --apply` again: "0 recipes gained a Protein Tag", and nothing changes. `uv run mp status` shows the Protein Tags count.
6. Optional: `uv run pytest -m mealie_live -k locked` with `MEALIE_IT_URL`/`MEALIE_IT_TOKEN` set, to confirm that real recipes carry `settings.locked`.
