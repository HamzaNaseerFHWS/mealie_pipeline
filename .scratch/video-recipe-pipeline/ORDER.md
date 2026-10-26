# Build order

Agents take tickets in **this order**, not by ticket number. Pick the first ticket in the list whose `Status:` is `ready-for-agent` (or `ready-for-human`, when you're working with the user) and whose `Blocked by:` tickets are all finished. Skip any whose blockers aren't finished yet, and take the next one.

The user wants the recipes from their **CSV/Excel list of recipe names** in Mealie first, so they can start meal planning before the social-media pipeline exists. Phase A delivers exactly that and nothing more.

## Phase A: recipe-name list → Mealie (do this first)

1. `01-doctor-and-mealie-gateway`: settings, `mp doctor`, Mealie gateway + fake
2. `02-import-one-youtube-video`: State Store, `claude -p` backend, extract → parse → tag → upload path (the end-to-end skeleton the list import reuses)
3. `03-resumable-batch-runs`: batches, status, retry, report
4. `26-import-recipe-name-list`: read the CSV/XLSX into Recipe Requests
5. `06-recipe-website-scraping`: polite fetching + structured recipe extraction from pages
6. `27-find-recipe-page-by-name`: search each name, pick the right page, ask when unsure
7. `08-verification-gate`: Grounding, Quality Score, Review Queue
8. `22-skip-recipes-already-in-mealie`: Existing Link Set (builds the URL Normalizer if ticket 04 hasn't)
9. `28-import-found-recipes`: found pages through the pipeline into Mealie

**Before the first real upload** (the user, on the laptop): finish wayfinder ticket `13-run-mealie-api-check` (token, `check_mealie.py --write-test`). Then run ticket 28's manual check, starting with `--dry-run` and a small `--limit`.

## Phase B: make those recipes better (re-run them in place)

10. `09-dual-engine-ingredient-parsing`
11. `25-protein-tags-for-every-recipe`: also backfills protein tags on everything already in Mealie
12. `10-full-tagging`
13. `13-claude-pro-usage-governor`: needs wayfinder 18. Move it earlier, right after 03, if the sheet has more than about 30 names, so a Pro usage limit pauses the run instead of failing items.

After Phase B, re-run the list's recipes so they pick up the better parsing and tags: `mp reset parse` then `mp run --mode update`, as in ticket 03. Once wayfinder 20 (tag taxonomy) is decided, re-tag them the same way.

## Phase C: social-media pipeline

14. `04-youtube-saved-lists`
15. `05-classify-videos`
16. `07-local-transcription` (needs wayfinder 17)
17. `11-languages`
18. `12-multi-recipe-videos`
19. `14-pipeline-chrome-profile-and-login`
20. `17-link-in-bio-and-creator-websites`
21. `15-instagram-saved-collector` (needs wayfinder 15)
22. `16-facebook-saved-collector` (needs wayfinder 16)
23. `18-dedupe-and-existing-recipes`
24. `19-first-real-run-on-the-laptop` (with the user)
25. `20-calibrate-the-classifier` (with the user)
26. `21-full-run`
27. `23-auto-sync-cycle`
28. `24-schedule-auto-sync`

Research tickets (wayfinder 15–18) can run any time in parallel. They only write findings, and Phase C needs them.
