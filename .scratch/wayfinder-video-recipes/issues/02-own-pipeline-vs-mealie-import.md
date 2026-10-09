# 02: Use Mealie's built-in import, or our own pipeline?

Type: grilling
Status: resolved
Blocked by: none

## Question

Should the pipeline lean on Mealie's `create/url` / `create/ai` import and transcription, or do everything itself and use Mealie only as storage?

## Answer

Our own pipeline. Mealie is storage plus Catalog lookup only. The user found Mealie's import and transcripts not good enough, and the source review (Mealie v3.28.0) showed unparsed ingredients, optional and silent tagging, a 200-tag limit, and no website-link following. Recorded as `docs/adr/0001-mealie-is-storage-only.md`.
