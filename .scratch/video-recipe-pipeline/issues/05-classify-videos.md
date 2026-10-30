# 05: Classify Videos: only real recipes continue

**What to build:** A `classify` stage that labels every collected Video as `recipe`, `recipe_partial`, `restaurant_or_place`, `ad_or_product`, `eating_or_review`, `not_food` or `uncertain`, with confidence and reasons. Only `recipe` and `recipe_partial` (drinks count as recipes) continue to later stages; the rest are `skipped` with their label.

How it works:
- Rule signals from `config/classify_rules.yaml` feed a batched `fast`-tier LLM call (about 20 Videos per call). Each Video gets its metadata first (the `metadata` stage, yt-dlp with no download).
- Uncertain or low-confidence Videos are escalated once with their subtitles if available. Transcript-based escalation is added in ticket 07.
- Everything is written to `reports/classification.csv` with an `override` column that always wins on the next run.
- `mp review classify` walks the uncertain ones in the terminal and records the user's choice as an override.

**Blocked by:** 04

**Status:** done

**Read first:** `spec.md` module 5; `PIPELINE_SPEC.md` §3.2; wayfinder ticket `05-what-counts-as-a-recipe.md`.

- [x] Signals are pure and table-tested:
  - Pro-recipe: "recipe", "ingredients", quantity+unit patterns, cooking verbs, "full recipe on…/link in bio", recipe hashtags; German and Urdu/Hindi equivalents ("Rezept", "Zutaten", "tarkeeb", "ajza").
  - Anti-recipe: 📍 or a location tag, addresses/opening hours, "menu", "reservation", city-eats hashtags, prices, "ad/sponsored/paid partnership/use code".
- [x] The classification prompt and schema return `{video_key, label, confidence, reasons[]}` per item. A batch whose response misses or duplicates keys is retried once, then the missing items become `uncertain`.
- [x] The confidence threshold (default 0.7) and batch size are settings.
- [x] Override semantics: a pipeline-seam test labels a Video `restaurant_or_place`. The user edits the CSV override to `recipe`, and the next run moves the Video on without calling the LLM for it again.
- [x] `mp review classify` is tested with simulated input: it shows title, Creator, caption excerpt and reasons, accepts a label key, and writes the override.
- [x] Skipped Videos appear in `reports/report.csv` with their label and never reach extract.

**Manual check on the laptop (user):** run `mp run --stages metadata,classify` on your synced list and skim `reports/classification.csv`. Calibration happens in ticket 20.

## Comments

**Built**
- `config/classify_rules.yaml`: pro-recipe and anti-recipe rule signals (English, German, Urdu/Hindi), loaded by `src/mealie_pipeline/classify.py`. Signals are pure and keep the text they matched (`tests/test_classify_signals.py`).
- `prompts/classify.md` and the `Classifier`: batched `fast`-tier call returning `{video_key, label, confidence, reasons[]}` per item. A batch missing or duplicating keys is retried once; still-missing Videos become `uncertain`.
- `classify` stage in `pipeline.py` right after `metadata`. `recipe` and `recipe_partial` get their Recipe Part and continue; anything else is `skipped` with `label (confidence): reason`. Uncertain or below-threshold Videos are escalated once with their subtitles (new `subtitles` method on the VideoSource, yt-dlp auto/manual subs, no download); if still unsure they are `skipped` as `uncertain`, wait for `mp review classify` or a CSV override, and never continue on their own. Recipe Requests (`platform == "web"`) bypass classify entirely.
- `reports/classification.csv` (one row per Video, override column preserved across runs). A valid override always wins and the LLM is not called for that Video again; an unknown override label is ignored with a warning.
- `mp review classify`: shows title, Creator, caption excerpt, label/confidence and reasons, takes a label key (`s` skips) and writes the override. Decided Videos are not shown again.
- `reports/report.csv` gained a `video_label` column so skipped Videos show their label.
- Settings under `classify:` (`confidence_threshold` 0.7, `batch_size` 20, `caption_chars`, `subtitle_chars`); store migration adds `videos.classification_json`.
- README: classify section, `mp review classify`, `video_label` column.

**Tests:** `tests/test_classify_signals.py`, `tests/test_classify_seam.py` (override, escalation, retry of missing/duplicated keys, batching, failure + retry, review with simulated input, Recipe Requests pass through); existing pipeline-seam tests updated for the new stage. `World.invoke` in `tests/test_pipeline_seam.py` now accepts `input=` for terminal prompts.

**Deferred**
- Transcript-based escalation: ticket 07.
- Threshold/rule calibration on the real list: ticket 20.

**Manual verification on the laptop**
1. `uv run mp run --stages metadata,classify` on your synced list.
2. Open `reports/classification.csv`: skim labels, confidences and reasons; spot-check a few restaurants/ads and a few real recipes.
3. Put `recipe` in the `override` column of one wrongly skipped Video, run `uv run mp run --stages metadata,classify` again, and check it is now `done` (no new Claude call for it).
4. `uv run mp review classify`: walk a couple of uncertain Videos and confirm the choice lands in the CSV.
5. `uv run mp report` and check `video_label` in `reports/report.csv`.
