# 03: Resumable batch runs with status, retry and reset

**What to build:** Make the pipeline safe to run over hundreds of Videos:
- `mp add --file urls.txt` adds many Videos at once.
- `mp run --limit N` processes a batch.
- `mp status` shows counts per stage and status, plus the last errors.
- `mp retry <key> [--stage]` and `mp reset <stage> [--failed-only]` re-run work.
- `mp report` writes `reports/report.csv`.

One Video failing never stops the others. Ctrl+C finishes the current entity and exits cleanly. Re-running continues exactly where it stopped. A Stage Runner owns ordering, prerequisites and failure isolation, and the stages from ticket 02 move onto it.

**Blocked by:** 02

**Status:** ready-for-agent

**Read first:** `spec.md` modules 1, 2, 15 and the CLI surface.

- [ ] The Stage Runner runs stages in dependency order, picks entities through `next_batch(stage, limit)`, and records `running → done|failed|skipped|review` with attempts and a last-error message. A failed entity doesn't block other entities, only its own later stages.
- [ ] Interruption safety: a test simulates an exception mid-batch and a cancel signal. Re-running processes only the unfinished entities, and no recipe is uploaded twice.
- [ ] `mp status` prints a per-stage table (rich), the totals of Videos and Recipe Parts, and the 10 most recent errors.
- [ ] `mp retry` and `mp reset` are covered by pipeline-seam tests: a failed upload is retried successfully after the fake is fixed, and resetting `extract` re-runs extract → upload with `--mode update` semantics.
- [ ] `reports/report.csv` has one row per Recipe Part: item_key, video URL, platform, status per stage, failure reason, Mealie slug and URL, created foods count, tags. The columns are documented in the report header or README.
- [ ] `mp add --file` ignores blank lines and `#` comments and reports duplicates and unsupported URLs without failing.

**Manual check on the laptop (user):** add 5 URLs from a file, run with `--limit 2` twice, then check that `mp status` and `reports/report.csv` reflect it.
