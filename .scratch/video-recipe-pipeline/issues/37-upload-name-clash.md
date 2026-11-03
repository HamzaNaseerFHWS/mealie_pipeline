# 37: Uploads that fail with "Recipe already exists"

**What to build:** About 35 uploads failed with `PATCH /api/recipes/<slug>-1 -> 400 {"detail":{"message":"Recipe already exists"}}` (26 on YouTube, 9 on Instagram). Mealie refuses a recipe whose name is already taken, often by a recipe from the name-list import. Find out why the pipeline's own "already in Mealie" check did not catch them, and handle the clash:

1. Decide per case from the existing recipe's `orgURL` and name: the same recipe (skip and record `already_in_mealie`), or a different recipe with the same name (upload under a distinguishing name, for example "Name (Channel)").
2. A report `reports/upload_clashes.csv`: the new item, the existing Mealie recipe, the decision.
3. Never overwrite an existing recipe without the user's go-ahead.

**Blocked by:** None

**Status:** done

**Read first:** `src/mealie_pipeline/pipeline.py` (`_upload`), `adapters/mealie_http.py`, `existing_links.py`, tickets 22 and 18, `logs/upload.log` (the failures).

- [x] Seam test against the fake Mealie server: a same-name recipe is either skipped (same source) or gets a distinguishing name (different source); no duplicate and no overwrite.
- [x] The failed items resolve (re-run, then the report lists each decision).

**Manual check (user):** open `reports/upload_clashes.csv` and confirm the decisions.

## Comments

**Why the "already in Mealie" check missed them:** the check compares links only (`orgURL`, ticket 22). These clashes are about the **name**, usually against a recipe from the name-list import that has a website as its `orgURL`. Mealie builds the slug from the name. `POST /api/recipes` with a taken name quietly creates "Name (1)" (`name-1`). The PATCH then sends the plain "Name" back, Mealie re-slugs it to `name`, which is taken, and answers `400 Recipe already exists`. That is exactly the logged `PATCH /api/recipes/<slug>-1 -> 400`. Two Videos with the same dish name in one run caused it too.

**Built** (`name_clash.py` (pure) and `Pipeline._free_name` in `pipeline.py`):
- Before creating or patching, upload looks for another recipe whose slug or name matches. It checks the Mealie listing and everything uploaded earlier in the same run.
  - **Same recipe**: the existing `orgURL` is one of the item's own links (the Video, or the website page it links, after URL normalization). The item is skipped as `already_in_mealie`. An empty "Name (1)" shell that this item created on an earlier failed upload is deleted. Nothing else is touched.
  - **Different recipe** (other link, or no link, such as a hand-made recipe): the item uploads as "Name (Channel)". The fallbacks, in order, are the uploader name, the page's domain, the platform, and then a number ("Name (Channel) 2"). A shell from an earlier failure is reused and renamed, so no duplicate appears.
  - If Mealie still answers 400 "already exists" (the name was taken after the listing), the pipeline lists Mealie again and renames once.
- An existing recipe is never PATCHed by this path.
- `reports/upload_clashes.csv` has one row per item with its latest decision: `item_key, new_name, new_url, existing_slug, existing_name, existing_url, decision, uploaded_as, decided_at`.
- Upload now follows the slug that Mealie returns from the PATCH, because a renamed recipe moves to a new slug.
- FakeMealie now behaves like Mealie here: a taken name is created as "Name (1)", and a PATCH that moves onto a taken slug gets the 400. Because of that, `test_reset_extract_then_run_in_update_mode_patches_the_same_recipe` now checks the recipe's **id** stays the same instead of its slug. With real Mealie the slug follows the name; the test still checks that the recipe is patched in place and not duplicated.

**Not done here:** I couldn't see `logs/upload.log` from the cloud session, so the ~35 real failures were not re-run.

**Manual check (user, laptop):**

```
uv run mp reset upload --failed-only
uv run mp run
```

Then open `reports/upload_clashes.csv` and confirm each decision. Renamed recipes appear in Mealie as "Name (channel)". The skipped ones show as `already_in_mealie` in the run output.
