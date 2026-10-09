# Mealie is storage only

Mealie's own "Import with AI" downloads and transcribes videos, but it stores ingredients as unparsed notes, tags optionally (and silently fails), sees only 200 tags, and never follows recipe-website links. The user found its transcripts not good enough either. So the pipeline does all collecting, scraping, transcription, extraction, ingredient parsing, tagging and verification itself, and calls Mealie only to read the Mealie Catalog and to write finished, verified recipes. Don't "simplify" by calling `/api/recipes/create/*` or `/api/parser/*`.

## Considered Options

- **`POST /api/recipes/create/html-or-json` with our own schema.org JSON-LD** (proposed in a separate planning thread): rejected, for three reasons.
  1. Ingredients land as plain text lines, which is the exact problem this project exists to fix.
  2. The request still runs Mealie's scraper strategy chain (`recipe-scrapers` → **AI transcription** → AI → OpenGraph, per `mealie/services/scraper/recipe_scraper.py` in v3.28.0). If the JSON-LD isn't accepted and `url` is a video URL with an audio provider configured, Mealie downloads and transcribes the video itself. So "no AI on this path" is only conditionally true.
  3. `keywords` auto-create tags, which breaks "only existing tags".

  Native `POST /api/recipes` + `PATCH /api/recipes/{slug}` is the only create path.
