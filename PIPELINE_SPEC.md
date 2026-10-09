# Mealie video recipe pipeline: plan and spec

**Status:** Draft v0.2 (own scraper, parser and verification; Mealie is storage only). Needs answers to the [open questions](#11-open-questions) before build starts.
**Goal:** Import about 900 cooking videos (about 300 each from Instagram, YouTube and Facebook) into a self-hosted Mealie instance as clean recipes. Each recipe should have parsed ingredients (quantity, unit and food all linked) and at least one existing tag.

---

## 1. Why Mealie's built-in import falls short

I checked Mealie's current source (`v3.28.0`, `mealie-recipes/mealie`, commit `96f15f3`, 2026-10-08). The built-in **"Import with AI"** feature (`POST /api/recipes/create/ai`) already downloads videos with yt-dlp and transcribes them. It falls short in four ways that match what you're seeing:

| Problem | Where it lives in Mealie | Effect |
|---|---|---|
| **Ingredients are never parsed** | `services/recipe/import_workflow/recipe_conversion.py`: `RecipeIngredient(title=..., note=ingredient.text)` | Each ingredient is saved as plain note text, with no quantity, unit or food. Scaling, shopping lists and the parsed display don't work. |
| **Tagging is optional and fails silently** | `steps/resolve_organizers.py`: `required = False`, and only the first 200 tags (`MAX_INJECTED_TAGS`) go to the model | A recipe can be saved with zero tags, and nothing warns you. |
| **Instagram and Facebook need cookies** | `YTDLP_COOKIEFILE` setting | Without a cookie file, many Instagram and Facebook downloads fail or return empty media. |
| **Website links in descriptions are ignored** | `compilers/transcription.py` puts the description in as text only | If the full recipe is on your website ("recipe at example.com/…"), Mealie never fetches that page, so it relies on a noisier transcript. |

Its transcripts and AI output weren't good enough in practice either. **Decision (v0.2):** the pipeline does **not** use Mealie's import, scraper, transcription, AI or ingredient parser. Everything (visiting websites, reading video pages, transcription, extraction, ingredient parsing, tagging and **verification**) runs in our own code. Mealie is **only the storage target**: we read its tags, foods and units, and write finished, already-checked recipes.

---

## 2. Architecture overview

```
 0.DISCOVER ─▶ 1.SCRAPE ─▶ 2.TRANSCRIBE ─▶ 3.EXTRACT ─▶ 4.PARSE ─▶ 5.TAG ─▶ 5b.VERIFY ─▶ 6.UPLOAD ─▶ 7.REVIEW
 list videos   our own     own STT,       LLM with      own         closed    checks +      Mealie API    report +
 + dedupe      scraper:    only if        evidence      ingredient  list,     score gate    (storage      review
               video page  needed         quotes        parser +    ≥1 tag    ─────────     only) +       queue
               + website                                food/unit             fail ⇒ retry  read-back
                                                        resolve               or review     check
            all stage outputs cached on disk + state in SQLite; every stage re-runnable on its own
```

**Design principles**

- **Every stage is resumable and idempotent.** State lives in `pipeline.db` (SQLite) with one row per video and a `stage` / `status` / `error` column. Raw artifacts are stored under `data/<platform>/<video_id>/`. Re-running the pipeline skips finished work, and you can re-run any single stage on its own (for example, re-tag everything after adding new tags).
- **The cheapest good source wins.** Use the website recipe first, then a description that contains a full recipe, then creator subtitles, then auto-subtitles, then Whisper. Transcription is the fallback, not the default.
- **Mealie stays the source of truth** for tags, foods and units. Nothing is hardcoded.
- **Dry-run mode** runs the whole pipeline and writes the final JSON without touching Mealie.
- **Start with a pilot of 20 videos** (a mix of platforms), check the results in the Mealie UI, tune, then run the rest.

**Stack:** Python 3.12, `uv`, `httpx`, **Playwright** (headless Chromium for JS-heavy pages and link-in-bio pages), `selectolax` / `trafilatura` (HTML → clean text), `extruct` + `recipe-scrapers` (structured data), `pydantic` v2, `yt-dlp` (+ `curl_cffi`), `faster-whisper`, `ingredient-parser-nlp`, `rapidfuzz`, `typer` CLI, `sqlite3`. Runs on **the same PC as Mealie**, so the API is just `http://localhost:9000`.

---

## 3. Stage 0: Discover (build the video manifest)

**Output:** one `videos` row per video with `platform`, `video_id`, `url`, `title`, `upload_date`, `duration`, and `status=discovered`.

| Platform | Primary method (recommended) | Alternative |
|---|---|---|
| **YouTube** | `yt-dlp --flat-playlist -J https://www.youtube.com/@<channel>/videos` and `/shorts`. No key needed, and returns IDs and titles fast. | YouTube Data API v3: `channels.list` → uploads playlist → `playlistItems.list` (1 quota unit per 50 videos, 10k units/day free). |
| **Instagram** | **Official data export** if it's your account: Accounts Center → *Your information and permissions* → *Download your information* → **JSON**, media included. It contains every post and reel with its **caption** and the **video file**, with no scraping and no ban risk. | (a) Instagram Graph API (`graph.instagram.com/me/media?fields=id,caption,media_type,media_url,permalink,thumbnail_url,timestamp`), which needs a **Professional (Creator/Business)** account and a Meta developer app with `instagram_business_basic`. (b) `yt-dlp` / `instaloader` with a logged-in cookie file. This is fragile: Instagram reworked its extractors in mid-2026, and accounts get rate-limited or flagged. |
| **Facebook** | **Official data export** (same Accounts Center flow, Facebook profile/Page → JSON + media). Includes videos and reels with descriptions. | `yt-dlp` with cookies against the Page's `/videos` and `/reels` tabs. |

**Cross-platform deduplication matters.** If the same recipe is posted on all three platforms, 900 videos might be about 300 unique recipes. After discovery:

1. Group candidates by normalized title, caption similarity (fuzzy / embedding cosine), and upload date within ±7 days.
2. Mark one **canonical** video per group. Prefer the one with the richest source: website link > longest description > YouTube (best subtitles) > others.
3. Create **one** Mealie recipe per group. The other URLs go in `extras` and in a recipe note ("Also on Instagram: …").

The dedupe output is a CSV you can check and correct by hand before continuing.

---

## 4. Stage 1: Scrape (our own scraper, video page and website)

Mealie's scraper is not used. Our scraper gathers **every** piece of raw evidence for a video and saves it, so later stages and the verifier can always go back to the original source.

### 4.1 Video page

Saved under `data/<platform>/<id>/`:

| File | How |
|---|---|
| `info.json` | `yt-dlp --skip-download --write-info-json` (title, full description, uploader, duration, chapters, thumbnail), or the export / Graph API record |
| `description.txt` | full description or caption, **not truncated** (the "…more" text is in `info.json`) |
| `pinned_comment.txt` | creators often post the recipe in a pinned comment. `yt-dlp --write-comments --extractor-args "youtube:max_comments=20"`, keeping only comments by the uploader |
| `subs.<lang>.vtt` | `--write-subs --write-auto-subs --sub-langs "en.*,<lang>"`. Creator subtitles and auto-subtitles are kept apart |
| `thumb.jpg` | `--write-thumbnail` |
| `video.mp4` / `audio.m4a` | only if stage 2 needs them (exports already contain the MP4) |

### 4.2 Website (the main source when it exists)

1. **Link discovery:** pull URLs from the description, the pinned comment and the channel "about" links.
   - Expand short links (`bit.ly`, `tinyurl`, `geni.us`) by following redirects with `httpx`.
   - **Link-in-bio pages** (`linktr.ee`, `lnk.bio`, `beacons.ai`, Instagram "link in bio") are opened in **Playwright** and their links collected. A link is picked by fuzzy-matching the video title against the link text or slug.
   - **Site search fallback:** if a video has no link but you have a recipe website, search the site for the video title (`/?s=<title>`, the WordPress REST API `/wp-json/wp/v2/posts?search=`, or `sitemap.xml`) and fuzzy-match titles (≥ 85). It's flagged `link_source=site_search` so the verifier is stricter.
2. **Fetch:** use `httpx` first, with a real browser User-Agent and HTTP/2. If the page is blocked (403/429, Cloudflare challenge) or the recipe card is rendered by JS, retry with Playwright. Raw `page.html` is saved, plus `page.png` (a screenshot, useful for review).
3. **Extract structured data, in this order:**
   1. **JSON-LD `@type: Recipe`** via `extruct` (including inside `@graph`, which is the WordPress/Yoast style)
   2. **Microdata / RDFa** `Recipe` via `extruct`
   3. **Recipe-card plugin HTML** (WP Recipe Maker `.wprm-recipe`, Tasty Recipes `.tasty-recipes`, Mediavine Create `.mv-create`) via site-specific CSS selectors in `config/site_selectors.yaml`
   4. **`recipe-scrapers`** site-specific scrapers
   5. **Fallback:** `trafilatura` main-content text → handed to the LLM in stage 3 as unstructured text
4. **Normalize** to an internal `SourceRecipe` (name, ingredient lines with section titles, steps, yield, times, image). The `extraction_method` used is recorded, because it feeds the confidence score.
5. **Politeness:** respect `robots.txt` for third-party sites (your own site can be allowlisted), allow 1 request every 2–3 s per domain, and cache everything so each page is fetched once.

### 4.3 Source priority

```
website structured data  >  website plugin HTML  >  description / pinned comment with ingredient list
  >  creator subtitles  >  our Whisper transcript  >  YouTube auto-subs  >  website plain text (LLM)
```

All available sources are still passed on, not only the best one. The verifier uses the extra ones to **cross-check**.

---

## 5. Stage 2: Transcribe (our own, only when needed)

**Decision rule:** transcribe if there's no website recipe **or** a video is the only evidence for quantities. Even when a website exists, we still transcribe a short sample if the website ingredient list looks incomplete (fewer than 3 ingredients). We don't use Mealie's transcription or YouTube auto-subs as the main transcript, because auto-subs have no punctuation and garble ingredient names.

Rough volume estimate: about 900 videos × about 1.5 min ≈ **22 h of audio** worst case (much less after skips).

| Option | Quality | Cost for about 22 h | Notes |
|---|---|---|---|
| **`faster-whisper` `large-v3`, local** ⭐ if you have an NVIDIA GPU | Very good | Free | Word timestamps, VAD filter (`vad_filter=True`) to skip music. |
| **Groq `whisper-large-v3`** ⭐ if no GPU | Very good | About $0.11/h → **about $2.50** | 25 MB limit, so send 16 kHz mono opus. A free tier exists. |
| OpenAI `gpt-4o-transcribe` | Best on music-heavy audio | About $0.36/h → about $8 | Retry engine for videos the others fail on. |

**Making it robust:**
- **Vocabulary prompt:** the video title + description + common units go in `initial_prompt` / `prompt`, so "gochujang" isn't heard as "go-to-jang".
- **Audio pre-processing:** `ffmpeg -af "highpass=f=100,lowpass=f=8000,loudnorm"`. Optional: separate vocals with `demucs` for videos with loud music (turned on automatically if the first pass has low average log-probability or `no_speech_prob > 0.5`).
- **Quality signals stored per transcript:** average log-probability, no-speech ratio, and words per minute. A silent reel (music + text on screen) is detected here and routed to **on-screen text OCR**: sample 1 frame/s with `ffmpeg`, dedupe similar frames, and read the overlay text with a vision LLM. This is phase 2, but the routing exists from day one.

Output: `transcript.json` (segments with timestamps), `transcript.txt`, `transcript.meta.json`.

---

## 6. Stage 3: Extract (LLM → structured recipe, with evidence)

When structured website data exists, the LLM **does not rewrite it**. It only fills gaps (missing times or servings) and merges in tips from the video. When there's no website recipe, the LLM extracts from description + transcript.

The prompt gets all sources, labeled:

```
[SRC:web]   Website recipe (JSON-LD)
[SRC:desc]  Video description
[SRC:cmt]   Pinned comment
[SRC:asr]   Transcript (whisper, with timestamps)
[SRC:ocr]   On-screen text (if any)
```

**Every ingredient and step must cite its evidence.** The output schema is enforced with structured outputs:

```python
class Evidence(BaseModel):
    source: Literal["web", "desc", "cmt", "asr", "ocr"]
    quote: str                      # verbatim substring of that source

class ExtractedIngredient(BaseModel):
    line: str                       # "2 cups all-purpose flour, sifted"
    section: str | None             # "For the sauce"
    evidence: list[Evidence]        # ≥1, required
    quantity_stated: bool           # false ⇒ the source never gave an amount

class ExtractedRecipe(BaseModel):
    is_recipe: bool
    name: str
    description: str
    servings: float | None
    yield_text: str | None
    prep_minutes: int | None
    cook_minutes: int | None
    total_minutes: int | None
    ingredients: list[ExtractedIngredient]
    instructions: list[Step]        # each with evidence too
    notes: list[str]
    language: str
```

Rules: **never invent quantities** (unstated means `to taste` / `quantity_stated=false`), one ingredient per line, keep section headers, and use the original wording for food names.

**Model:** a Claude model through the Anthropic API with structured outputs. Sonnet 5.5 for extraction, because accuracy matters more than cost on about 300–900 recipes. Configurable. The cost per recipe is measured on the pilot.

---

## 7. Stage 4: Parse ingredients (our own parser, two engines that must agree)

Mealie's `/api/parser` is not used. Each ingredient line is parsed by **two independent engines** locally:

1. **`ingredient-parser-nlp`** (Python library, CRF model) gives quantity (incl. ranges and fractions), unit, food name, size, preparation, comment, and confidence per field.
2. **The LLM** parses the same line, constrained to `{quantity, quantity_max, unit, food, note}`, with your Mealie unit list in the prompt.

**Reconciliation per line:**

| Case | Action |
|---|---|
| Both agree (qty equal, unit maps to the same Mealie unit, food fuzzy ≥ 90) | accept, `parse_status=agreed` |
| Disagree on one field, NLP confidence for that field ≥ 0.9 | take NLP, `parse_status=nlp_preferred` |
| Disagree otherwise | take the LLM result, `parse_status=conflict` → counts against the recipe score |
| No food found by either | keep the line as note-only, `parse_status=unparsed` → recipe goes to review |

**Unit normalization:** a local table maps `tbsp/tbs/T/Esslöffel/EL → tablespoon`, `g/gr/grams → gram`, and so on, onto **your Mealie units** (`GET /api/units?perPage=-1`).

**Food resolution** against **your Mealie foods** (`GET /api/foods?perPage=-1`, names + plural names + aliases):
exact → plural/alias → singularized + lowercased → `rapidfuzz` token-set ≥ 92 → **new food**.
New foods are created with `POST /api/foods` and logged in `created_foods.csv` (or queued for approval, see question 6). Mealie's `PATCH /api/recipes/{slug}` does **not** create missing foods or units, so every ingredient must point to an existing `id` before upload.

**Sanity checks per line:** a quantity is out of range for its unit (for example `> 5 kg` salt or `> 20 tbsp`), a count unit is used with a liquid, or a food is actually a unit ("cup" as the food). Any of these makes the line `suspicious`.

---

## 8. Stage 5: Tag (≥1 existing tag, required)

1. `GET /api/organizers/tags?perPage=-1` loads **all** your tags, not just the first 200.
2. The LLM gets the parsed recipe and the **full tag list as a JSON-schema enum**, so it can't return a tag that doesn't exist. It returns 1–6 tags, each with a reason.
3. **Rule tags** from `config/tag_rules.yaml`, computed from parsed data rather than guesses: `no meat/fish foods → Vegetarian`, `total ≤ 30 min → Quick`, `foods ∋ chicken|turkey → Poultry`, and so on.
4. **Contradiction check:** the LLM said "Vegetarian" but a parsed food is in the meat list, so the tag is dropped and flagged.
5. At least one tag is required. If none are left, retry once. If there are still none, use the fallback tag `To Review`.
6. Suggested **new** tags only go to `suggested_tags.csv` for your approval.

---

## 9. Stage 5b: Verify (the gate before anything reaches Mealie)

Every recipe gets a **quality score (0–100)** made of hard checks and soft checks. **Hard failures block upload.**

| # | Check | Type |
|---|---|---|
| H1 | `is_recipe == true` and name is non-empty | hard |
| H2 | ≥ 2 ingredients and ≥ 1 instruction step | hard |
| H3 | **Grounding:** every ingredient's evidence `quote` actually occurs in the cited source (fuzzy ≥ 90 on normalized text), so no hallucinated ingredients | hard (per ingredient → dropped + flagged; > 20 % dropped → recipe fails) |
| H4 | Every ingredient has a resolved Mealie `food.id` (or is an intentional note line like "Salt and pepper to taste") | hard |
| H5 | ≥ 1 existing tag | hard |
| S1 | **Cross-source agreement:** when both website and video exist, compare the ingredient sets (food-level Jaccard). Low overlap suggests the wrong website page was matched | soft (< 0.5 → review) |
| S2 | **Ingredients ↔ steps:** each food is mentioned in some step, and each food mentioned in the steps is in the ingredient list | soft |
| S3 | Parse agreement rate (stage 4) | soft |
| S4 | Transcript quality signals (stage 2) | soft |
| S5 | Quantity sanity: the `suspicious` count from stage 4 | soft |
| S6 | Times and servings are plausible (total ≥ prep, servings 1–50) | soft |
| S7 | **LLM judge:** an independent call that sees the final recipe and the raw sources and answers *"What's missing or wrong?"* in a JSON list | soft |

**Gate:** score ≥ 80 with no hard fail → upload. 60–79 → upload with the `To Review` tag (if allowed). Below 60 or a hard fail → **retry once** with a stronger model and the verifier's findings in the prompt. If it still fails, it goes to the review queue only and is not uploaded.

Output: `verify.json` (each check, pass/fail, details) is kept with the recipe.

---

## 10. Stage 6–7: Upload to Mealie, read-back, review

All calls use `Authorization: Bearer <MEALIE_TOKEN>` against `MEALIE_URL` (for example `http://localhost:9000`).

| Step | Call |
|---|---|
| Idempotency | `GET /api/recipes?queryFilter=orgURL="<url>"`. If found, update (or skip, per `--mode`). |
| Create shell | `POST /api/recipes` `{ "name": "..." }` → `slug` |
| Fill | `PATCH /api/recipes/{slug}` with `description`, `recipeServings`, `recipeYield`, `prepTime`/`performTime`/`totalTime`, `recipeIngredient` (`[{quantity, unit:{id,name}, food:{id,name}, note, originalText, title, referenceId}]`), `recipeInstructions` (`[{id,title,summary,text,ingredientReferences}]`), `notes`, `tags` (`[{id,name,slug}]`), `orgURL`, `extras` (`{pipeline_version, platform, video_id, website_url, score, also_on}`) |
| Image | Website image if it exists, otherwise the video thumbnail: `PUT /api/recipes/{slug}/image` (multipart upload of the local file, so no Mealie-side scraping) |
| **Read-back check** | `GET /api/recipes/{slug}` and compare with what we sent: same ingredient count, every `food.id` present, tags present, steps present. On a mismatch, mark `upload_mismatch` and retry. |

Exact camelCase field names are checked against your instance's `/openapi.json` during the smoke test (M0).

**Reporting:**
- `report.csv` / `report.html` has one row per video: score, which checks failed, source used, transcript quality, tags, foods created, and the Mealie link.
- `review/` has one Markdown file per recipe needing attention, showing the sources side by side with the extracted recipe and the failed checks.
- After the run: `GET /api/foods/empty`, `GET /api/organizers/tags/empty` for cleanup, and `PUT /api/foods/merge` for duplicate foods.

## 11. Open questions

1. **Websites to scrape:** which domain(s) do the video descriptions link to? Is it one recipe site (your own?) or many different creators' sites? Can you send me 3–5 example video URLs, including one where the link only works through link-in-bio, so I can build and test the scraper on real pages first?
2. **Whose videos are these?** Are they **your own accounts** (then official data exports are the best route for Instagram and Facebook), or someone else's / saved posts (then we need yt-dlp + cookies)?
3. **Is it the same recipes on all three platforms?** Is it about 300 unique recipes posted 3 times, or about 900 different ones? This decides whether dedupe is central.
4. **Language** of the videos, and the language you want the recipes stored in.
5. **Hardware:** do you have an NVIDIA GPU (then local Whisper is free), or should we use Groq or OpenAI? Which LLM API keys do you already have (Anthropic, OpenAI, other)?
6. **Foods and units:** is it OK to auto-create missing foods and units in Mealie (logged to CSV), or should unknown ones go to a review list first?
7. **Tags:** is it OK to add a `To Review` tag for uncertain recipes? Should the pipeline also set **categories** and **tools**, or only tags? Is it allowed to *suggest* new tags?
8. **Mealie version and setup:** which version are you running (Settings → About), and is it on Docker at `localhost:9000`? (Needed only for API field names, since nothing of Mealie's AI or parser is used.)
9. **Existing recipes:** are some of these videos already imported (badly)? Should the pipeline **update** them (matched by `orgURL`) or skip them?
10. **Image:** website image first, otherwise the video thumbnail. Is that OK?
11. **Strictness:** recipes that fail verification are **not uploaded** and stay in the review queue. Or would you rather they get uploaded with a `To Review` tag?

---

## 12. Access setup checklist

| What | How | Env var |
|---|---|---|
| Mealie API token | Mealie → your profile → **API Tokens** → create (or `POST /api/users/api-tokens`) | `MEALIE_URL`, `MEALIE_TOKEN` |
| YouTube | Nothing for public videos. Optional: Google Cloud project → enable YouTube Data API v3 → API key | `YOUTUBE_API_KEY` (opt.) |
| Instagram | Request **Download your information** (JSON, all time, media included). It's ready in minutes to a few days. Fallback: export `cookies.txt` from a logged-in browser (Netscape format) | `IG_EXPORT_DIR` / `YTDLP_COOKIES` |
| Facebook | Same export from Accounts Center for the profile/Page | `FB_EXPORT_DIR` |
| Transcription | Groq console API key, **or** local GPU with CUDA + `faster-whisper`, **or** OpenAI key | `GROQ_API_KEY` / `OPENAI_API_KEY` |
| LLM | Anthropic API key (or OpenAI-compatible) | `ANTHROPIC_API_KEY` |
| Tools | `ffmpeg`, `uv`, Python 3.12, `yt-dlp` (keep it updated, since platforms break it often) | — |

Secrets go in `.env` (git-ignored). `cookies.txt` and exports are never committed.

---

## 13. Repo layout (proposed)

```
mealie_pipeline/
  PIPELINE_SPEC.md
  pyproject.toml
  .env.example
  config/
    settings.yaml          # domains allowlist, thresholds, languages, model names
    tag_rules.yaml
    site_selectors.yaml    # per-site recipe-card CSS selectors
    units.yaml             # unit synonym table → Mealie units
  src/mealie_pipeline/
    cli.py                 # `mp discover|scrape|transcribe|extract|parse|tag|verify|upload|report|run --limit 20`
    db.py                  # SQLite state
    sources/{youtube,instagram,facebook}.py
    scrape/{links.py,fetch.py,structured.py,plugins.py,fallback_text.py}   # our own website scraper
    transcribe/{subs,faster_whisper,groq,openai,ocr}.py
    extract/{prompt.py,schema.py,llm.py}
    parse/{nlp.py,llm.py,reconcile.py,units.py,foods.py}                  # our own ingredient parser
    tag/{llm.py,rules.py}
    verify/{checks.py,grounding.py,judge.py,score.py}
    mealie/{client.py,catalog.py}                                         # storage + tag/food/unit lookup only
    stages/*.py
  data/                    # git-ignored artifacts
  tests/                   # saved real pages (HTML fixtures), captions, transcripts; golden recipes for regression
```

---

## 14. Milestones

1. **M0 (setup):** answer the questions, add tokens to `.env`, run a smoke test against Mealie (`GET /api/app/about`, `/openapi.json`, list tags, foods and units, create and delete a test recipe).
2. **M1 (scraper and parser first):** build the website scraper and ingredient parser against your example pages. You hand-check about 10 **golden recipes** (correct ingredients, quantities and tags), which become regression tests that every later change must pass.
3. **M1b (YouTube pilot):** 10 YouTube videos end-to-end in dry-run with verification reports, then write to Mealie. You review them in the UI.
4. **M2 (Instagram and Facebook ingest):** parse the exports or Graph API data, plus cross-platform dedupe. You review the dedupe CSV.
5. **M3 (full pilot):** 20 mixed videos. Tune the prompts, tag rules and the verification score threshold.
6. **M4 (full run):** all videos in batches of 50, with a report after each batch.
7. **M5 (cleanup):** work the review queue, merge duplicate foods (`PUT /api/foods/merge`), remove empty tags.

---

### Sources

- Mealie source v3.28.0: `mealie/routes/recipe/recipe_crud_routes.py`, `mealie/routes/parser/ingredient_parser.py`, `mealie/services/recipe/import_workflow/*`, `mealie/services/recipe/recipe_service.py`, `mealie/schema/recipe/*`. https://github.com/mealie-recipes/mealie
- Mealie AI providers docs: https://mealie.io/documentation/getting-started/installation/ai-providers/
- Mealie migration guide (v3.23 AI workflow): https://mealie.io/contributors/developers-guide/migration-guide/
- ingredient-parser-nlp: https://github.com/strangetom/ingredient-parser
- extruct: https://github.com/scrapinghub/extruct · recipe-scrapers: https://github.com/hhursev/recipe-scrapers
- Groq speech-to-text: https://console.groq.com/docs/speech-to-text
- Instagram Media API reference: https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media
- yt-dlp releases (Instagram extractor rework mid-2026): https://github.com/yt-dlp/yt-dlp/releases
- Pricing figures are approximate (third-party summaries, 2026). Check them on provider pages before committing.
