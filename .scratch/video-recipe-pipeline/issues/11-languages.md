# 11: Script check for Urdu/Hindi and ingredient lines

**What to build:** A pure check on each extraction: the name, description and steps of an Urdu/Hindi recipe must be in Roman letters (no Devanagari or Arabic script), and every Ingredient Line must be English script. A violation triggers one extraction retry with the problem stated, then the recipe goes to review (`NeedsReview`).

Scope cut (user decision): the language detector and the glossary files are dropped. The extract prompt already handles language, and German aliases were done in ticket 30.

**Blocked by:** None

**Status:** done

- [x] `script_problems(recipe)` is pure and table-tested (`src/mealie_pipeline/script_check.py`, `tests/test_script_check.py`).
- [x] Pipeline-seam tests: a Devanagari name is retried once with the problem in the prompt and the retry uploads; a second failure goes to review and uploads nothing.

## Comments

**Built:** the check, wired into `_run_extraction` in `pipeline.py` (one retry at the same tier, then `NeedsReview` "wrong script after one retry").

**Not checked:** German or other non-English words written in Latin letters inside an Ingredient Line. Only script is checked.

**Manual check (user):** import one Urdu/Hindi video and check the steps are in Roman letters.
