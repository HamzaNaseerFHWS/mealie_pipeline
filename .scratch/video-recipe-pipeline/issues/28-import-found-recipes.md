# 28: Import the found recipes into Mealie

**What to build:** A `found` Recipe Request runs through the existing pipeline into Mealie. The chosen page is its only Source (`web`), so there's **no video, classification, transcription or outline**. Everything else is the same as for a Video: the extraction call normalizes the page's recipe, ingredients are parsed into English Foods and Units, tags are chosen from the existing list, the Gate verifies it, and the Uploader writes it.

**Details:**
- **Item Key:** `web:<short hash of the normalized page URL>#1`. The URL Normalizer gets a `web` platform for this.
- **Source and Evidence:** the page's recipe is the `web` Source, and Grounding checks quotes against it. The sheet's `name` and `notes` are context, never Evidence.
- **Language:** detected from the page (`inLanguage`, `<html lang>`, text). The English-ingredients and Roman Urdu/Hindi rules apply as for Videos once ticket 11 exists.
- **Mealie fields:**
  - `orgURL` = the page URL
  - `extras` = `{item_key, requested_name, request_row, source: "web-search", score, pipeline_version}`
  - If the page's recipe name differs from the requested name, the page's name is used. The requested name goes into `extras.requested_name` and a note.
- **Image:** the page's recipe image, through ticket 02's file → URL → `image_missing` chain.
- **Already in Mealie:** ticket 22's Existing Link Set is checked with the chosen page URL before any AI work. A match makes the request `already_in_mealie` with the existing link. There is no name-based matching (as decided in ticket 22).
- **Failures:** a request that fails the Gate goes to the Review Queue with the page and the extracted recipe side by side, and isn't uploaded.
- **Results:** `reports/requests.csv` gets the final status, Mealie link, Quality Score and reason for every row.

**Blocked by:** 27, 02, 08, 22

**Status:** done

**Read first:** `spec.md` modules 4 (URL Normalizer), 9–13 and 18; tickets 02, 08, 22, 26, 27; `docs/adr/0003`. Tickets 09, 10, 11 and 13 improve parsing, tagging, languages and usage when they're done, but this ticket doesn't wait for them.

- [x] The URL Normalizer supports `web` URLs: scheme, `www.`, trailing slash and tracking parameters normalized, with a stable short hash. Table-tested: the same page with and without `www`/`?utm_` gives one key.
- [x] The Stage Runner treats a Recipe Request as a work item that runs `find → extract → parse → tag → verify → upload` and skips the Video-only stages.
- [x] The extraction prompt for a web-sourced request keeps the page's quantities and wording and fills only gaps (the same instruction as ticket 06). A `FakeLLM` assertion checks this.
- [x] Pipeline-seam tests with `FakeWebSearch`, fixture pages, `FakeLLM` and `FakeMealie`:
  - (a) a 3-name sheet becomes 3 Mealie recipes with parsed ingredients, ≥ 1 existing tag, `orgURL` = the page, and `extras.requested_name`
  - (b) a page URL already in `FakeMealie` (with different tracking parameters) makes zero LLM calls and no write, and the row shows `already_in_mealie`
  - (c) a page failing the Gate goes to review and isn't uploaded
  - (d) re-running the sheet makes no new writes
  - (e) a row with a `url` column skips the search
- [x] `mp run` processes requests alongside Videos. `--limit`, `--dry-run` and `--stages` work for them, and `mp requests` shows final counts.
- [x] `reports/requests.csv` is complete and opens correctly in Excel.

**Manual check on the laptop (user):** first finish wayfinder ticket 13 (Mealie token + `check_mealie.py --write-test`). Then run `uv run mp run --limit 5 --dry-run` and look at the payloads in `work/`. Then run without `--dry-run` and open the recipes in Mealie.

## Comments

### Built (2026-10-26)

A plain `mp run` now takes a sheet of names all the way into Mealie: `find` (ticket 27) for pending requests, then every `found` request runs through `linkcheck -> scrape -> extract -> parse -> tag -> verify -> upload` and the request's status follows.

- **A request is a work item** (`request_import.py`): each `found` request becomes a Video-shaped item with platform `web`, Video Key `web:<hash>` and Item Key `web:<hash>#1` (the hash is of the normalized page URL, so `www.`, a trailing slash, `?utm_...` and `#fragment` all give one key; `normalize_web` in `url_normalizer.py`, table-tested). Its `metadata` stage is done from the start (no yt-dlp, no classification, transcription or outline), and `scrape` reads the chosen page as the only Source (`data/web/<hash>/web.json`). Everything after that is the existing code, so `--limit`, `--dry-run`, `--stages`, `retry`, `reset`, `--mode update` and the report work unchanged. Two cells that found the same page share one item and one recipe; both requests end `imported` with the same link.
- **Extraction:** the prompt carries `[SRC:web]` (the page's recipe) with the "keep the website's quantities and wording" rule, no `[SRC:desc]`, and the requested name and notes as context marked "never Evidence". Grounding checks quotes against the page text only.
- **Already in Mealie:** `linkcheck` runs before any fetch or LLM call, with the page URL normalized (ticket 22's Existing Link Set); a hit makes the request `already_in_mealie` with the existing link, no write. Upload checks again.
- **Mealie fields:** `orgURL` = the page URL; `extras` = `{item_key, requested_name, request_row (the cell, e.g. R2C1), source: "web-search" ("sheet-url" when the sheet gave the URL), score (the Quality Score), pipeline_version}`. When the page's recipe name differs from the requested name, the page's name is used and a note "Requested as ..." is added. Image: the page's own image through the file -> URL -> `image_missing` chain.
- **Outcome on the request** (updated at the end of every run, also after Ctrl+C): `imported` (link, Quality Score, "imported" or "imported with the To Review tag"), `already_in_mealie`, `review` (the Gate's reason; the review file is `review/web_<hash>_1.md` with the page and the extracted recipe), `failed` (stage and error; `mp retry <item_key>` then `mp run` re-does it) or `found`. `reports/requests.csv` has them all, and `mp requests` shows the counts.
- Store migration 5 adds `recipe_requests.item_key`.

### Notes

- A plain `mp run` also runs `find` when the workspace has requests (searches are read-only); `--limit` applies to it. With `--stages`, `find` runs only if listed. If every search source is down it says so, and the import of already-found requests still runs.
- Language handling for German and Urdu/Hindi pages waits for ticket 11, as the ticket says.
- A sheet-URL row has `source: "sheet-url"` in its extras (the ticket only names `web-search`).

### Manual verification on the laptop (user)

1. First finish wayfinder ticket 13: Mealie token in `.env` and `uv run python scripts/check_mealie.py --write-test`.
2. `uv sync`, `uv run mp doctor` (Mealie and `claude` green), `uv run mp requests add --file "<path>\food_list_kategorien.csv.csv"`.
3. Find pages for a few names: `uv run mp run --stages find --limit 10` (see ticket 27), check `reports/requests.csv`, fill any `choice` in `reports/request_choices.csv` and run it again.
4. Dry run on the found ones: `uv run mp run --limit 5 --dry-run`, then look at the payloads in `work/payloads/` (ingredients with units and foods, the page as `orgURL`, `extras.requested_name`).
5. Real import: `uv run mp run --limit 5`. Open the recipes in Mealie from `reports/requests.csv` (`mealie_url`): amounts, units and foods on each ingredient, at least one tag, the image, and the `To Review` tag on borderline ones. Look in `review/` for held-back ones.
6. Run `uv run mp run --limit 5` again: nothing new is written. Then drop `--limit` to do the rest (Ctrl+C stops between items; a Claude usage limit stops the run with a message; run again later).

### First real import on the laptop (2026-10-26)

French Toast, Avocado-Sandwich, then batches of 20 and 50 from `food_list_kategorien.csv.csv` (grid layout; ingredient-only columns "Prep / ...", "Proteins" and repeated names were removed from the State Store first, 379 -> 307 requests). 38 imported, 5 review, 7 failed, 16 waiting for a choice, 6 not found, 235 pending after the first 72 names.

- **Mealie v3.22.0 has no `extras` queryFilter** (`extras.key` / `extras.item_key` both give `400 ... does not exist on this schema`); the `org_url` filter works. `MealieHttpGateway.find_recipe` now tries the `extras` filter and falls back to `org_url`; `_upload` passes the page URL. Without a URL the item-key lookup finds nothing on such a Mealie. Wayfinder 13 never confirmed this; see its Comments.
- **Mealie timeout:** `GET /api/foods?perPage=-1` (1,945 foods) takes about 15 s, so the 20 s default sometimes fails with `ReadTimeout` in `extract`. Run with `MEALIE__TIMEOUT_SECONDS=60` (put it in `.env`).
- **Open problems found:**
  - Two `parse` crashes: `ValueError: could not convert string to float: 'half'` and `'3-#1$2-4'` (quantity text the parser cannot read). Not fixed; ticket 09 reworks parsing.
  - Three pages (two on bettybossi.ch) give "the extraction has no ingredients or no steps".
  - Short German names match the wrong page ("Tee" imported "Tee's Corn Pudding"). German and Urdu/Hindi handling waits for ticket 11.
  - German pages score lower (60-70, `To Review` tag); English and desi pages mostly 85-100.
- A `--limit N` on a plain `mp run` limits the find stage; the import then runs for every `found` request.

### Final state of the CSV import (2026-10-29)

271 of 307 names are in Mealie (plus 1 already there); 10 failed, 20 not found, 3 need a browser, 2 held for review.

- **Empty extractions were a scraper bug, not the German pages.** `recipe_extraction._get` returned the first matching key in the item's own order, so a `HowToStep` with `"name": "Step 1"` before `"text": ...` gave the steps "Step 1".."Step 6" and the model rightly found no method. `_get` now honours the order of the names asked for, and `_clean` decodes HTML entities (`&#190;` -> `3/4`). The 12 affected pages were re-scraped and imported.
- **Held German recipes** were fixed by ticket 30 (source food names as aliases): 14 uploaded, 2 stay in review (Lentil Bolognese has no method; the vegan sausages page is not the dish).
- **Still open:** 8 `parse` crashes on quantity text (`'few'`, `'half'`, `'1.5-2'`, `''`, `'3-#1$2-4'`: `NlpIngredientEngine` calls `float()` on a text amount), 2 "Recipe already exists" on upload, 3 pages that need a browser, 1 page that no longer holds one recipe.
