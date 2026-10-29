# 05: Classify Videos: only real recipes continue

**What to build:** A `classify` stage that labels every collected Video as `recipe`, `recipe_partial`, `restaurant_or_place`, `ad_or_product`, `eating_or_review`, `not_food` or `uncertain`, with confidence and reasons. Only `recipe` and `recipe_partial` (drinks count as recipes) continue to later stages; the rest are `skipped` with their label.

How it works:
- Rule signals from `config/classify_rules.yaml` feed a batched `fast`-tier LLM call (about 20 Videos per call). Each Video gets its metadata first (the `metadata` stage, yt-dlp with no download).
- Uncertain or low-confidence Videos are escalated once with their subtitles if available. Transcript-based escalation is added in ticket 07.
- Everything is written to `reports/classification.csv` with an `override` column that always wins on the next run.
- `mp review classify` walks the uncertain ones in the terminal and records the user's choice as an override.

**Blocked by:** 04

**Status:** in-progress

**Read first:** `spec.md` module 5; `PIPELINE_SPEC.md` §3.2; wayfinder ticket `05-what-counts-as-a-recipe.md`.

- [ ] Signals are pure and table-tested:
  - Pro-recipe: "recipe", "ingredients", quantity+unit patterns, cooking verbs, "full recipe on…/link in bio", recipe hashtags; German and Urdu/Hindi equivalents ("Rezept", "Zutaten", "tarkeeb", "ajza").
  - Anti-recipe: 📍 or a location tag, addresses/opening hours, "menu", "reservation", city-eats hashtags, prices, "ad/sponsored/paid partnership/use code".
- [ ] The classification prompt and schema return `{video_key, label, confidence, reasons[]}` per item. A batch whose response misses or duplicates keys is retried once, then the missing items become `uncertain`.
- [ ] The confidence threshold (default 0.7) and batch size are settings.
- [ ] Override semantics: a pipeline-seam test labels a Video `restaurant_or_place`. The user edits the CSV override to `recipe`, and the next run moves the Video on without calling the LLM for it again.
- [ ] `mp review classify` is tested with simulated input: it shows title, Creator, caption excerpt and reasons, accepts a label key, and writes the override.
- [ ] Skipped Videos appear in `reports/report.csv` with their label and never reach extract.

**Manual check on the laptop (user):** run `mp run --stages metadata,classify` on your synced list and skim `reports/classification.csv`. Calibration happens in ticket 20.
