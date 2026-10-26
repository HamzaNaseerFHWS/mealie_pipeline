# 08: Verify every Recipe Part before it reaches Mealie

**What to build:** A `verify` stage between `tag` and `upload` that gives each Recipe Part a Quality Score.

**Hard checks:**
- H1: it is a recipe with a name
- H2: ≥ 2 ingredients and ≥ 1 step
- H3: Grounding. Every Evidence quote must occur in its cited Source. Ungrounded ingredients are dropped; more than 20 % dropped fails.
- H4: every ingredient has a Food or is an intentional note line
- H5: ≥ 1 tag

**Soft checks:**
- S1: website vs video agreement
- S2: ingredients ↔ steps
- S3: parse agreement (stub until ticket 09)
- S4: transcript quality
- S5: quantity sanity (stub until ticket 09)
- S6: plausible times and servings
- S7: LLM judge, only when the deterministic score is < 90

**Outcomes:**
- ≥ 80: upload
- 60–79: upload with the `To Review` tag (created once if missing)
- below 60 or a hard fail: one retry of extraction with the findings in the prompt at the `strongest` tier, then the Review Queue (`review/<item_key>.md` with Sources side by side) and **no upload**

**Blocked by:** 02

**Status:** in-progress

**Read first:** `spec.md` modules 12 and 15; `PIPELINE_SPEC.md` §9; wayfinder ticket `10-verification-gate.md`.

- [ ] Grounding is pure and table-tested: normalized fuzzy containment ≥ 90 (case, whitespace, punctuation, Unicode normalization), in the original script (Devanagari/Nastaliq quotes match Devanagari/Nastaliq Sources), and only against the cited Source's slice.
- [ ] The Quality Score is pure, with weights and thresholds in settings. It's tested with worked examples whose expected scores are written by hand in the test.
- [ ] Ingredients ↔ steps (S2) and plausibility (S6) are pure and table-tested.
- [ ] Judge call: `strong` tier, schema `{problems:[{severity, field, description}]}`. Blockers reduce the score per settings. It is skipped (no LLM call) when the deterministic score is ≥ 90, which the test checks through `FakeLLM`'s call log.
- [ ] Retry: findings go into the extraction prompt. At most one retry per Recipe Part per run. The attempt count is visible in `mp status` and the report.
- [ ] The review file shows the Video link, the label, each Source (trimmed), the extracted recipe, and every failed check with details.
- [ ] Pipeline-seam tests:
  - (a) a hallucinated ingredient (quote not in any Source) is dropped and the rest uploads
  - (b) a recipe with 1 ingredient goes to review, not Mealie
  - (c) a 70-score recipe uploads with `To Review`
- [ ] `report.csv` gains the score, the outcome and the failed check IDs.
