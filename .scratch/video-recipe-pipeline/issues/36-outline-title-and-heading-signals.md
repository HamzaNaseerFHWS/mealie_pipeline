# 36: Split more multi-recipe videos: more heading styles and the title as a signal

**What to build:** Ticket 12 only asks the model for an outline when the code sees a structural sign of several recipes: 2+ chapters, numbered caption headings (`1.`, `#1`, `Recipe 1`), or 2+ recipe names on the website. Videos without those uploaded as **one merged recipe** (for example "Budget Meal Prep: 5 Healthy Dinners, Beans, Chicken Soup, Tostadas, Fried Rice" and "Freezer Meals: Breakfast Burritos, ... and Lasagna"). `reports/possible_merged.csv` lists about 50 more candidates.

1. `_MARKER` in `outline.py` also accepts `Night 1`, `Day 1`, `Option 1`, `Part 1`, `Recipe #1`, `Meal 1`, `Number 1` headings (and German `Rezept 1`, `Tag 1`).
2. A new signal from the **title**: `N ways`, `vs`, `meal prep`, `freezer meals`, `recipes you need`, or a title with 3+ dish names separated by commas or `and`. It triggers the outline call (one `strong` call).
3. When the title signal fires but the outline finds no usable split (no chapters, no headings, no transcript), do **not** upload as one recipe: hold it for review with the reason "looks like several recipes, nothing to split on" (subtitles from ticket 34 may later give something to split on). If the Video has no usable text at all, ticket 39's link-only stub applies instead.
4. Re-processing: a command that resets the Videos listed in `reports/possible_merged.csv` so they are re-outlined. The user deletes the old merged recipes in Mealie.

**Blocked by:** None

**Status:** ready-for-agent

**Read first:** `src/mealie_pipeline/outline.py` (`detect_signals`, `_MARKER`), `pipeline.py` (`_outline`), ticket 12, `reports/possible_merged.csv`.

- [ ] Table tests for the new headings and the title signal, including titles that must **not** fire ("Pasta with Romanesco Broccoli and Spinach").
- [ ] Pipeline-seam test: a "NIGHT 1 / NIGHT 2" caption becomes two parts; a "Freezer Meals" title with a single-recipe page and no split goes to review.
- [ ] Real check: re-run the 4 known cases (Budget Meal Prep, Freezer Meals, Middle Eastern Feast, Japanese vs Korean Rice Bowl).

**Manual check (user):** delete the merged recipes from Mealie, reset them, re-run, and open the results.
