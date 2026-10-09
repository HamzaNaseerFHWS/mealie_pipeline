# Mealie is storage only

Mealie's own "Import with AI" downloads and transcribes videos, but it stores ingredients as unparsed notes, tags optionally (and silently fails), sees only 200 tags, and never follows recipe-website links. The user found its transcripts not good enough either. So the pipeline does all collecting, scraping, transcription, extraction, ingredient parsing, tagging and verification itself, and calls Mealie only to read the Mealie Catalog and to write finished, verified recipes. Don't "simplify" by calling `/api/recipes/create/*` or `/api/parser/*`.
