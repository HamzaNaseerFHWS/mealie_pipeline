# Mealie video recipe pipeline: plan and spec

**Status:** Draft v0.5 (input is your saved lists on YouTube, Instagram and Facebook; own collector, classifier, scraper, parser and verification; Mealie is storage only). Needs answers to the [open questions](#11-open-questions) before build starts.
**Goal:** Give the pipeline links to your **saved playlists / collections** on YouTube, Instagram and Facebook (about 300 items each). It collects every video URL, keeps only real **recipe** videos (no restaurant ads, places to visit or product promos), and imports them into a self-hosted Mealie instance as clean recipes. Each recipe should have parsed ingredients (quantity, unit and food all linked) and at least one existing tag.

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
 0a.COLLECT ─▶ 0b.CLASSIFY ─▶ 0c.DEDUPE ─▶ 1.SCRAPE ─▶ 2.TRANSCRIBE ─▶ 3.EXTRACT ─▶ 4.PARSE ─▶ 5.TAG ─▶ 5b.VERIFY ─▶ 6.UPLOAD ─▶ 7.REVIEW
 saved-list    recipe vs      same recipe  our own     own STT,       LLM with      own         closed    checks +      Mealie API    report +
 links ⇒ all   restaurant/    across lists scraper:    only if        evidence      ingredient  list,     score gate    (storage      review
 video URLs    ad/travel      & platforms  video page  needed         quotes        parser +    ≥1 tag    fail ⇒ retry  only) +       queue
 (yt-dlp /     (rules + LLM,  + already in + website                              food/unit             or review     read-back
 Playwright)   you override)  Mealie                                                resolve                             check
            all stage outputs cached on disk + state in SQLite; every stage re-runnable on its own
```

**Design principles**

- **Every stage is resumable and idempotent.** State lives in `pipeline.db` (SQLite) with one row per video and a `stage` / `status` / `error` column. Raw artifacts are stored under `data/<platform>/<video_id>/`. Re-running the pipeline skips finished work, and you can re-run any single stage on its own (for example, re-tag everything after adding new tags).
- **The cheapest good source wins.** Use the website recipe first, then a description that contains a full recipe, then creator subtitles, then auto-subtitles, then Whisper. Transcription is the fallback, not the default.
- **Mealie stays the source of truth** for tags, foods and units. Nothing is hardcoded.
- **Dry-run mode** runs the whole pipeline and writes the final JSON without touching Mealie.
- **Start with a pilot of 20 videos** (a mix of platforms), check the results in the Mealie UI, tune, then run the rest.

**Stack:** Python 3.12, `uv`, `httpx`, **Playwright** (headless Chromium for JS-heavy pages and link-in-bio pages), `selectolax` / `trafilatura` (HTML → clean text), `extruct` + `recipe-scrapers` (structured data), `pydantic` v2, `yt-dlp` (+ `curl_cffi`), `faster-whisper`, `ingredient-parser-nlp`, `rapidfuzz`, `typer` CLI, `sqlite3`. Runs on **your laptop** (GTX 1650, Chrome). Mealie runs on **another PC on your Tailscale network**, reached at `MEALIE_URL=http://<mealie-pc>.<tailnet>.ts.net:9000` (MagicDNS name or `100.x.y.z` Tailscale IP).

---

## 2b. Decisions so far, and the compute / AI backends

**Decided with you (v0.4):**

| Topic | Decision |
|---|---|
| Instagram input | **All posts** in your saved items (`instagram.com/<you>/saved/all-posts/`) |
| Instagram / Facebook access | **Logged-in browser** driven by the pipeline, with a one-time manual login by you (`mp login`) |
| What gets imported | `recipe` **and** `recipe_partial` (sauces, techniques), **drinks/cocktails count as recipes**, and **compilations are split** into one Mealie recipe per dish (see §6) |
| First test | We run the pipeline **together on one of your collections** (you'll send the link). That collection becomes the pilot and the source of the first test cases |
| Transcription | **Local on your GTX 1650** (free), see below |
| AI (classify / extract / parse / tag / verify) | **Your Claude Code subscription (Pro)** through the `claude` CLI. **OpenAI credits only as an emergency fallback**, off by default and capped |
| Where things run | Pipeline on **your laptop**. Mealie on **another PC**, reached over **Tailscale** |
| Browser | **Chrome**. The pipeline uses its own Chrome profile, see §3.1 |
| Languages | **English → English**, **German → German**, **Urdu/Hindi → ingredients in English, recipe text in romanized Urdu/Hindi**. Details in §2c |
| Multi-recipe videos | Each recipe in a video is **extracted, checked, tagged and saved on its own**. Details in §6.1 |

### Local transcription on a GTX 1650 (4 GB VRAM, no tensor cores)

- **Engine:** `faster-whisper` (CTranslate2). The GTX 1650 has compute capability 7.5, which supports `float16`/`int8_float16`. It has no tensor cores, so it gains less from fp16 than newer cards, but it still runs many times faster than the CPU.
- **Model ladder (tried in order, picked once by a benchmark on your laptop):**
  1. `large-v3-turbo` with `compute_type="int8_float16"`, about 1.6–2.5 GB VRAM. **Default.** This is the best quality that fits comfortably in 4 GB.
  2. `large-v3-turbo` with `int8`, if (1) runs out of memory or produces NaN/garbage on this card.
  3. `medium` / `small` with `int8_float16`, the last resort for speed.
  - Full `large-v3` is **not** used, because it doesn't fit reliably in 4 GB.
- **Settings:** `batch_size=1`, `beam_size=5` (drop to 1 if too slow), `vad_filter=True`, `condition_on_previous_text=False` (reduces repetition loops on music), `language` set when known.
- **One GPU job at a time.** Transcription runs as its own queue. Close games and browsers that use the GPU during long runs, because the 4 GB is shared with the display.
- **`mp bench-whisper`** (in M0) transcribes 3 sample videos with each ladder step and records speed, VRAM and quality. Expected throughput is roughly 5–15× real time, so ~22 h of audio worst case takes about **2–5 h**, and likely much less after skipping videos that have a website recipe or subtitles. Good for an overnight run.
- **Laptop care:** run plugged in. The queue is resumable, so closing the lid or a thermal slowdown loses nothing.
- **CPU fallback:** `int8` on CPU works if CUDA setup is a problem. It's slow but still fine overnight.
- **Emergency fallback:** OpenAI `gpt-4o-mini-transcribe` (about $0.003/min), only for videos where local transcription fails twice, and only when `--allow-openai` is set.

### AI backend: Claude Code subscription via `claude -p`

The pipeline never calls an API directly for Claude. It runs the **Claude Code CLI in non-interactive mode**, which uses your subscription login:

```bash
# --model: haiku for classification, sonnet for extract/verify
# --safe-mode: no CLAUDE.md, hooks, plugins or MCP; login and model still work
# --tools "": pure text in / JSON out, no file or shell access
# stdin: the labeled sources (max 10 MB)
claude -p \
  --model sonnet \
  --safe-mode \
  --tools "" \
  --system-prompt-file prompts/extract.md \
  --output-format json \
  --json-schema "$(cat schemas/extracted_recipe.json)" \
  --no-session-persistence \
  < work/<video_id>/llm_input.md
```

The result is in `.structured_output` of the JSON response, already validated against the schema. Pydantic validates it again on our side.

- **Do not use `--bare`:** bare mode ignores the subscription login and needs an API key.
- **Image input (OCR of on-screen text, phase 2):** the same call with `--tools "Read"`, run in a working directory that contains only the sampled frames.
- **Usage limits:** subscription usage is limited per time window. The `llm` module detects `rate_limit` errors (exit code + `api_retry`/result error), **pauses the queue until the window resets**, and resumes. Nothing is lost, because every stage is resumable.
- **Fewer, bigger calls to save usage:**
  - Classification is batched (about 20 items per call, Haiku).
  - Extraction, LLM ingredient parsing and tag selection happen in **one** Sonnet call per recipe.
  - Verification (LLM judge) is a second call, made only when the deterministic checks pass. That's about **2–3 calls per recipe**.
  - With ~300–600 recipes, the full run is spread over a few days of normal subscription limits. That's fine because `mp run` can be left running and resumes on its own.
- **Concurrency:** 1 `claude -p` process at a time (Pro), configurable.
- **Claude Pro specifics:**
  - Pro has the smallest usage allowance, and `claude -p` runs share it with your normal Claude Code / claude.ai use. So `mp run` has a `--window night` option that only sends AI calls in hours you choose, and it backs off as soon as a limit message appears.
  - **Usage-saving mode** is on by default for Pro:
    - Haiku is used for classification, and for the LLM ingredient parse of recipes that come from structured website data. That's the easy case, so most lines are already settled by the local parser.
    - The LLM judge (S7) is skipped for recipes that scored ≥ 90 on the deterministic checks.
    - Sonnet is used where accuracy matters: extraction from transcripts, multi-recipe splitting, Urdu/Hindi romanization.
    - The "retry with Opus" step becomes "retry with Sonnet at `--effort high`" unless Opus is available on your plan.
  - The pilot measures usage per recipe, so we'll know how many recipes fit in a 5-hour window before the full run. Expect the full run to take **several days to about a week**, unattended. Stages that don't need AI (collecting, scraping, transcribing) run at full speed in the meantime.
- **Terms of use:** this is personal, local, low-volume use of your own subscription through the official CLI. Anthropic's rules for scripted/Agent SDK use of subscriptions have been changing in 2026, so check the current Claude Code usage policy before the full run. If scripted use ever needs an API key, the backend switches to `ANTHROPIC_API_KEY` by changing config only.
- **Emergency fallback: OpenAI** (`backend: openai` for a single stage or item). It's only used when `--allow-openai` is passed, with a hard spend cap (`OPENAI_MAX_USD`, default $2) tracked in the SQLite DB. Every OpenAI call is logged in the report.

The backend is an interface (`llm.complete(prompt, schema, model_tier)`), so stages don't know or care which provider answered.

---

## 2c. Languages (English, German, Urdu/Hindi)

The language is detected **per recipe**, not per video or channel. Signals are: Whisper's language detection on the audio, the caption script (Latin / Devanagari / Nastaliq), and the website's `inLanguage` / `<html lang>`. Code-mixed Hinglish/Urdu-English is common, and is treated as Urdu/Hindi when the spoken instructions are mainly Urdu/Hindi.

| Source language | Recipe name and description | Ingredients (food, unit, note) | Instructions and notes | Mealie foods / units |
|---|---|---|---|---|
| **English** | English | English | English | English foods and units |
| **German** | German | **German** ("2 EL Olivenöl", "1 Zwiebel, fein gewürfelt") | German | **German** foods and units ("Zwiebel", "EL", "TL", "Prise", "Bund", "Zehe", "Msp.") |
| **Urdu / Hindi** | romanized ("Chicken Karahi") plus an optional English subtitle in the description | **English** ("2 tbsp ginger garlic paste", "1 cup yogurt") | **romanized Urdu/Hindi** in Latin script ("Pyaz ko golden hone tak bhoon lein…"), never Devanagari or Nastaliq | English foods and units, shared with English recipes |

**How each part is handled:**

- **Transcription:** Whisper writes Hindi in Devanagari and Urdu in Nastaliq script. The transcript is kept as-is, because it's the evidence for the grounding check (§9, H3). The **LLM** then writes the romanized text. The grounding check compares in the original script, so romanization can't break it.
- **Romanization style:** the common "Roman Urdu" spelling that creators use in captions (`pyaz`, `adrak lehsan`, `namak`, `bhoon lein`, `dum par rakhein`). Ingredient names in the steps are **English** too, so the steps match the ingredient list: "Ab chicken daal kar 5 minute bhoonein". The prompt includes a short style guide and examples, which you can edit in `prompts/style_roman_urdu.md`.
- **Desi ingredient names → English:** a reviewed glossary `config/glossary_desi.yaml` (`haldi → turmeric`, `dhania → coriander`, `kasuri methi → dried fenugreek leaves`, `besan → gram flour`, `dahi → yogurt`, `garam masala → garam masala`, …) is applied first. Where English has no good word, the common name stays (`garam masala`, `chaat masala`, `ghee`, `paneer`). The glossary grows with every reviewed recipe.
- **German ingredient parsing:** `ingredient-parser-nlp` is English-only, so German lines use the LLM plus a **rule-based German quantity/unit parser** (decimal commas, `½`, `1–2`, and units EL/TL/g/kg/ml/l/Prise/Bund/Zehe/Msp./Becher/Dose/Pck.) as the second engine for the agreement check (§7).
- **Foods in Mealie:** German recipes get **German food entries**, so ingredients display in German. To avoid duplicates, the English name is stored as an **alias**, and a `glossary_de_en.yaml` keeps the pairs consistent. English and Urdu/Hindi recipes share the English foods.
- **Whisper on Urdu/Hindi:** `large-v3-turbo` is weaker on Urdu/Hindi than on English/German. `mp bench-whisper` includes one Urdu/Hindi sample. If quality is poor, the options are:
  - (a) a per-language model choice, for example `large-v3` `int8` for `hi`/`ur`, if it fits in 4 GB on your card
  - (b) prefer YouTube's Hindi/Urdu subtitles when they exist
  - (c) OpenAI transcription for these only, with `--allow-openai`
- **Language tag:** if a matching tag already exists in Mealie (for example "German", "Pakistani", "Indian", "Desi"), it's added by rule. Otherwise it's only suggested.

---

## 3. Stage 0: Collect and classify (start from your saved lists)

**Input:** you give the pipeline **links to your saved lists**, and it finds every video URL in them by itself:

```bash
mp collect https://www.youtube.com/playlist?list=PLxxxx            # any YouTube playlist (public, unlisted, private, WL, LL)
mp collect https://www.instagram.com/<you>/saved/<collection>/<id>/ # an Instagram saved collection (or .../saved/all-posts/)
mp collect https://www.facebook.com/saved/?list_id=<id>             # a Facebook saved collection (or facebook.com/saved)
mp collect --file urls.txt                                          # plain list of video URLs (manual additions)
mp collect --sync                                                   # re-check all known lists, add only new items
```

Every list is stored in a `sources` table (URL, platform, last synced). `--sync` adds only new items, so you can keep saving videos and re-run the pipeline whenever you like.

### 3.1 Collectors (one per platform)

These are **saved** lists, so most of the videos come from **other creators**. Saved lists are private, so collecting them needs **your logged-in session**.

| Platform | Primary collector | Fallback | Notes |
|---|---|---|---|
| **YouTube** | `yt-dlp --flat-playlist -J <playlist url>`. Fast, and returns id, title, channel, duration and URL for every item. Private playlists, **Watch Later (`list=WL`)** and **Liked (`list=LL`)** need cookies. They come from the pipeline's own Chrome profile (below), exported as `cookies.txt`. | YouTube Data API v3 `playlistItems.list` with OAuth (works for your own private playlists, but **not** Watch Later). | Most reliable of the three. |
| **Instagram** | **Our own Playwright collector:** opens the collection URL in a **persistent browser profile** where you've logged in once, scrolls until no new tiles load, and harvests every `/p/<code>/` and `/reel/<code>/` link. Throttled to human speed (random scroll pauses of 1.5–4 s), capped per session, and it resumes where it left off. | (a) **Data export** (Accounts Center → Download your information → JSON → "Saved"), which contains saved posts and collections with their links. This is the safest route: no automation on your account. The exact file layout is confirmed on your first export. (b) `instaloader --login <you> :saved` (all saved posts, without per-collection grouping). | **yt-dlp can't list saved collections** (confirmed in the yt-dlp 2026.08.19 source: no saved/collection extractor). It *can* download each single `/reel/…` URL with your cookies, which stage 1 uses. |
| **Facebook** | **Our own Playwright collector** on `facebook.com/saved` / the collection page, scroll and harvest `/reel/<id>`, `/watch/?v=`, `/<page>/videos/<id>` and `fb.watch/…` links (expanded). | **Data export** "Saved items and collections" (JSON). | yt-dlp has no saved-items extractor either. Single `/reel/<id>` and video URLs work with cookies. |

**Login and session handling (YouTube, Instagram, Facebook), Chrome:**
- The pipeline does **not** read cookies from your everyday Chrome profile. On Windows, Chrome's app-bound cookie encryption breaks `yt-dlp --cookies-from-browser chrome`, and touching your main profile is risky anyway. Instead, Playwright launches **real Chrome** (`channel="chrome"`) with a **separate, persistent pipeline profile**. You log in to YouTube, Instagram and Facebook there **once**.
- `mp login instagram` / `mp login facebook` opens a **visible** Chromium window. You log in yourself, including 2FA, and the session is stored in `secrets/browser_profile/`. The pipeline never sees or stores your password.
- The same profile is exported to `cookies.txt` for yt-dlp in stage 1.
- If the session expires or a checkpoint/captcha appears, the collector **stops and asks you** to run `mp login` again. It never tries to get around it.
- **Account safety:** stay at about 300 items per platform. With slow scrolling that's a few minutes per collection, which is normal human behavior. The per-video metadata fetch in stage 1 is the bigger risk, so it's spread out (default ≤ 60 videos/hour per platform, which still finishes in an evening or two). An optional burner account isn't needed for saved lists, because they're tied to your account.

**URL normalization:** remove tracking parameters (`igsh`, `si`, `utm_*`, `mibextid`), expand `youtu.be`, `fb.watch` and `/share/` short links, map shorts to their canonical form (`/shorts/<id>` → video id), and store a **canonical key** `platform:video_id` so the same item from two lists is stored once.

### 3.2 Classify: is this a home-cookable recipe video?

Saved lists are full of things that aren't recipes. Each collected item is classified **before** any expensive work (download, transcription) happens.

**Metadata first:** the Instagram and Facebook collectors only see grid thumbnails, so each item first gets a **metadata-only** fetch (`yt-dlp --skip-download --dump-json --cookies cookies.txt <url>`): caption, uploader, hashtags, location, duration. For YouTube, `--flat-playlist` gives the title, and the full description comes from the same metadata call. This result is cached and reused in stage 1.

**Labels:**

| Label | Example | Action |
|---|---|---|
| `recipe` | "Crispy garlic chicken thighs in 20 min" | **process** |
| `recipe_partial` | "My secret sauce" (technique or single component) | process, flagged |
| `restaurant_or_place` | "Best ramen in Tokyo 📍", "You need to try this café", food tours | skip |
| `ad_or_product` | sponsored gadget/brand promos with no recipe, "use code X" | skip |
| `eating_or_review` | mukbang, taste tests, "rating every Costco snack" | skip |
| `not_food` | anything else that ended up in the list | skip |
| `uncertain` | not enough information | escalate (see below) |

**How it decides (3 tiers, cheapest first):**

1. **Metadata only** (title, caption/description, hashtags, channel name, duration, IG location tag). This is cheap and covers most items. The inputs are:
   - **Rule signals** (computed features, not decisions on their own):
     - *Pro-recipe:* "recipe", "ingredients", quantity + unit patterns, "how to make", cooking verbs, "full recipe on my site/link in bio", hashtags like `#recipe` / `#easyrecipes`.
     - *Anti-recipe:* a 📍 / location tag, addresses or opening hours, "located in", "visit", "menu", "reservation", "#foodie #[city]eats", prices in local currency, "ad" / "sponsored" / "paid partnership" / "use code".
   - **An LLM classifier** gets the metadata **and** the rule signals and returns `{label, confidence, reasons[]}` with structured output. Model: Claude Haiku via `claude -p --model haiku` (§2b). Batch about 20 items per call.
2. **If `uncertain` or confidence < 0.7:** fetch the video's subtitles, or transcribe **only the first 60 s** of audio, and classify again with that text.
3. **If still uncertain**, the item goes into `classify_review.csv` for you to decide (`mp review classify` shows the items one by one in the terminal and records your answers).

**You stay in control:**
- `classification.csv` lists every item with its label, confidence and reasons, plus an `override` column. Any change you make there wins on the next run.
- Default policy: only `recipe` (and optionally `recipe_partial`) go on to stage 1.
- **Accuracy check before the full run:** in the pilot, you label about 50 random items by hand and we measure the classifier against them. If precision or recall on `recipe` is below 95 %, we tune the rules and prompt before continuing.

### 3.3 Cross-platform deduplication

The same recipe often appears in several lists, or on several platforms (the creator posts a reel and a YouTube Short). After classification:
1. Exact duplicates (same canonical key) are merged automatically.
2. **Near-duplicates:** same creator (handle-matched across platforms) and similar title/caption (fuzzy ≥ 85 or embedding cosine ≥ 0.9). This is confirmed later by comparing extracted ingredient sets (food-level Jaccard ≥ 0.7).
3. One **canonical** item per group, preferring the one with the richest source: website link > full ingredient list in caption > YouTube (best subtitles) > others. The other URLs go to `extras.also_on` and a recipe note.
4. A recipe that **already exists in Mealie** (same `orgURL`, or same website URL, or a fuzzy name match + ingredient overlap) is skipped or updated, per `--mode`.

The output (`dedupe.csv`) can be checked and edited by hand.

---

## 4. Stage 1: Scrape (our own scraper, video page and website)

Mealie's scraper is not used. Our scraper gathers **every** piece of raw evidence for a video and saves it, so later stages and the verifier can always go back to the original source.

### 4.1 Video page

Saved under `data/<platform>/<id>/`:

| File | How |
|---|---|
| `info.json` | already cached by stage 0b (`yt-dlp --dump-json`, with `--cookies` for Instagram, Facebook and private YouTube) |
| `description.txt` | full description or caption, **not truncated** (the "…more" text is in `info.json`) |
| `pinned_comment.txt` | creators often post the recipe in a pinned comment. `yt-dlp --write-comments --extractor-args "youtube:max_comments=20"`, keeping only comments by the uploader |
| `subs.<lang>.vtt` | `--write-subs --write-auto-subs --sub-langs "en.*,<lang>"`. Creator subtitles and auto-subtitles are kept apart |
| `thumb.jpg` | `--write-thumbnail` |
| `video.mp4` / `audio.m4a` | only if stage 2 needs them (exports already contain the MP4) |

### 4.2 Website (the main source when it exists)

1. **Link discovery:** pull URLs from the description, the pinned comment and the channel "about" links.
   - Expand short links (`bit.ly`, `tinyurl`, `geni.us`) by following redirects with `httpx`.
   - **Link-in-bio pages** (`linktr.ee`, `lnk.bio`, `beacons.ai`, Instagram "link in bio") are opened in **Playwright** and their links collected. A link is picked by fuzzy-matching the video title against the link text or slug.
   - **Creator website discovery:** these are other creators' videos, so we keep a `creators` table (handle → website), filled from their channel "About" links, IG/FB bio links and earlier videos. One creator lookup serves all their saved videos.
   - **Site search fallback:** if a video has no link but the creator has a known recipe website, search that site for the video title (`/?s=<title>`, the WordPress REST API `/wp-json/wp/v2/posts?search=`, or `sitemap.xml`) and fuzzy-match titles (≥ 85). It's flagged `link_source=site_search` so the verifier is stricter.
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

| Engine | When | Cost |
|---|---|---|
| **`faster-whisper` `large-v3-turbo` `int8_float16` on your GTX 1650** | default (see §2b for the model ladder) | free |
| same, `int8` on CPU | CUDA problems | free (slow) |
| OpenAI `gpt-4o-mini-transcribe` | only after 2 local failures **and** `--allow-openai` | about $0.003/min, capped |

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

**Model:** Claude Sonnet via `claude -p --model sonnet --json-schema …` on your subscription (§2b). The same call also does the LLM ingredient parse (§7) and tag selection (§8), to save usage. A retry with `--model opus` is used for recipes that fail verification.

### 6.1 Multi-recipe videos (each recipe handled on its own)

Some videos contain several recipes: "5 meal-prep lunches", "3 chutneys", or a main dish plus a sauce or side. **Each one becomes its own Mealie recipe and goes through every later stage independently.**

1. **Detect.** The extraction call first returns a **recipe outline**: `recipes: [{title, start_ts, end_ts, website_url?}]`. The signals it uses are YouTube chapters, numbered lists in the caption ("1️⃣ … 2️⃣ …"), several links to different website recipes, and spoken transitions ("next up…", "doosri recipe…"). The outline is checked against the transcript timestamps, so segments can't overlap or go beyond the video length.
2. **Segment.** Each recipe gets **only its own slice** of the sources: its transcript segment (by timestamps), its caption block, and its own website page if one exists. Shared intro/outro text is given to all of them as context, but marked as shared.
3. **Extract, parse, tag and verify separately.** Each recipe gets its own extraction call, evidence, ingredient parse, tags and verification score. **Grounding (H3) only accepts quotes from that recipe's own segment**, which stops ingredients leaking from one dish into another.
4. **Independent outcome.** One recipe failing verification doesn't block the others. Each part has its own row in the DB (`item_key = platform:video_id#<n>`), its own status and its own review entry.
5. **Upload.** Each part is a separate Mealie recipe:
   - `orgURL` is the video URL **with the timestamp** of that recipe (`…watch?v=ID&t=754s` on YouTube, the plain URL elsewhere). This keeps it unique per part.
   - `extras`: `{video_key, part: 2, of: 5, siblings: [slugs]}`.
   - A note links the sibling recipes ("Also in this video: Mint Chutney, Tamarind Chutney").
   - **Image:** the website image if there is one, otherwise a **frame grabbed at that recipe's start time** (`ffmpeg -ss <start_ts> -frames:v 1`), so the 3 chutneys don't all get the same thumbnail.
6. **Sub-recipes:** "biryani + raita served with it" counts as 2 recipes. A component used *inside* the main dish ("for the marinade") stays a **section** of one recipe, not a separate recipe. The prompt explains the difference with examples.
7. **Dedupe and idempotency** work per part (`video_key#n`), so re-runs update the right recipe, and a part saved separately elsewhere (for example the chutney also posted on its own) is matched to its own recipe.

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

All calls use `Authorization: Bearer <MEALIE_TOKEN>` against `MEALIE_URL` (your Mealie PC over Tailscale, for example `http://mealie-pc.tailXXXX.ts.net:9000`). Timeouts and retries are set for network calls, and image uploads are retried on connection drops.

| Step | Call |
|---|---|
| Idempotency | Primary key is `extras.item_key` (`platform:video_id#n`), tracked in the local DB together with the Mealie slug. Fallback lookup: `GET /api/recipes?queryFilter=orgURL="<url>"`. If found, update (or skip, per `--mode`). |
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

Answered: Instagram = all posts · logged-in browser OK · partial recipes, drinks and multi-recipe splitting included · pilot on one of your collections · GTX 1650 + Claude Pro, OpenAI only as an emergency fallback · Mealie on another PC over Tailscale · Chrome · languages per §2c.

Still open:

1. **The pilot collection link**, whenever you're ready.
2. **Laptop OS:** Windows, Linux or macOS? This affects the CUDA install and how `mp login` opens Chrome.
3. **Mealie address:** what's the Tailscale name or IP and port of the Mealie PC (for example `http://mealie-pc:9000`)? Mealie's `BASE_URL` doesn't matter for the API, but links in the report use whatever you give me.
4. **German foods:** OK to create German food entries (with English aliases) so German recipes display in German? The alternative is one shared English food list, but then German recipes would show "onion" instead of "Zwiebel".
5. **Roman Urdu/Hindi examples:** if you have 2–3 captions written in the romanization style you like, send them and they become the style examples in the prompt.
6. **Foods and units:** is it OK to auto-create missing foods and units in Mealie (logged to CSV), or should unknown ones go to a review list first?
7. **Tags:** is it OK to add a `To Review` tag for uncertain recipes? Should the pipeline also set **categories** and **tools**, or only tags? Is it allowed to *suggest* new tags?
8. **Mealie version:** which version are you running (Settings → About)? It's needed only for API field names, since nothing of Mealie's AI or parser is used.
9. **Existing recipes:** are some of these videos already imported (badly)? Should the pipeline **update** them (matched by `orgURL`) or skip them?
10. **Image:** website image first, otherwise the video thumbnail. Is that OK?
11. **Strictness:** recipes that fail verification are **not uploaded** and stay in the review queue. Or would you rather they get uploaded with a `To Review` tag?

---

## 12. Access setup checklist

| What | How | Env var |
|---|---|---|
| Saved lists | A list of your saved-list URLs (YouTube playlists incl. `WL`/`LL`, Instagram collections, Facebook saved collections) in `config/sources.yaml` | — |
| Browser login (IG/FB, private YT) | `mp login instagram` / `mp login facebook` / `mp login youtube`, a one-time manual login in a visible browser. The session is stored locally in `secrets/browser_profile/` and exported to `cookies.txt` for yt-dlp | `BROWSER_PROFILE_DIR`, `YTDLP_COOKIES` |
| Mealie API token | Mealie → your profile → **API Tokens** → create. `MEALIE_URL` is the Mealie PC's Tailscale name/IP + port. `mp doctor` checks that it's reachable from the laptop | `MEALIE_URL`, `MEALIE_TOKEN` |
| YouTube | Nothing for public videos. Optional: Google Cloud project → enable YouTube Data API v3 → API key | `YOUTUBE_API_KEY` (opt.) |
| Instagram (optional fallback) | **Download your information** → JSON → include "Saved". Used if the browser collector gets blocked | `IG_EXPORT_DIR` |
| Facebook (optional fallback) | **Download your information** → JSON → "Saved items and collections" | `FB_EXPORT_DIR` |
| Transcription | NVIDIA driver + CUDA 12 runtime + cuDNN 9 (pulled in by `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`), then `faster-whisper`. Checked by `mp doctor` | — |
| AI | Claude Code installed and logged in with your subscription (`claude auth status` → `authMethod: claude.ai`). Checked by `mp doctor` | — |
| Emergency only | OpenAI API key, used only with `--allow-openai` | `OPENAI_API_KEY`, `OPENAI_MAX_USD` |
| Tools | `ffmpeg`, `uv`, Python 3.12, Claude Code CLI, `yt-dlp` (keep it updated, since platforms break it often); Playwright Chromium | — |

Secrets go in `.env` (git-ignored). `cookies.txt`, `secrets/` and exports are never committed. **`cookies.txt` is equivalent to being logged in to your account**, so keep it private and delete it when you're done.

---

## 13. Repo layout (proposed)

```
mealie_pipeline/
  PIPELINE_SPEC.md
  pyproject.toml
  .env.example
  config/
    sources.yaml           # your saved-list URLs
    settings.yaml          # thresholds, rate limits, languages, model names
    classify_rules.yaml    # pro/anti recipe keyword signals
    tag_rules.yaml
    glossary_desi.yaml     # Urdu/Hindi ingredient names → English
    glossary_de_en.yaml    # German ↔ English food pairs (aliases)
    site_selectors.yaml    # per-site recipe-card CSS selectors
    units.yaml             # unit synonym table → Mealie units
  src/mealie_pipeline/
    cli.py                 # `mp login|collect|classify|dedupe|scrape|transcribe|extract|parse|tag|verify|upload|report|run --limit 20`
    db.py                  # SQLite state
    collect/{youtube.py,instagram.py,facebook.py,browser.py,normalize.py}   # saved-list → video URLs
    classify/{signals.py,llm.py,review.py}                                  # recipe vs restaurant/ad/travel
    dedupe.py
    sources/{youtube,instagram,facebook}.py                                 # per-video metadata
    scrape/{links.py,fetch.py,structured.py,plugins.py,fallback_text.py}   # our own website scraper
    transcribe/{subs,faster_whisper,openai_fallback,ocr}.py
    llm/{base.py,claude_cli.py,openai_fallback.py,ratelimit.py}         # claude -p backend + emergency fallback
    extract/{prompt.py,schema.py}
  prompts/                 # system prompts per stage (classify.md, outline.md, extract.md, judge.md, style_roman_urdu.md)
  schemas/                 # JSON schemas passed to --json-schema
    parse/{nlp_en.py,rules_de.py,llm.py,reconcile.py,units.py,foods.py}                  # our own ingredient parser
    tag/{llm.py,rules.py}
    verify/{checks.py,grounding.py,judge.py,score.py}
    mealie/{client.py,catalog.py}                                         # storage + tag/food/unit lookup only
    stages/*.py
  data/                    # git-ignored artifacts
  tests/                   # saved real pages (HTML fixtures), captions, transcripts; golden recipes for regression
```

---

## 14. Milestones

1. **M0 (setup):** `mp doctor` (checks Python, ffmpeg, CUDA/GPU, `claude auth status`, Playwright, yt-dlp version, Mealie reachability), `mp bench-whisper` (picks the Whisper model for your GTX 1650), a `claude -p` smoke test with a JSON schema, and a smoke test against Mealie (`GET /api/app/about`, `/openapi.json`, list tags, foods and units, create and delete a test recipe).
2. **M1 (pilot on your collection, together):** you send one collection link. We collect it, classify it, and check the labels together. Then we build and tune the website scraper and ingredient parser on the recipe videos in it. You hand-check about 10 **golden recipes** (correct ingredients, quantities and tags), which become regression tests that every later change must pass.
3. **M1b (YouTube pilot):** collect one YouTube playlist (the easiest collector), classify it, then run 10 recipe videos end-to-end in dry-run with verification reports, then write to Mealie. You review them in the UI.
4. **M2 (collect and classify):** collectors for all 3 platforms (`mp login`, `mp collect`), URL normalization, and the classifier. You hand-label about 50 random items, and the classifier must reach ≥ 95 % on `recipe` before we continue. You review `classification.csv` and `dedupe.csv` for the full lists.
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
- Claude Code headless mode and CLI reference (`-p`, `--json-schema`, `--tools`, `--safe-mode`, `--bare`): https://code.claude.com/docs/en/headless · https://code.claude.com/docs/en/cli-reference
- faster-whisper: https://github.com/SYSTRAN/faster-whisper
- Instagram Media API reference: https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media
- yt-dlp 2026.08.19 source `yt_dlp/extractor/instagram.py`, `facebook.py` (no saved/collection extractors; single post/reel URLs supported)
- Instaloader `:saved` target: https://instaloader.github.io/basic-usage.html
- yt-dlp releases (Instagram extractor rework mid-2026): https://github.com/yt-dlp/yt-dlp/releases
- Pricing figures are approximate (third-party summaries, 2026). Check them on provider pages before committing.
