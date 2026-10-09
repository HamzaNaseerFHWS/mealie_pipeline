# Ticket: Mealie upload stage — push self-parsed recipe, image & tags via API

## Parent spec

Mealie video → recipe import pipeline (link/number to be filled in by parent spec).

## Context

Mealie's built-in AI recipe parser gives poor results for video recipes. The pipeline does its own parsing: download the video, get the transcript, then extract a recipe with our own LLM. This ticket covers the **last stage only**: taking the already-structured recipe and pushing it into Mealie through its REST API. That includes the recipe image (the video thumbnail or a chosen frame) and tags generated from the transcript.

Mealie's AI and URL scraping are not used at all. Mealie only stores what we send.

## What to build

A `MealieClient` module (or similar) that takes a `ParsedRecipe` from the upstream parsing stage and:

1. Creates the recipe in Mealie from a schema.org `Recipe` JSON-LD object we build ourselves.
2. Sets the recipe image to our own thumbnail or frame (file upload preferred, URL as fallback).
3. Makes sure the recipe's tags and categories exist in Mealie and are attached to the recipe.
4. Returns the Mealie slug and URL of the created recipe so the pipeline can log it or report it.

## API reference (verified against Mealie `mealie-next` source + demo OpenAPI, nightly)

Auth: `Authorization: Bearer <token>`. Create the token in Mealie under User Profile → API Tokens. Base URL: `<MEALIE_URL>/api`.

### Create the recipe: primary path (JSON-LD)

`POST /api/recipes/create/html-or-json` returns the slug (string).

```json
{
  "data": "<schema.org Recipe JSON-LD, serialized as a STRING>",
  "url": "https://youtube.com/watch?v=VIDEO_ID",
  "includeTags": true,
  "includeCategories": true
}
```

- `data` must be a JSON **string**, not a nested object. If it starts with `{`, Mealie treats it as JSON-LD.
- No AI runs on this path. Mealie maps the schema.org fields directly.
- `image` (string, list, or `{url}`): Mealie downloads the first entry and stores it as the recipe image.
- `keywords` (comma-separated string or list) become **tags** when `includeTags: true`. Tags that don't exist yet are created automatically.
- `recipeCategory` becomes **categories** when `includeCategories: true`.
- Ingredients are imported as plain text lines. They are not split into quantity, unit and food.

Example JSON-LD payload, before it is serialized into a string:

```json
{
  "@context": "https://schema.org",
  "@type": "Recipe",
  "name": "Garlic Butter Noodles",
  "description": "…",
  "image": "https://i.ytimg.com/vi/VIDEO_ID/maxresdefault.jpg",
  "recipeYield": "2 servings",
  "prepTime": "PT10M",
  "cookTime": "PT15M",
  "totalTime": "PT25M",
  "recipeIngredient": ["200g noodles", "3 cloves garlic"],
  "recipeInstructions": [{ "@type": "HowToStep", "text": "Boil noodles…" }],
  "keywords": "quick, pasta, vegetarian",
  "recipeCategory": ["Dinner"]
}
```

### Create the recipe: alternative path (native Mealie format)

Use this path only if we later want structured ingredients (quantity, unit and food as separate fields):

1. `POST /api/recipes` with `{"name": "..."}` returns the slug.
2. `PATCH /api/recipes/{slug}` with Mealie-native fields: `description`, `recipeIngredient`, `recipeInstructions`, `prepTime`, `cookTime`, `totalTime`, `recipeYield`, `tags`, `recipeCategory`, `orgURL`, `nutrition`, `notes`, `extras`.

   `PUT` replaces the whole recipe and returns 422 if any required field is missing. Use `PATCH` for partial updates.

### Recipe image

| Method | Path | Body | Notes |
|---|---|---|---|
| `PUT` | `/api/recipes/{slug}/image` | multipart: `image` (file bytes), `extension` (e.g. `jpg`) | **Preferred.** Upload our own thumbnail or frame. |
| `POST` | `/api/recipes/{slug}/image` | `{"url": "https://..."}` | Mealie downloads it. Returns **400** on a non-image response, a disallowed domain, or a failed download, and the existing image is left unchanged. |
| `DELETE` | `/api/recipes/{slug}/image` | none | Removes the image. |

Thumbnail sources, all fetched by our pipeline rather than by Mealie:

- **YouTube:** `https://i.ytimg.com/vi/<VIDEO_ID>/maxresdefault.jpg` (fall back to `hqdefault.jpg` if it returns 404).
- **TikTok, Instagram or any other site:** `yt-dlp --write-thumbnail --skip-download <url>`, or the `thumbnail` field from `yt-dlp -J`.
- **Optional:** a better-looking frame grabbed with `ffmpeg`.

### Tags / categories / tools

| Method | Path | Body / params | Purpose |
|---|---|---|---|
| `GET` | `/api/organizers/tags?search=<q>` | pagination params | Find existing tags |
| `GET` | `/api/organizers/tags/slug/{slug}` | none | Look up a tag by its slug |
| `POST` | `/api/organizers/tags` | `{"name": "pasta"}` | Create a tag; the response includes `id` and `slug` |
| `PATCH` | `/api/recipes/{slug}` | `{"tags": [{"id","name","slug"}]}` | Set the tags on one recipe |
| `POST` | `/api/recipes/bulk-actions/tag` | `{"recipes": ["slug1"], "tags": [{"id","name","slug"}]}` | Add tags to many recipes at once |
| `POST` | `/api/recipes/bulk-actions/categorize` | `{"recipes": [...], "categories": [...]}` | Add categories to many recipes at once |

Categories and tools work the same way under `/api/organizers/categories` and `/api/organizers/tools`.

## Proposed flow

```
ParsedRecipe (from upstream LLM stage)
  → build schema.org JSON-LD (keywords = generated tags, recipeCategory = categories)
  → POST /recipes/create/html-or-json  {includeTags, includeCategories}  → slug
  → PUT  /recipes/{slug}/image  (local thumbnail/frame file)
       ↳ on failure: POST /recipes/{slug}/image {url}  → on failure: log, keep going
  → (optional) PATCH /recipes/{slug} with extra tags / notes / orgURL
  → return { slug, url: <MEALIE_URL>/g/<group>/r/<slug> }
```

## Acceptance criteria

- [ ] Given a `ParsedRecipe`, a recipe is created in Mealie with the correct name, description, ingredients, instructions, times, yield and source URL (`orgURL`).
- [ ] Mealie's AI and URL scraping are never called. Only `create/html-or-json` or `POST`/`PATCH /recipes` is used.
- [ ] The recipe image is set from our own thumbnail or frame file through `PUT /recipes/{slug}/image`.
- [ ] If the image upload fails, the URL fallback is tried. If that also fails, the recipe still exists, the failure is logged, and the pipeline does not crash.
- [ ] Tags generated from the transcript show up on the recipe. New tags are created and existing ones are reused, with no duplicates that differ only in case or spacing.
- [ ] Categories are applied the same way.
- [ ] The Mealie base URL and API token come from config or environment variables. The token is never logged.
- [ ] The client returns the slug and recipe URL. Non-2xx responses raise or log errors that include the response body.
- [ ] Re-running the same video doesn't silently create duplicates. Before creating, check for an existing recipe by source URL or name and skip or update it (pick one behaviour and document it).
- [ ] Integration test against a local Mealie container (or the demo instance) covering create, image upload and tags.

## Out of scope

- Downloading videos, transcription and LLM recipe extraction (upstream tickets).
- Generating tags from the transcript. This ticket consumes the tags; the upstream stage produces them.
- Structured ingredient parsing (quantity, unit and food) — that needs the native-format path.
- Meal plans, shopping lists and cookbooks.

## Open questions

- JSON-LD path vs native path: start with JSON-LD for simplicity, and move to native only if structured ingredients become a requirement?
- Tag normalisation rules (lowercase? singular? a fixed allowlist vs free-form tags from the LLM?).
- Duplicate handling when a video is processed again: skip, update, or create a new version?
- Which Mealie version is the target? Endpoints were verified against the nightly build, so check against the instance's `/docs` page.

## Blocked by

- Upstream recipe extraction stage, which produces `ParsedRecipe`, the tag list and the thumbnail.

## References

- Mealie API docs (Swagger): `<MEALIE_URL>/docs`, e.g. https://demo.mealie.io/docs
- Source: `mealie/routes/recipe/recipe_crud_routes.py`, `mealie/routes/organizers/controller_tags.py`, `mealie/routes/recipe/bulk_actions.py`, `mealie/services/scraper/cleaner.py`
