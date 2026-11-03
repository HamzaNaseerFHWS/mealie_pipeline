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
10. `29-parallel-workers` (optional speedup, can be done any time after 28): `mp run --workers N` for the slow stages. Do it before the big import of the remaining names if you want it faster; the later phase numbers below are unchanged.

**Before the first real upload** (the user, on the laptop): finish wayfinder ticket `13-run-mealie-api-check` (token, `check_mealie.py --write-test`). Then run ticket 28's manual check, starting with `--dry-run` and a small `--limit`.

## Phase B: make those recipes better (re-run them in place)

10. `09-dual-engine-ingredient-parsing`
10b. `30-german-food-aliases` (done): German food names become aliases of the English Foods; fixes the German recipes' low S2 score
11. `25-protein-tags-for-every-recipe`: also backfills protein tags on everything already in Mealie
12. `10-full-tagging`
13. ~~`13-claude-pro-usage-governor`~~ (dropped: videos run one at a time)

After Phase B, re-run the list's recipes so they pick up the better parsing and tags: `mp reset parse` then `mp run --mode update`, as in ticket 03. Once wayfinder 20 (tag taxonomy) is decided, re-tag them the same way.

## Phase C: social-media pipeline

14. `04-youtube-saved-lists`
15. `05-classify-videos`
17. `11-languages` (done): script check only
18. `12-multi-recipe-videos`
19. `14-pipeline-chrome-profile-and-login`
20. `17-link-in-bio-and-creator-websites`
21. ~~`15-instagram-saved-collector`~~ (dropped: ticket 35 export import) (needs wayfinder 15)
22. ~~`16-facebook-saved-collector`~~ (dropped: ticket 35 export import) (needs wayfinder 16)
23. `18-dedupe-and-existing-recipes`
24. ~~`19-first-real-run-on-the-laptop`~~ (dropped: real runs already happen) (with the user)
25. ~~`20-calibrate-the-classifier`~~ (dropped: classification already done)
26. ~~`21-full-run`~~ (dropped: Telegram inbox replaces it)
27. ~~`23-auto-sync-cycle`~~ (dropped: Telegram inbox replaces it)
28. ~~`24-schedule-auto-sync`~~ (dropped: Telegram inbox replaces it)

## Phase D: run it on the Mealie PC, and close the gaps found in the first real runs

29. `35-instagram-facebook-export-import` (done): saved Instagram/Facebook posts from the data exports; replaces the live collectors (15, 16) for this user
30. `38-mealie-timeouts-and-hangs`: a silent Mealie must not hang a run
31. `37-upload-name-clash`: "Recipe already exists" upload failures
32. `36-outline-title-and-heading-signals`: stop uploading multi-recipe videos as one recipe
33. `34-captions-and-cloud-transcription`: YouTube (and Facebook/Instagram if available) subtitles as a Source; no audio transcription
33b. `39-ingredients-only-and-link-only-recipes`: ingredients-only captions become real recipes; videos with no usable text become link-only stubs (name, thumbnail, link, tags). Do it before 33 so the inbox bot never reports "needs transcription".
34. `33-inbox-drain-worker`: Telegram links run through the pipeline and the bot reports back
35. `31-pipeline-docker-image-and-compose`: separate compose project with the inbox bot and the pipeline (Mealie's compose stays untouched)
36. `32-claude-login-in-container`: spike with the user; do it right after 31, because the Docker plan depends on it
