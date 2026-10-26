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

**Status:** done

**Read first:** `spec.md` modules 12 and 15; `PIPELINE_SPEC.md` §9; wayfinder ticket `10-verification-gate.md`.

- [x] Grounding is pure and table-tested: normalized fuzzy containment ≥ 90 (case, whitespace, punctuation, Unicode normalization), in the original script (Devanagari/Nastaliq quotes match Devanagari/Nastaliq Sources), and only against the cited Source's slice.
- [x] The Quality Score is pure, with weights and thresholds in settings. It's tested with worked examples whose expected scores are written by hand in the test.
- [x] Ingredients ↔ steps (S2) and plausibility (S6) are pure and table-tested.
- [x] Judge call: `strong` tier, schema `{problems:[{severity, field, description}]}`. Blockers reduce the score per settings. It is skipped (no LLM call) when the deterministic score is ≥ 90, which the test checks through `FakeLLM`'s call log.
- [x] Retry: findings go into the extraction prompt. At most one retry per Recipe Part per run. The attempt count is visible in `mp status` and the report.
- [x] The review file shows the Video link, the label, each Source (trimmed), the extracted recipe, and every failed check with details.
- [x] Pipeline-seam tests:
  - (a) a hallucinated ingredient (quote not in any Source) is dropped and the rest uploads
  - (b) a recipe with 1 ingredient goes to review, not Mealie
  - (c) a 70-score recipe uploads with `To Review`
- [x] `report.csv` gains the score, the outcome and the failed check IDs.

## Comments

### Built (2026-10-26)

A `verify` stage now sits between `tag` and `upload` (`STAGES = metadata, extract, parse, tag, verify, upload`); `upload` only takes parts whose `verify` is `done`.

- **Grounding** (`grounding.py`, pure): NFKC + case-fold + punctuation/whitespace stripped, fuzzy containment >= 90 (rapidfuzz `partial_ratio`). Letters and combining marks of every script are kept, so Devanagari/Nastaliq quotes match Devanagari/Nastaliq text and a translated quote does not match. Only the Source a quote cites counts.
- **Checks** (`verify.py`, `checks.py`, pure): H1-H5; S2 (ingredients <-> steps, using the Mealie food list for the "used but not listed" direction) and S6 (servings 1-50, total >= prep/cook, <= 24 h). S1 (`food_overlap`, Jaccard) exists but is not wired until a website Source exists (ticket 06). S3 and S5 are stubs until ticket 09, S4 until transcription: a check that does not apply is **left out of the average**, not counted as zero.
- **Quality Score** (`scoring.py`, pure): weighted average of the applicable components (H3 coverage, S1-S6) with weights in `config/settings.yaml` (`verify:`), minus the judge's penalties (blocker 30, major 15, minor 5). Thresholds: `>= 80` upload, `60-79` upload with `To Review`, below 60 or any hard fail -> retry then Review Queue. Hand-computed worked examples are in `tests/test_scoring.py` and the seam tests.
- **Judge (S7)**: task `judge`, `strong` tier, schema `{problems:[{severity, field, description}]}`, prompt `prompts/judge.md`. Skipped (no LLM call) when the score is >= 90 or a hard check failed. An unavailable judge (`LLMError`) never blocks a recipe; a usage limit still stops the run.
- **Retry:** at most once per Recipe Part per run: re-extract at `strongest` with "Your previous extraction failed verification ..." and the findings, then re-parse, re-tag, re-verify. `extraction_attempts` (1 or 2) is stored with the part's `verify` data, shown in `mp status` ("Gate: N in the Review Queue, N extracted a second time") and in `reports/report.csv` (new columns `verify_status`, `score`, `outcome`, `failed_checks`, `extraction_attempts`).
- **Review Queue:** Stage Record status `review` for `verify`, `review/<item_key>.md` with the Video link, label (shows "not classified yet" until ticket 05), each Source (trimmed to 3000 chars), the extracted recipe, dropped ingredients and every failed check. `mp run` prints `REVIEW ...` lines; this is not an error (exit code 0).
- **To Review tag:** looked up case-insensitively in the catalog, created once if missing (not in a dry run).
- **Ungrounded ingredients** are dropped from both the extracted recipe and its parsed list before upload. The parse stage also skips creating Foods/Units for them, so a hallucinated line leaves no junk Food in Mealie.
- **Dry run:** runs the deterministic checks only (no judge, no retry, no tag created); a part that would be held back is reported ("would go to the Review Queue ...") and gets no payload file.

### Deviations / notes

- Ungrounded **steps** are not dropped (that could break a recipe); more than 20 % of them ungrounded fails H3 like ingredients do.
- Migration 2 adds `recipe_parts.verify_json` (applied automatically when `pipeline.db` is opened).
- `mp reset verify` re-runs the Gate (and upload) for everything; use `--mode update` to PATCH recipes already in Mealie.

### Manual verification on the laptop (user)

1. `uv run mp add` a couple of YouTube recipe videos (ingredients in the description), plus one video that is not a recipe or has a sparse description.
2. `uv run mp run --dry-run`: payload files appear for good recipes; weak ones are reported as "would go to the Review Queue".
3. `uv run mp run`. Good recipes upload as before. For a held-back one open `review/<item_key>.md` and check that the Source and the extracted recipe are side by side and the failed check makes sense.
4. In Mealie look for the `To Review` tag on borderline recipes (score 60-79).
5. `uv run mp status` and `uv run mp report` show the Gate line and the new score/outcome columns.
6. Optional: lower `verify.upload_at` / raise `verify.judge_skip_at` in `config/settings.yaml` to see the judge and the `To Review` path on a normal recipe (each judge call costs one Claude call).
