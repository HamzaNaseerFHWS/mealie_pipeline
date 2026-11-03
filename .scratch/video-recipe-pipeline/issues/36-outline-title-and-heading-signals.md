# 36: Split more multi-recipe videos: more heading styles and the title as a signal

**What to build:** Ticket 12 only asks the model for an outline when the code sees a structural sign of several recipes: 2+ chapters, numbered caption headings (`1.`, `#1`, `Recipe 1`), or 2+ recipe names on the website. Videos without those uploaded as **one merged recipe** (for example "Budget Meal Prep: 5 Healthy Dinners, Beans, Chicken Soup, Tostadas, Fried Rice" and "Freezer Meals: Breakfast Burritos, ... and Lasagna"). `reports/possible_merged.csv` lists about 50 more candidates.

1. `_MARKER` in `outline.py` also accepts `Night 1`, `Day 1`, `Option 1`, `Part 1`, `Recipe #1`, `Meal 1`, `Number 1` headings (and German `Rezept 1`, `Tag 1`).
2. A new signal from the **title**: `N ways`, `vs`, `meal prep`, `freezer meals`, `recipes you need`, or a title with 3+ dish names separated by commas or `and`. It triggers the outline call (one `strong` call).
3. When the title signal fires but the outline finds no usable split (no chapters, no headings, no transcript), do **not** upload as one recipe: hold it for review with the reason "looks like several recipes, nothing to split on" (subtitles from ticket 34 may later give something to split on). If the Video has no usable text at all, ticket 39's link-only stub applies instead.

**Blocked by:** None

**Status:** done

**Read first:** `src/mealie_pipeline/outline.py` (`detect_signals`, `_MARKER`), `pipeline.py` (`_outline`), ticket 12.

- [x] Table tests for the new headings and the title signal, including titles that must **not** fire ("Pasta with Romanesco Broccoli and Spinach").
- [x] Pipeline-seam test: a "NIGHT 1 / NIGHT 2" caption becomes two parts; a "Freezer Meals" title with a single-recipe page and no split goes to review.
- [ ] Real check: send the 4 known cases (Budget Meal Prep, Freezer Meals, Middle Eastern Feast, Japanese vs Korean Rice Bowl) through the pipeline one at a time.

**Manual check (user):** send one multi-recipe link and open the results in Mealie.

## Comments

**Built** (`outline.py`, `Pipeline._outline`):
- `_MARKER` also accepts word-numbered headings: `Night 1`, `Day 1`, `Option 1`, `Part 1`, `Recipe 1`, `Recipe #1`, `Meal 1`, `Number 1`, German `Rezept 1` and `Tag 1`. A bare `NIGHT 1` line with the recipe underneath counts as a heading.
- `title_signal(title)` (pure) fires on:
  - "meal prep", "freezer meals", "recipes you need", "vs"/"versus", or "N ways/recipes/dinners/...";
  - a list of 3+ short dish names with at least one comma ("Hummus, Falafel and Tabbouleh").

  Everything after " | " (the channel) is ignored. A list item containing "with/in/on/over/served/topped" means one dish, so "Pasta with Romanesco Broccoli and Spinach" and "Salmon with lemon, garlic butter sauce and ..." do not fire. It adds `title:<pattern>` to the signals, which triggers the one `strong` outline call.
- When the title is the only signal and the outline gives fewer than 2 parts (or none), the Video goes to **review** with "looks like several recipes, nothing to split on". It is never uploaded as one merged recipe.
- When the title is the only signal and the Video has no usable text and no website recipe, there is no outline call: it becomes one link-only stub (ticket 39).
- **Bug fixed on the way:** parts of a multi-recipe video without timestamps share one `orgURL`. The upload's "already uploaded?" lookup falls back to `orgURL` on Mealie v3.22 and found part 1 for part 2, so part 2 was recorded "(already in Mealie)" and never uploaded. A match whose `extras.item_key` names another part is now ignored.

**Known false positive:** "Salt, Pepper and Garlic Wings" fires the list rule. It costs one outline call, and the item goes to review if nothing splits.

**Not done here (needs the laptop):** sending the 4 known cases (Budget Meal Prep, Freezer Meals, Middle Eastern Feast, Japanese vs Korean Rice Bowl) through the real pipeline. `reports/possible_merged.csv` is not in the repo.

**Manual check (user):** send one multi-recipe link (for example the Budget Meal Prep video) and open the results in Mealie: one recipe per dish, or a REVIEW line saying "nothing to split on". For a recipe already uploaded merged, reset it (`uv run mp retry <video key> --stage outline`) and run again.
