# 37: Uploads that fail with "Recipe already exists"

**What to build:** About 35 uploads failed with `PATCH /api/recipes/<slug>-1 -> 400 {"detail":{"message":"Recipe already exists"}}` (26 on YouTube, 9 on Instagram). Mealie refuses a recipe whose name is already taken, often by a recipe from the name-list import. Find out why the pipeline's own "already in Mealie" check did not catch them, and handle the clash:

1. Decide per case from the existing recipe's `orgURL` and name: the same recipe (skip and record `already_in_mealie`), or a different recipe with the same name (upload under a distinguishing name, for example "Name (Channel)").
2. A report `reports/upload_clashes.csv`: the new item, the existing Mealie recipe, the decision.
3. Never overwrite an existing recipe without the user's go-ahead.

**Blocked by:** None

**Status:** ready-for-agent

**Read first:** `src/mealie_pipeline/pipeline.py` (`_upload`), `adapters/mealie_http.py`, `existing_links.py`, tickets 22 and 18, `logs/upload.log` (the failures).

- [ ] Seam test against the fake Mealie server: a same-name recipe is either skipped (same source) or gets a distinguishing name (different source); no duplicate and no overwrite.
- [ ] The failed items resolve (re-run, then the report lists each decision).

**Manual check (user):** open `reports/upload_clashes.csv` and confirm the decisions.
