# 18: One Mealie recipe per dish across lists, platforms and earlier imports

**What to build:** A `dedupe` stage after `classify`.
- **Grouping:** near-duplicate Videos are grouped (same Creator across platforms by handle similarity, title/caption fuzzy ≥ 85, upload dates within ±7 days). One **canonical** Video per group is chosen by richest Source: website link > full ingredient list in caption > YouTube > others. Only the canonical Video continues; the others are recorded as `also_on`.
- **After parsing:** the group is confirmed by food-level Jaccard ≥ 0.7 between the canonical recipe and any sibling that was processed anyway. Otherwise the group is split again.
- **Existing recipes:** recipes already in Mealie are matched by Item Key, `org_url`, website URL, or fuzzy name + ingredient overlap, and are skipped or updated per `--mode`.
- **Output:** `reports/dedupe.csv` lists the groups with an override column that always wins.

**Blocked by:** 05, 09

**Status:** ready-for-agent

**Read first:** `spec.md` module 14; `PIPELINE_SPEC.md` §3.3.

- [ ] Grouping and canonical choice are pure and table-tested with hand-made Video sets (same reel on Instagram and Facebook, a YouTube Short + long video, two different recipes by the same Creator on the same day → **not** merged).
- [ ] Override semantics are tested: the user splits a group in the CSV, and both Videos proceed.
- [ ] `also_on` URLs appear in the uploaded recipe's `extras.also_on` and a note.
- [ ] Pipeline-seam test: `FakeMealie` already holds a recipe with the same `org_url`. With `--mode skip` there's no write; with `--mode update` it is PATCHed.
