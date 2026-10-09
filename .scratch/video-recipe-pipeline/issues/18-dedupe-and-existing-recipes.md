# 18: One Mealie recipe per dish across lists, platforms and earlier imports

**What to build:** A `dedupe` stage after `classify`.
- **Grouping:** near-duplicate Videos are grouped (same Creator across platforms by handle similarity, title/caption fuzzy ≥ 85, upload dates within ±7 days). One **canonical** Video per group is chosen by richest Source: website link > full ingredient list in caption > YouTube > others. Only the canonical Video continues; the others are recorded as `also_on`.
- **After parsing:** the group is confirmed by food-level Jaccard ≥ 0.7 between the canonical recipe and any sibling that was processed anyway. Otherwise the group is split again.
- **Existing recipes:** matching recipes already in Mealie (incl. the user's earlier Instagram imports) is handled by ticket 22. This ticket reuses its Existing Recipe Index, so a near-duplicate group whose sibling is already in Mealie is resolved to that existing recipe instead of uploading a canonical copy.
- **Output:** `reports/dedupe.csv` lists the groups with an override column that always wins.

**Blocked by:** 05, 09, 22

**Status:** ready-for-agent

**Read first:** `spec.md` module 14; `PIPELINE_SPEC.md` §3.3.

- [ ] Grouping and canonical choice are pure and table-tested with hand-made Video sets (same reel on Instagram and Facebook, a YouTube Short + long video, two different recipes by the same Creator on the same day → **not** merged).
- [ ] Override semantics are tested: the user splits a group in the CSV, and both Videos proceed.
- [ ] `also_on` URLs appear in the uploaded recipe's `extras.also_on` and a note.
- [ ] Pipeline-seam test: an Instagram reel and its Facebook copy form one group. The Instagram reel is already in `FakeMealie` (from ticket 22's index), so neither Video is uploaded, and the Facebook URL is added to the report as `also_on` of the existing recipe (no write to it unless `--upgrade-existing`).
