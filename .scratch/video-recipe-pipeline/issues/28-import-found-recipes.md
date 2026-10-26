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

**Status:** ready-for-agent

**Read first:** `spec.md` modules 4 (URL Normalizer), 9–13 and 18; tickets 02, 08, 22, 26, 27; `docs/adr/0003`. Tickets 09, 10, 11 and 13 improve parsing, tagging, languages and usage when they're done, but this ticket doesn't wait for them.

- [ ] The URL Normalizer supports `web` URLs: scheme, `www.`, trailing slash and tracking parameters normalized, with a stable short hash. Table-tested: the same page with and without `www`/`?utm_` gives one key.
- [ ] The Stage Runner treats a Recipe Request as a work item that runs `find → extract → parse → tag → verify → upload` and skips the Video-only stages.
- [ ] The extraction prompt for a web-sourced request keeps the page's quantities and wording and fills only gaps (the same instruction as ticket 06). A `FakeLLM` assertion checks this.
- [ ] Pipeline-seam tests with `FakeWebSearch`, fixture pages, `FakeLLM` and `FakeMealie`:
  - (a) a 3-name sheet becomes 3 Mealie recipes with parsed ingredients, ≥ 1 existing tag, `orgURL` = the page, and `extras.requested_name`
  - (b) a page URL already in `FakeMealie` (with different tracking parameters) makes zero LLM calls and no write, and the row shows `already_in_mealie`
  - (c) a page failing the Gate goes to review and isn't uploaded
  - (d) re-running the sheet makes no new writes
  - (e) a row with a `url` column skips the search
- [ ] `mp run` processes requests alongside Videos. `--limit`, `--dry-run` and `--stages` work for them, and `mp requests` shows final counts.
- [ ] `reports/requests.csv` is complete and opens correctly in Excel.

**Manual check on the laptop (user):** first finish wayfinder ticket 13 (Mealie token + `check_mealie.py --write-test`). Then run `uv run mp run --limit 5 --dry-run` and look at the payloads in `work/`. Then run without `--dry-run` and open the recipes in Mealie.
