# 18: One Mealie recipe per dish across lists, platforms and earlier imports

**What to build:** A `dedupe` stage after `classify`.
- **Grouping:** near-duplicate Videos are grouped (same Creator across platforms by handle similarity, title/caption fuzzy ≥ 85, upload dates within ±7 days). One **canonical** Video per group is chosen by richest Source: website link > full ingredient list in caption > YouTube > others. Only the canonical Video continues; the others are recorded as `also_on`.
- **After parsing:** the group is confirmed by food-level Jaccard ≥ 0.7 between the canonical recipe and any sibling that was processed anyway. Otherwise the group is split again.
- **Existing recipes:** matching recipes already in Mealie (incl. the user's earlier Instagram imports) is handled by ticket 22. This ticket reuses its Existing Link Set, so a near-duplicate group whose sibling is already in Mealie is resolved to that existing recipe instead of uploading a canonical copy.
- **Output:** `reports/dedupe.csv` lists the groups with an override column that always wins.

**Blocked by:** 05, 09, 22

**Status:** done

**Read first:** `spec.md` module 14; `PIPELINE_SPEC.md` §3.3.

- [x] Grouping and canonical choice are pure and table-tested with hand-made Video sets (same reel on Instagram and Facebook, a YouTube Short + long video, two different recipes by the same Creator on the same day → **not** merged).
- [x] Override semantics are tested: the user splits a group in the CSV, and both Videos proceed.
- [x] `also_on` URLs appear in the uploaded recipe's `extras.also_on` and a note.
- [x] Pipeline-seam test: an Instagram reel and its Facebook copy form one group. The Instagram reel is already in `FakeMealie` (from ticket 22's link set), so neither Video is uploaded, and the Facebook URL is added to the report as `also_on` of the existing recipe (no write to it unless `--upgrade-existing`).

## Comments

**Built**
- `src/mealie_pipeline/dedupe.py` (pure): `similar` (Creator handle ratio ≥ 80, title fuzzy ≥ 85, upload dates within ±7 days; a missing date does not block), `find_groups`, `plan_groups` (canonical order: `canonical` override > member already in Mealie > member that already went on > richest Source website link > ingredient list in caption > YouTube > others, ties by lowest Video Key), `jaccard`/`confirmed` (≥ 0.7), and the `reports/dedupe.csv` reader/writer.
- New video stage `dedupe` (after `classify`, before `linkcheck`) in `pipeline.py`. It groups all classified Videos, not just new ones. Non-canonical Videos get Stage Status `skipped` with detail `also_on:<canonical key>` and never reach linkcheck, scrape or extract. Group state lives in those Stage Records, so there is **no schema migration**.
- Existing recipes: if a group member's Video Key is in the Existing Link Set (ticket 22), it becomes canonical, goes through `linkcheck` and is recorded `already_in_mealie`; its siblings cost nothing. Mealie is only listed when a group exists. With `--upgrade-existing` the `also_on` extras are merged into the old recipe; otherwise nothing is written to it.
- Upload: `extras.also_on` (list of URLs) plus an "Also posted on" note. `report.csv` has new `dedupe_status` and `also_on` columns. `mp run` prints `duplicate <key>: also on <canonical>`.
- Post-parse confirmation: a group member that had already been extracted before grouping (`sibling_of:`) is compared with the canonical by food-level Jaccard after `parse`. At ≥ 0.7 it is confirmed (`also_on`); under 0.7 the group is split again and a warning is reported.
- `reports/dedupe.csv` columns: group_id, video_key, url, platform, title, creator, role, canonical_key, reason, override. Override values: `split` (the Video goes on alone) and `canonical` (this Video is the canonical one). Overrides always win and stay in the file.
- Tests: `tests/test_dedupe.py` (table tests with hand-made Video sets, override semantics, Jaccard) and `tests/test_dedupe_seam.py` (Instagram reel and Facebook copy: one recipe with `also_on`; reel already in FakeMealie: no AI call, no write, Facebook URL is `also_on` in the report; `--upgrade-existing`; CSV split; Jaccard split). `tests/test_batch_runs.py` expected the report columns, which I updated for the two new ones.

**Deferred / notes**
- `mp add` accepts YouTube only, so the seam tests register Instagram and Facebook Videos straight in the store, as the collectors do. Nothing else changed there.
- Only the Video Key is matched against the Existing Link Set for grouping. A group's website-level match still happens in `linkcheck`, as in ticket 22.
- A Video that already went on (extracted or uploaded) is not folded retroactively when a group appears. It is checked after parsing instead.
- Handle similarity uses the normalized handle from `creators.creator_handle`. An empty handle never matches, so Videos without any uploader name are never grouped.

**Manual verification (on the laptop)**
1. `uv run mp run --stages metadata,classify,dedupe` on a real list that holds the same reel on Instagram and Facebook (or a YouTube Short plus the long video).
2. Open `reports/dedupe.csv`: the groups, canonical and `also_on` rows should look right. Put `split` in the `override` column of one row and run `uv run mp run`: both Videos should be processed.
3. Run `uv run mp run` for a group whose reel you already imported into Mealie: no AI calls, nothing new in Mealie, and `uv run mp report` shows the other platform's URL in `also_on` of the existing recipe's row.
4. For a freshly uploaded group, check in Mealie that the recipe's extras hold `also_on` and that the "Also posted on" note lists the other URL(s).
