# Spec: Video Recipe Pipeline

Status: ready-for-agent
Source: wayfinder map `.scratch/wayfinder-video-recipes/map.md`. Design reference: `PIPELINE_SPEC.md` (research, API details, rationale). Vocabulary: `GLOSSARY.md`. Decisions: `docs/adr/0001`–`0006`.

## Problem Statement

The user has about 900 cooking Videos saved across YouTube playlists, Instagram saved "All posts" and Facebook saved items. Mealie's built-in import does a poor job on them: ingredients come in as unparsed text, so quantities, foods and shopping lists don't work; tags are often missing; transcripts are weak; recipes written on the Creator's website are ignored; and restaurant ads or travel clips get imported like recipes. Doing it by hand for hundreds of Videos isn't realistic. The recipes are in English, German and Urdu/Hindi, and some Videos contain several recipes.

## Solution

A command-line pipeline (`mp`) that runs on the user's Windows laptop. The user points it at Saved Lists. It enumerates every Video, keeps only real recipe Videos, gathers the best Sources (Recipe Website first, then description, pinned comment, subtitles, then its own local transcript), and has Claude (through the user's Claude Pro subscription) extract each Recipe Part with Evidence for every ingredient and step. It parses ingredients into English Foods and Units, tags each recipe with at least one existing Mealie tag, verifies everything against the Sources, and uploads only recipes that pass the Gate to Mealie over Tailscale. Everything is resumable, re-runnable per stage, and leaves a report plus a Review Queue for anything uncertain. Multi-recipe Videos become several independent Mealie recipes.

## User Stories

### Setup and health

1. As the user, I want one command that checks my setup (Python, ffmpeg, GPU/CUDA, Claude CLI login, Playwright Chrome, yt-dlp version, Mealie reachability and token), so that I know what's broken before a long run.
2. As the user, I want to put my Mealie URL and token in a `.env` file, so that secrets stay out of the repo.
3. As the user, I want the pipeline to tell me plainly when the Mealie PC is unreachable (Tailscale down), so that I don't think recipes were lost.
4. As the user, I want a benchmark command that tries the Whisper model ladder on my GTX 1650 with English, German and Urdu/Hindi samples, so that the best model that fits is chosen with evidence.
5. As the user, I want to log in once to YouTube, Instagram and Facebook in a visible Chrome window that the pipeline owns, so that my everyday Chrome profile and passwords are never touched.
6. As the user, I want the pipeline to stop and tell me when a platform asks for a checkpoint or captcha, so that my account isn't put at risk.

### Collecting

7. As the user, I want to register a Saved List by pasting its URL, so that I don't have to list Videos by hand.
8. As the user, I want YouTube playlists, Watch Later and Liked to work, so that all my YouTube saves are covered.
9. As the user, I want my Instagram saved "All posts" collected, so that every saved reel and post is covered.
10. As the user, I want my Facebook saved items and collections collected, so that saved reels and videos are covered.
11. As the user, I want to add single Video URLs or a text file of URLs, so that I can import things outside my lists.
12. As the user, I want to re-sync my Saved Lists later and only process new Videos, so that I can keep saving and re-run.
13. As the user, I want tracking parameters and short links normalized, so that the same Video saved twice is processed once.
14. As the user, I want collection to go at a human pace with a per-session cap, so that platforms don't flag my account.

### Classifying

15. As the user, I want every Video labelled recipe / partial recipe / restaurant or place / ad or product / eating or review / not food / uncertain, so that only real recipes are processed.
16. As the user, I want drinks and cocktails treated as recipes, so that they're imported too.
17. As the user, I want the classifier to use cheap metadata first and only look at subtitles or the first 60 s of audio when unsure, so that it's fast and cheap.
18. As the user, I want a classification CSV with label, confidence, reasons and an override column that always wins, so that I stay in control.
19. As the user, I want a terminal review command for uncertain Videos, so that I can decide quickly.
20. As the user, I want to measure classifier accuracy on a hand-labelled sample before the full run, so that I can trust it.

### Sources

21. As the user, I want the recipe on the Creator's website to be used when a Video links to one, so that I get the creator's exact quantities.
22. As the user, I want short links and link-in-bio pages followed to find the recipe page, so that "link in bio" Videos still get their website recipe.
23. As the user, I want the Creator's website remembered and searched by Video title when a Video has no direct link, so that more recipes are found.
24. As the user, I want the creator's pinned comment read, because many creators post the recipe there.
25. As the user, I want subtitles used when they exist, and local transcription only when needed, so that time and GPU are saved.
26. As the user, I want transcription to stay correct on music-heavy reels (vocabulary prompt, audio clean-up, VAD), so that ingredient names aren't garbled.
27. As the user, I want Videos with no speech and no usable caption sent to review as `needs_ocr`, so that they're not imported as empty recipes.

### Extracting

28. As the user, I want every ingredient and step to cite a verbatim quote from a Source, so that nothing is invented.
29. As the user, I want unstated quantities written as "to taste" rather than guessed, so that recipes stay honest.
30. As the user, I want ingredient Sections ("For the sauce") kept, so that recipes read like the original.
31. As the user, I want a Video containing several recipes split into separate, independent Mealie recipes, so that each dish can be found, planned and shopped on its own.
32. As the user, I want a sub-component used inside a dish kept as a Section, not split off, so that recipes aren't fragmented.
33. As the user, I want English and German recipe text kept in its language and Urdu/Hindi recipe text written in Roman Urdu/Hindi, so that I can read them the way I'm used to.
34. As the user, I want all ingredients in English whatever the recipe language, so that my food list and shopping list stay one English list.
35. As the user, I want desi ingredient names mapped to English with a glossary I can edit, so that "haldi" becomes "turmeric" every time.

### Parsing and tagging

36. As the user, I want every ingredient split into quantity, unit, food and note and linked to Mealie Foods and Units, so that scaling and shopping lists work.
37. As the user, I want two independent parsers to agree, and disagreements flagged, so that parsing errors are caught.
38. As the user, I want missing English Foods and Units created automatically and logged, so that nothing is left unparsed.
39. As the user, I want implausible quantities flagged ("5 kg salt"), so that extraction mistakes are caught.
40. As the user, I want each recipe to get at least one of my existing tags, chosen from the full tag list, so that my collection stays organized.
41. As the user, I want rule-based tags (vegetarian, quick, drinks…) derived from the parsed data, and contradictions removed, so that tags are trustworthy.
42. As the user, I want new tag ideas written to a CSV instead of created, so that my tag list doesn't sprawl.

### Verifying and uploading

43. As the user, I want each Recipe Part to get a Quality Score from hard and soft checks, so that only good recipes reach Mealie.
44. As the user, I want failing recipes retried once with the problems fed back, then held in a Review Queue with sources side by side, so that I can fix them quickly.
45. As the user, I want borderline recipes uploaded with a `To Review` tag, so that I can find them in Mealie.
46. As the user, I want each uploaded recipe to carry its source URL (timestamped for multi-recipe Videos), image and pipeline metadata, so that I can trace it back.
47. As the user, I want the pipeline to read every uploaded recipe back and compare it, so that silent upload errors are caught.
48. As the user, I want re-runs not to create duplicates, so that I can run the pipeline as often as I like.
49. As the user, I want the same recipe saved on several platforms to become one Mealie recipe, so that my collection has no duplicates.
49a. As the user, I want recipes I already imported into Mealie earlier (by hand or with Mealie's import, matched by their original link or by name + ingredients) never uploaded again, so that my old Instagram imports don't get duplicated.
49b. As the user, I want the option to upgrade those old, badly parsed imports in place instead, so that I keep their ratings and comments but get parsed ingredients.

### Running

50. As the user, I want every stage resumable and re-runnable on its own, so that a crash, sleep, or usage limit loses nothing.
51. As the user, I want the run to pause automatically when my Claude Pro limit is hit and continue after reset, so that it can run unattended for days.
52. As the user, I want to restrict AI calls to hours I choose, so that the pipeline doesn't eat my daytime Claude usage.
53. As the user, I want OpenAI used only if I pass a flag, with a hard spend cap, so that my credits are safe.
54. As the user, I want a status command and a CSV/HTML report per run, so that I can see progress and problems.
55. As the user, I want to run in dry-run mode that writes the final payloads without touching Mealie, so that I can inspect results first.

## Implementation Decisions

### Platform and tooling

- Python 3.12 on native Windows, managed with `uv`. Single package `mealie_pipeline` with a `typer` CLI entry point `mp`. Lint/format with `ruff`, type-check with `pyright` (basic mode), test with `pytest`.
- All file I/O uses explicit UTF-8. Subprocesses are called with `encoding="utf-8"` and argument lists (never shell strings). Paths use `pathlib`.
- Dependencies: `httpx`, `pydantic` v2 + `pydantic-settings`, `typer`, `rich`, `yt-dlp` (+ `curl_cffi` for impersonation), `playwright` (Chrome channel), `extruct`, `recipe-scrapers`, `selectolax`, `trafilatura`, `faster-whisper`, `ingredient-parser-nlp`, `rapidfuzz`, `pyyaml`. Test-only: `pytest`, `pytest-httpserver` (or `respx`), `freezegun` (or an injected clock).
- `ffmpeg` must be on PATH (`winget install Gyan.FFmpeg`); `mp doctor` checks it.

### Workspace and configuration

- A **workspace** directory holds `pipeline.db` (SQLite), `data/<platform>/<video_id>/` artifacts, `work/` scratch, `reports/` and `review/`. Default is the repo root; `--workspace` overrides it.
- Settings come from `config/settings.yaml` (thresholds, pacing, models, languages, feature switches), overridable by environment variables and `.env`. Secrets live only in `.env`: `MEALIE_URL`, `MEALIE_TOKEN`, `OPENAI_API_KEY`, `OPENAI_MAX_USD`.
- Editable data files in `config/`: `tag_rules.yaml`, `classify_rules.yaml`, `units.yaml` (unit synonyms → Mealie unit names), `glossary_desi.yaml`, `glossary_de_en.yaml`, `site_selectors.yaml`, and prompts in `prompts/` (one file per LLM task, plus `style_roman_urdu.md`). JSON Schemas for LLM outputs are generated from the pydantic models, not hand-written.

### Modules (deep modules behind small interfaces)

1. **State Store.** Owns `pipeline.db`. Entities: Saved List, Video (Video Key, URLs seen, list memberships, metadata, Video Label), Recipe Part (Item Key, Video Key, part index, outline slice, Mealie slug), Creator (handle per platform, Recipe Website), Stage Record (entity, stage, status `pending|running|done|failed|skipped|review`, attempts, last error, timestamps), Usage Record (backend, model, task, tokens/cost when known). Interface: register/list Saved Lists; upsert Video by Video Key; create Recipe Parts for a Video (replacing earlier ones only if none were uploaded); `next_batch(stage, limit)` returning entities whose prerequisites are done; `record(entity, stage, status, detail)`; queries for status and reports. Schema migrations are versioned and applied on open.
2. **Stage Runner.** Runs named stages in dependency order over the State Store with an `Adapters` bundle, `limit`, `dry_run` and time-window settings. Each stage is a function `(ctx) -> StageReport`. A failure in one entity is recorded and never stops the stage. `UsageLimited` from the LLM pauses the whole run until the reset time (or the window opens), then resumes. Ctrl+C finishes the current entity and exits cleanly.
   - Video stages, in order: `collect`, `metadata`, `classify`, `dedupe`, `scrape`, `transcribe`, `outline`.
   - Recipe Part stages: `extract`, `parse`, `tag`, `verify`, `upload`.
3. **Adapters** (ports, each with a real implementation and an in-memory fake; selected by an `Adapters` factory so tests inject fakes):
   - `MealieGateway`: `about()`, `whoami()`, `catalog() -> Catalog(tags, foods, units)`, `create_food(name, plural?)`, `create_unit(name, abbreviation?)`, `create_tag(name)`, `find_recipe(item_key | org_url)`, `create_recipe(name) -> slug`, `patch_recipe(slug, payload)`, `get_recipe(slug)`, `upload_image(slug, path)`, `delete_recipe(slug)`. The real one uses `httpx` with timeouts and retries on connection errors, and follows the contract in wayfinder ticket 03. The fake keeps state in memory and **enforces the same rules** (unknown food/unit IDs rejected, `org_url` filter, slug generation).
   - `LLMBackend`: `complete(task, prompt, schema, tier, images=()) -> dict`, raising `UsageLimited(reset_at|None)` or `LLMError`. `tier` is `fast` (Haiku), `strong` (Sonnet) or `strongest` (Opus if available, else Sonnet at high effort). Implementations:
     - `ClaudeCliBackend`: `claude -p --model <alias> --safe-mode --tools "" --system-prompt-file <task prompt> --output-format json --json-schema <schema> --no-session-persistence`, with the prompt on stdin; `--tools "Read"` plus a working directory of images when `images` is given. It reads `structured_output` and logs usage.
     - `OpenAIBackend`: only constructed with `--allow-openai`, refuses calls once `OPENAI_MAX_USD` is spent.
     - `FakeLLM`: returns scripted responses matched by task and prompt substring, and records calls.
   - `VideoSource` (yt-dlp, as a library): `list_playlist(url, cookies?)`, `metadata(url, cookies?) -> VideoMeta` (title, description, uploader + id, duration, upload date, chapters, thumbnail URL, subtitle tracks, location if present), `pinned_comments(url)`, `download_subtitles`, `download_audio(url) -> path` (16 kHz mono), `grab_frame(url_or_file, at_seconds) -> path`.
   - `ListCollector` per platform: `enumerate(list_url) -> Iterator[str]` (raw Video URLs), with resume cursors stored in the State Store. YouTube uses `VideoSource.list_playlist`; Instagram and Facebook use the Browser.
   - `Browser`: a persistent Playwright Chrome context on the pipeline profile; `login(platform)` (visible window, waits for the user), `export_cookies(path)`, `open(url)` with response listening, `fetch_rendered(url) -> Page`. It detects stop signals and raises `NeedsHumanLogin`.
   - `WebFetcher`: `fetch(url) -> Page(final_url, status, html)` using httpx with a real User-Agent, falling back to `Browser.fetch_rendered` on block/JS-only pages; `robots.txt` honoured for third-party domains; per-domain pacing; on-disk cache.
   - `Transcriber`: `transcribe(audio_path, language_hint?, vocabulary_prompt?) -> Transcript(language, segments[start,end,text,avg_logprob,no_speech_prob], quality)`. Real `faster-whisper` with the model chosen by the benchmark; fake returns fixtures.
   - `Clock`/`Sleeper`, injected so pacing and pause logic are testable without waiting.
4. **URL Normalizer** (pure): any supported URL → `(platform, video_id, canonical_url)` or `unsupported`. Strips tracking parameters (`si`, `igsh`, `utm_*`, `mibextid`, `fbclid`…), handles `youtu.be`, `/shorts/`, `m.`/`www.`, Instagram `/p/` `/reel/` `/reels/` `/tv/`, Facebook `/reel/`, `/watch/?v=`, `/<page>/videos/<id>`, `fb.watch`, `/share/v|r/` (share links are resolved via redirect by the caller, then normalized).
5. **Classifier**: `signals(meta) -> Signals` (pure, from `classify_rules.yaml`), plus a batched LLM call (`fast` tier, ~20 Videos per call) returning `{video_key, label, confidence, reasons[]}`. Escalation for `uncertain` or confidence < threshold: re-classify with subtitles, or with the first 60 s of transcript once transcription exists. Overrides from `reports/classification.csv` always win and are re-read on every run.
6. **Source Builder**: collects the Sources for a Video (`web`, `desc`, `cmt`, `asr`, `ocr`) and the Source priority. It includes **Link Discovery** (pure: URLs from text, short-link expansion via the fetcher, link-in-bio expansion, title-to-link fuzzy match) and **Structured Recipe Extraction** (pure: HTML → `SourceRecipe` via JSON-LD incl. `@graph`, microdata/RDFa, WPRM/Tasty/Mediavine selectors, `recipe-scrapers`, else main-text fallback), recording `extraction_method`. It maintains the Creator → Recipe Website registry and site search (WordPress search / REST / sitemap, fuzzy title match ≥ 85, flagged `site_search`).
7. **Transcription Policy** (pure decision + orchestration): skip when a structured website recipe exists, or the description/pinned comment holds an ingredient list (≥ 3 quantity+unit lines or an "ingredients"/"zutaten"/"ajza"/"samagri" heading); else use creator subtitles, else transcribe. The vocabulary prompt is title + description + common units. Audio pre-processing uses an ffmpeg filter chain. Quality flags: low avg logprob, high no-speech ratio, low words-per-minute → `needs_ocr` review when no usable caption exists. One GPU job at a time.
8. **Outliner**: one `strong` LLM call per Video returns the Outline (`parts: [{title, start_s?, end_s?, website_url?, caption_block?}]`, `language`). Validation (pure): parts are non-overlapping, inside the Video duration, ≥ 1 part. Segmentation (pure) gives each part its own slice of each Source (transcript by timestamps; caption by its block; own website page), with shared intro/outro marked shared.
9. **Extractor**: per Recipe Part, one `strong` LLM call with the part's Sources (labelled `[SRC:web]` etc.) returns an `ExtractedRecipe`. In the same call it returns the LLM ingredient parse for each line and ranked tag choices from the full tag list (passed as an enum), to save usage. Rules in the prompt: never invent quantities; one ingredient per line; English Ingredient Lines (translated, original kept); recipe text in the Recipe Language (Roman Urdu/Hindi per `style_roman_urdu.md`); Sections kept; Evidence quotes are verbatim from the cited Source in its original language/script.
10. **Ingredient Parser**: for each English Ingredient Line, engine A is `ingredient-parser-nlp` and engine B is the LLM parse from the Extractor. **Reconcile** (pure) gives `agreed` / `nlp_preferred` / `conflict` / `unparsed` per the rules in `PIPELINE_SPEC.md` §7. **Unit Normalizer** (pure, `units.yaml`) maps to Catalog units. **Food Matcher** (pure) checks exact → plural/alias → singular/lowercase → rapidfuzz token-set ≥ 92 → `new`. **Sanity Checks** (pure) flag implausible quantities and food-is-a-unit cases. New Foods/Units are created through `MealieGateway` (serialised, logged to `reports/created_foods.csv` / `created_units.csv`), unless `auto_create_foods=false`, in which case they go to review.
11. **Tagger**: combines the LLM's ranked choices (already restricted to existing tags) with **Rule Tags** (pure, `tag_rules.yaml`, evaluated on parsed Foods, times, language and drink-ness), removes contradictions (pure, for example a vegetarian tag with a meat Food), and keeps 1–6 tags. If none survive: one retry, else the `To Review` fallback (created once if missing). Suggestions → `reports/suggested_tags.csv`.
12. **Verifier**: computes hard checks H1–H5 and soft checks S1–S7 exactly as in `PIPELINE_SPEC.md` §9. Grounding (pure) does normalized fuzzy containment (≥ 90) of each quote in its cited Source slice, in the original script. The Quality Score is a weighted sum (weights in settings). The LLM judge (S7, `strong`) runs only when the deterministic score is below the usage-saving skip threshold (90). Outcome: `upload`, `upload_review`, `retry` (once, with findings appended to the extraction prompt, using the `strongest` tier), or `review`.
13. **Uploader**: builds the Mealie payload (pure): name, description, servings/yield, ISO-8601 durations, ingredients with `referenceId`s and Section titles, steps with `ingredientReferences` (food-name matching, pure), notes (including sibling-part links), tags, `orgURL` (timestamped for YouTube multi-part: `&t=<start>s`), `extras` (`item_key`, `video_key`, `part`, `of`, `platform`, `website_url`, `score`, `pipeline_version`, `also_on`). It is idempotent by Item Key (State Store slug, then `extras`/`org_url` lookup), with `--mode skip|update`. It uploads the image (website image > part start frame > thumbnail; YouTube thumbnail `maxresdefault` → `hqdefault`), first as a file and then by URL. If both fail, the recipe stays and is marked `image_missing`. It then reads the recipe back and compares ingredient count, food IDs, tags and steps, then records the slug. `--dry-run` writes the payload to `work/` instead.
14. **Dedupe**: exact Video Key merge at collect time. Near-duplicates are matched by same Creator across platforms (handle similarity) + title/caption fuzzy ≥ 85 + upload date ± 7 days, then confirmed after parsing by food-level Jaccard ≥ 0.7. A canonical Video is chosen by richest Source. Existing-in-Mealie matching is the **Existing Recipe Index** (ticket 22): every Mealie recipe's `orgURL` is normalized to a Video Key / website URL. The cheap check runs **before extraction** (no LLM usage for already-imported Videos). A name + ingredient-overlap check runs before upload. Probable duplicates are held for review, and recipes the pipeline didn't create are only modified with `--upgrade-existing`. Output: `reports/dedupe.csv` with an override column.
15. **Reporter**: `reports/report.csv` (one row per Recipe Part and per skipped Video), `reports/report.html` (same data, sortable table), `review/<item_key>.md` (Sources side by side with the extracted recipe and failed checks), usage summary, Catalog cleanup hints (empty foods/tags).
16. **Usage Governor**: inside the Stage Runner. It handles `UsageLimited` (pause until reset, or poll every 15 min when no reset time is given), `--window HH:MM-HH:MM` for AI stages, usage-saving tier selection, single-concurrency for `claude -p` on Pro, and the OpenAI cap.

### CLI surface

`mp doctor`, `mp login <platform>`, `mp lists add <url>` / `mp lists` / `mp sync [--list]`, `mp add <url…> | --file <path>`, `mp run [--stages a,b] [--limit N] [--window HH:MM-HH:MM] [--dry-run] [--mode skip|update] [--allow-openai]`, `mp status`, `mp review classify`, `mp retry <item_key|video_key> [--stage]`, `mp reset <stage> [--failed-only]`, `mp report`, `mp bench-whisper [--samples dir]`.

### Data shapes (decisions)

- `ExtractedRecipe`: `is_recipe`, `name`, `description`, `language` (`en|de|ur|hi`), `servings?`, `yield_text?`, `prep_minutes?`, `cook_minutes?`, `total_minutes?`, `ingredients: [{line (English), original_line, section?, quantity_stated, evidence:[{source, quote}], llm_parse:{quantity?, quantity_max?, unit?, food?, note?}}]`, `instructions: [{section?, text, evidence:[…]}]`, `notes: [str]`, `tag_choices: [{tag, reason}]` (enum of existing tag names), `missing_info: [str]`.
- `Outline`: `language`, `parts: [{title, start_s?, end_s?, website_url?, caption_block?, is_component_of_other_part: false}]`.
- Classification item: `{video_key, label, confidence (0–1), reasons[]}`.
- Judge: `{problems: [{severity: blocker|major|minor, field, description}]}`.

## Testing Decisions

Good tests check **external behaviour at agreed seams**: given these Sources and this Catalog, this is what lands in Mealie. They never assert on internal calls or private helpers. Expected values come from hand-written fixtures and worked examples, never recomputed the way the code computes them.

**Agreed seams** (no others without updating this spec):

1. **Pipeline seam (primary).** Run stages through the Stage Runner (or the `mp` CLI via `typer`'s test runner) on a temporary workspace with the fake adapters (`FakeMealie`, `FakeLLM`, fake `VideoSource`, fake collectors, fixture-backed `WebFetcher`, fake `Transcriber`, fake clock). Assert on the State Store's public queries, the files in `reports/` and `review/`, and the recipes inside `FakeMealie`. Every user-visible ticket gets at least one test here.
2. **Pure-module seam.** Table-driven tests for the pure modules: URL Normalizer, classifier signals, Link Discovery, Structured Recipe Extraction (on saved HTML fixtures), Transcription Policy, Outline validation and segmentation, Reconcile, Unit Normalizer, Food Matcher, Sanity Checks, Rule Tags and contradictions, Grounding, Quality Score, payload builder.
3. **Adapter contract seam.** One shared contract test suite per port, run against the fake **and** the real adapter's request layer. `MealieHttpGateway` runs against a local `pytest-httpserver` asserting exact paths, headers and JSON from wayfinder ticket 03. `ClaudeCliBackend` runs against a stub `claude` executable (a tiny script placed first on PATH) that echoes recorded `--output-format json` results, including a usage-limit result. An opt-in live run of the Mealie contract suite (`mealie_live` marker, `MEALIE_IT_URL`/`MEALIE_IT_TOKEN`) targets a throwaway Mealie container or the user's instance; it is never part of CI. yt-dlp, Playwright and faster-whisper real calls are **not** run in CI; their adapters are thin and are verified by the manual laptop steps in each ticket.

Fixtures live under `tests/fixtures/` (HTML pages, `info.json` samples, transcripts, LLM responses). They are synthetic or trimmed; no personal data or cookies.

There is no existing test prior art in the repo yet. Ticket 01 establishes the conventions (fixture loading, adapter factory injection, workspace temp dirs) that later tickets follow.

## Out of Scope

- OCR of on-screen text (Videos are routed to review as `needs_ocr`).
- Platforms other than YouTube, Instagram, Facebook. Mealie categories, tools, nutrition, meal plans, video assets.
- Any use of Mealie's own import, scraper, AI or ingredient parser endpoints.
- Running anywhere but the user's laptop; multi-user; a web UI.

## Further Notes

- Agents usually can't reach the Mealie PC, Chrome logins or the GPU. Every ticket lists **manual verification steps** for the user on the laptop, and the HITL tickets (`ready-for-human`) cover first-run setup and calibration.
- Open wayfinder tickets gate specific implementation tickets: Instagram enumeration (15) gates the Instagram collector, Facebook enumeration (16) gates the Facebook collector, Whisper on Windows (17) gates transcription, `claude -p` on Windows and limits (18) gates the usage governor, the Mealie check (13) and the pilot list (14) gate the first real run, and run defaults (19) gate the full run.
