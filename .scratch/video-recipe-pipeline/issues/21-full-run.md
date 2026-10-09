# 21: Full run over every Saved List

**What to build:** A `mp run --all` mode that syncs every registered list and processes everything in batches of 50 (configurable). After each batch it writes `reports/report.html` and a batch summary (uploaded, upload-with-review, Review Queue, skipped by label, created foods/units, usage). It ends with cleanup hints: empty Foods/Tags in Mealie, likely duplicate Foods (fuzzy ≥ 95), and pending `suggested_tags.csv` entries. Then the user starts the real full run.

**Blocked by:** 10, 11, 12, 15, 16, 17, 18, 20, 22; wayfinder tickets `19-confirm-run-defaults.md` and `20-tag-taxonomy-review.md`

**Status:** ready-for-agent

- [ ] `--all` batching and per-batch summaries are tested at the pipeline seam with fakes across 2 batches, including a usage-limit pause between them.
- [ ] `report.html` is a single static file (no external assets), with a sortable table, filters by outcome, and links to Mealie and the review files.
- [ ] Cleanup hints come from `MealieGateway` lookups (empty foods/tags) and a pure duplicate-food finder (table-tested).
- [ ] A short `RUNBOOK.md` explains:
  - how to start, pause and resume
  - working the Review Queue (edit and `mp retry`)
  - re-syncing later
  - where every report lives
- [ ] **Hand-off to the user (ready-for-human after the code is done):** run `uv run mp run --all --window 23:00-07:00` on the laptop, and come back to the batch reports.
