# Mealie video recipe pipeline: plan and spec

**Status:** Draft v0.1. Needs answers to the [open questions](#11-open-questions) before build starts.
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

So the plan is to **do the extraction, tagging and parsing ourselves** and use Mealie's API only for things it does well: storage, the ingredient parser, and food, unit and tag lookups.

---

## 2. Architecture overview

```
 ┌──────────┐   ┌──────────┐   ┌────────────┐   ┌──────────┐   ┌────────┐   ┌──────────┐   ┌────────┐
 │ 0.DISCOVER│──▶│ 1.FETCH  │──▶│2.TRANSCRIBE│──▶│3.EXTRACT │──▶│ 4.TAG  │──▶│5.PARSE   │──▶│6.UPLOAD│──▶ 7.REVIEW
 │ list all  │   │ metadata │   │ (only if   │   │ LLM →    │   │ closed │   │ Mealie   │   │ Mealie │
 │ videos    │   │ desc,subs│   │  needed)   │   │ recipe   │   │ list   │   │ parser + │   │ API    │
 │ + dedupe  │   │ audio,   │   │            │   │ JSON     │   │ ≥1 tag │   │ food/unit│   │        │
 │           │   │ website  │   │            │   │          │   │        │   │ resolve  │   │        │
 └──────────┘   └──────────┘   └────────────┘   └──────────┘   └────────┘   └──────────┘   └────────┘
                        │                 all stage outputs cached on disk + state in SQLite
```

**Design principles**

- **Every stage is resumable and idempotent.** State lives in `pipeline.db` (SQLite) with one row per video and a `stage` / `status` / `error` column. Raw artifacts are stored under `data/<platform>/<video_id>/`. Re-running the pipeline skips finished work, and you can re-run any single stage on its own (for example, re-tag everything after adding new tags).
- **The cheapest good source wins.** Use the website recipe first, then a description that contains a full recipe, then creator subtitles, then auto-subtitles, then Whisper. Transcription is the fallback, not the default.
- **Mealie stays the source of truth** for tags, foods and units. Nothing is hardcoded.
- **Dry-run mode** runs the whole pipeline and writes the final JSON without touching Mealie.
- **Start with a pilot of 20 videos** (a mix of platforms), check the results in the Mealie UI, tune, then run the rest.

**Stack:** Python 3.12, `uv`, `httpx`, `pydantic` v2, `yt-dlp` (+ `curl_cffi` for impersonation), `faster-whisper` (optional local transcription), `recipe-scrapers` / `extruct` for website schema.org, `typer` CLI, `sqlite3`. Runs on **the same PC as Mealie**, so the API is just `http://localhost:9000`.

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

## 4. Stage 1: Fetch (raw material for each video)

For each canonical video, save under `data/<platform>/<id>/`:

| File | How |
|---|---|
| `info.json` | `yt-dlp --skip-download --write-info-json` (title, description, uploader, duration, thumbnail, chapters), or straight from the export / Graph API JSON |
| `description.txt` | from `info.json` / caption |
| `subs.<lang>.vtt` | `yt-dlp --write-subs --write-auto-subs --sub-langs "en.*,<your-lang>" --skip-download` (YouTube is excellent here, Instagram and Facebook rarely have them) |
| `thumb.jpg` | `--write-thumbnail` (becomes the recipe image) |
| `audio.m4a` | **only if** stage 2 needs it: `yt-dlp -f bestaudio -x` (or extract from the exported MP4 with `ffmpeg -vn`) |
| `website.html` / `website.recipe.json` | see below |

**Following website links (requirement #1):**

1. Pull URLs out of the description/caption with a regex. Expand short links (`bit.ly`, `linktr.ee`, `lnk.bio`…) by following redirects.
2. Keep links on **your recipe domain(s)** (an allowlist in config). Ignore affiliate and shop links.
3. Fetch the page and pull out the **schema.org `Recipe` JSON-LD** (`extruct` / `recipe-scrapers`). Most recipe sites (WordPress + WPRM / Tasty Recipes) have it.
4. If structured data exists, it's the **top-priority source**, and the LLM's job in stage 3 becomes "clean and normalize" instead of "extract".
5. "Link in bio" posts with no direct link can't be resolved automatically. They fall through to caption + transcript.

**Rate limiting:** 1 request per 2–5 s per platform with jitter, exponential backoff on 429, and `--sleep-requests` / `--sleep-interval` for yt-dlp. With 900 videos this still finishes in an evening.

---

## 5. Stage 2: Transcribe (only when needed)

**Decision rule:** skip transcription if a website recipe was found, **or** the description already contains an ingredient list. A heuristic: 3 or more lines matching quantity + unit patterns, or the words "ingredients" / "zutaten" / etc. Otherwise use creator subtitles if they exist, then auto-subtitles, then speech-to-text.

Rough volume estimate: about 900 videos × about 1.5 min ≈ **22 h of audio** worst case (probably far less after skips).

| Option | Quality | Cost for about 22 h | Notes |
|---|---|---|---|
| **`faster-whisper` `large-v3-turbo`, local** ⭐ if you have an NVIDIA GPU | Very good | Free | About 1 min of audio per few seconds on a modern GPU. CPU works but is slow (int8, hours). No upload, no limits. |
| **Groq `whisper-large-v3-turbo`** ⭐ if no GPU | Very good | About $0.04/h → **about $1** | OpenAI-compatible API. Free tier is about 8 h of audio/day, so it fits in 3 days. 25 MB file limit, so send 16 kHz mono opus. |
| OpenAI `gpt-4o-mini-transcribe` | Very good | About $0.18/h → about $4 | Also what Mealie's own audio provider uses. |
| OpenAI `gpt-4o-transcribe` | Best on noisy, music-heavy audio | About $0.36/h → about $8 | Worth it only for videos the others fail on. |
| YouTube auto-subs (free) | OK, no punctuation | Free | YouTube only, already fetched in stage 1. |

**Tips for cooking reels:** background music hurts accuracy. Pass a **prompt/glossary** to Whisper (`initial_prompt` with common ingredient and unit words) and the video title. Many reels say almost nothing and show text on screen, so for those the **caption is the source**. *Optional later:* sample frames and OCR the on-screen text with a vision LLM. This is out of scope for v1, but such videos are flagged.

Output: `transcript.txt` + `transcript.source` (`website|description|subs|auto_subs|whisper`).

---

## 6. Stage 3: Extract (LLM → structured recipe)

Put all the sources in one prompt, labeled and ordered by trust:

```
## Website recipe (schema.org)      ← if any
## Video title
## Video description / caption
## Transcript (source: whisper)
```

Ask the LLM for **structured output** (JSON schema enforced) that matches this model:

```python
class ExtractedRecipe(BaseModel):
    is_recipe: bool                 # false for vlogs, ads, Q&A → skipped, logged
    name: str
    description: str                # 1–2 sentences, your voice
    servings: float | None
    yield_text: str | None          # "12 cookies"
    prep_minutes: int | None
    cook_minutes: int | None
    total_minutes: int | None
    ingredient_sections: list[IngredientSection]   # title optional ("For the sauce")
    #   each line is ONE ingredient as a human would write it: "2 cups all-purpose flour, sifted"
    instructions: list[Step]        # each step: optional title + text
    notes: list[str]                # tips, substitutions, storage
    language: str
    source_confidence: float        # 0–1, the model's own estimate of how complete this is
    missing_info: list[str]         # e.g. ["quantities not stated for spices"]
```

Rules in the prompt:

- **Never invent quantities.** If the video says "some salt", output `salt, to taste`.
- Normalize ingredient lines into the `qty unit food, prep note` form. This shape gives the Mealie parser in stage 5 the best chance.
- Keep the original language, or translate to a configured target language (decision needed).
- Fold "Ingredients:" lists from the caption in verbatim when they exist.

**Model:** a Claude model through the Anthropic API with structured outputs. Haiku 5.5 is likely enough for most videos, with Sonnet 5.5 as a retry for low-confidence results. This is configurable, and any OpenAI-compatible model works too. I'll check the per-recipe cost on the pilot batch before the full run.

Output: `recipe.extracted.json`.

---

## 7. Stage 4: Tag (≥1 existing tag, required)

1. `GET /api/organizers/tags?perPage=-1` loads **all** existing tags (`id`, `name`, `slug`). Same for categories via `/api/organizers/categories` if you want them too.
2. Send the LLM the recipe and the **full tag list as an enum** in the JSON schema, so it can't return a tag that doesn't exist. Ask for 1–6 tags with a short reason each, ranked.
3. **Deterministic boosts / guards** in `config/tag_rules.yaml`. These are keyword rules, for example `chicken|turkey → "Poultry"`, `no meat/fish in foods → "Vegetarian"`, `total_minutes <= 30 → "Quick"`, and `platform == instagram → "Reel"` (if such tags exist).
4. **Validation:** at least one tag required. If the LLM returns none, retry once with a stronger prompt. If it still returns none, apply the configured fallback tag (for example `To Review`) and add the recipe to the review queue.
5. **New tags:** off by default. Suggested new tags go into `suggested_tags.csv` for you to approve. After approval, they're created with `POST /api/organizers/tags` and stage 4 re-runs.

---

## 8. Stage 5: Parse ingredients (so they display properly)

This is the part the built-in import skips. Steps:

1. **Parse.** `POST /api/parser/ingredients`
   ```json
   { "parser": "nlp", "ingredients": ["2 cups all-purpose flour, sifted", "1 tsp salt", ...] }
   ```
   The response is a list of `ParsedIngredient { confidence: {average, quantity, unit, food, comment}, ingredient: RecipeIngredient }`. Mealie's parser already tries to match the food and unit against your existing database, so a matched food comes back **with an `id`**.
   - `parser` options: `nlp` (CRF model, fast, free, English-focused), `brute` (rule-based), and `openai` (uses the AI provider configured in Mealie, which is better for non-English text or messy lines).
2. **Low-confidence retry.** For items with `confidence.average < 0.75` (tunable), or with no food detected, re-parse that line with `parser: "openai"` if your Mealie has an AI provider. Otherwise our LLM does it, constrained to output `{quantity, unit, food, note}`.
3. **Resolve IDs.** `PUT/PATCH /api/recipes/{slug}` does **not** auto-create foods or units (only the zip importer does), so every food and unit must be an existing record:
   - Load all foods and units once: `GET /api/foods?perPage=-1`, `GET /api/units?perPage=-1` (names, plural names, aliases).
   - Match locally: exact → plural/alias → normalized (lowercase, singular) → fuzzy (`rapidfuzz` ≥ 92).
   - Still unmatched: **create** with `POST /api/foods` `{ "name": "...", "pluralName": null }` / `POST /api/units` `{ "name": "...", "abbreviation": "..." }`, and log the creation to `created_foods.csv` (default on, see question 6). Units are a short list, so we pre-seed common ones before the run.
   - Hold a per-run lock on creation so two recipes in parallel don't both create "garlic".
4. **Build the final ingredient objects:**
   ```json
   {
     "quantity": 2, "unit": {"id": "...", "name": "cup"},
     "food": {"id": "...", "name": "all-purpose flour"},
     "note": "sifted", "originalText": "2 cups all-purpose flour, sifted",
     "title": "For the dough",           // section header on first item of a section only
     "referenceId": "<uuid4>"
   }
   ```
5. **Optional:** link ingredients to steps (`recipeInstructions[].ingredientReferences[].referenceId`) by matching food names in the step text. This gives you the "ingredients used in this step" view.

---

## 9. Stage 6: Upload to Mealie

All calls use `Authorization: Bearer <MEALIE_API_TOKEN>` against `MEALIE_URL` (for example `http://localhost:9000`).

| Step | Call |
|---|---|
| Idempotency check | `GET /api/recipes?queryFilter=orgURL="<url>"`. If found, update instead of creating (or skip, depending on `--mode`). |
| Create shell | `POST /api/recipes` `{ "name": "..." }` → returns `slug` |
| Fill everything | `PATCH /api/recipes/{slug}` with `description`, `recipeServings`, `recipeYield`, `prepTime`/`performTime`/`totalTime`, `recipeIngredient` (stage 5), `recipeInstructions` (`[{id,title,summary,text,ingredientReferences}]`), `notes`, `tags` (`[{id,name,slug}]`), `recipeCategory`, `orgURL` (canonical video URL), `extras` (`{"pipeline_source": "...", "platform": "...", "video_id": "...", "also_on": "..."}`) |
| Image | `POST /api/recipes/{slug}/image` `{ "url": "<thumbnail url>" }`, or for exported files `PUT /api/recipes/{slug}/image` (multipart upload of `thumb.jpg`) |
| Optional: attach video | `POST /api/recipes/{slug}/assets` (multipart). Off by default because 900 videos would fill your disk. |
| Verify | `GET /api/recipes/{slug}`: check that every ingredient has `food.id`, there's ≥1 tag, and there's ≥1 instruction. Otherwise mark `needs_review`. |

**Exact field names** (camelCase aliases) are checked against your instance's `/docs` OpenAPI page in the pilot, so the client is generated or validated against **your** version.

---

## 10. Stage 7: Review and reporting

- `report.csv` has one row per video: status, source used, transcript source, tags assigned, ingredient parse confidence (min and avg), number of foods created, Mealie URL.
- **Review queue** criteria: `is_recipe == false`, `source_confidence < 0.6`, any ingredient without a food, fallback tag used, or an ingredient line with no quantity that isn't "to taste". These recipes also get a `To Review` tag in Mealie (if you agree), so you can filter them in the UI.
- After the run: `GET /api/foods/empty` and `GET /api/organizers/tags/empty` to clean up orphans.

---

## 11. Open questions

1. **"A link on their website":** which of these do you mean?
   (a) The video description links to **your own recipe website**, and we should scrape the recipe from there. (If so, what's the domain?)
   (b) Just "the platform's website", meaning grab the description from the video page.
   (c) Something else?
2. **Whose videos are these?** Are they **your own accounts** (then official data exports are the best route for Instagram and Facebook), or someone else's / saved posts (then we need yt-dlp + cookies)?
3. **Is it the same recipes on all three platforms?** Is it about 300 unique recipes posted 3 times, or about 900 different ones? This decides whether dedupe is central.
4. **Language** of the videos, and the language you want the recipes stored in.
5. **Hardware:** do you have an NVIDIA GPU (then local Whisper is free), or should we use Groq or OpenAI? Which LLM API keys do you already have (Anthropic, OpenAI, other)?
6. **Foods and units:** is it OK to auto-create missing foods and units in Mealie (logged to CSV), or should unknown ones go to a review list first?
7. **Tags:** is it OK to add a `To Review` tag for uncertain recipes? Should the pipeline also set **categories** and **tools**, or only tags? Is it allowed to *suggest* new tags?
8. **Mealie version and setup:** which version are you running (Settings → About), and is it on Docker at `localhost:9000`? Do you already have an AI provider configured in Mealie? That would allow `parser: "openai"`.
9. **Existing recipes:** are some of these videos already imported (badly)? Should the pipeline **update** them (matched by `orgURL`) or skip them?
10. **Image:** is the video thumbnail fine as the recipe image?

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
  src/mealie_pipeline/
    cli.py                 # `mp discover|fetch|transcribe|extract|tag|parse|upload|report|run --limit 20`
    db.py                  # SQLite state
    sources/{youtube,instagram,facebook,website}.py
    transcribe/{subs,faster_whisper,groq,openai}.py
    extract/{prompt.py,schema.py,llm.py}
    mealie/{client.py,foods_units.py,tags.py}
    stages/*.py
  data/                    # git-ignored artifacts
  tests/                   # fixtures: sample captions, transcripts, parser responses
```

---

## 14. Milestones

1. **M0 (setup):** answer the questions, add tokens to `.env`, run a smoke test against Mealie (`GET /api/app/about`, list tags, parse one ingredient).
2. **M1 (YouTube pilot):** 10 YouTube videos end-to-end in dry-run, then write to Mealie. You review them in the UI.
3. **M2 (Instagram and Facebook ingest):** parse the exports or Graph API data, plus cross-platform dedupe. You review the dedupe CSV.
4. **M3 (full pilot):** 20 mixed videos. Tune the prompt, tag rules and confidence thresholds.
5. **M4 (full run):** all videos in batches of 50, with a report after each batch.
6. **M5 (cleanup):** work the review queue, merge duplicate foods (`PUT /api/foods/merge`), remove empty tags.

---

### Sources

- Mealie source v3.28.0: `mealie/routes/recipe/recipe_crud_routes.py`, `mealie/routes/parser/ingredient_parser.py`, `mealie/services/recipe/import_workflow/*`, `mealie/services/recipe/recipe_service.py`, `mealie/schema/recipe/*`. https://github.com/mealie-recipes/mealie
- Mealie AI providers docs: https://mealie.io/documentation/getting-started/installation/ai-providers/
- Mealie migration guide (v3.23 AI workflow): https://mealie.io/contributors/developers-guide/migration-guide/
- Groq speech-to-text: https://console.groq.com/docs/speech-to-text
- Instagram Media API reference: https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media
- yt-dlp releases (Instagram extractor rework mid-2026): https://github.com/yt-dlp/yt-dlp/releases
- Pricing figures are approximate (third-party summaries, 2026). Check them on provider pages before committing.
