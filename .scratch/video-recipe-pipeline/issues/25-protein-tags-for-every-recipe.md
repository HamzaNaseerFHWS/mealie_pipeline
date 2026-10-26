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

**Status:** ready-for-agent

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
