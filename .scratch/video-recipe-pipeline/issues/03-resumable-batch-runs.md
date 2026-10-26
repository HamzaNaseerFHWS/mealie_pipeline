# 03: Resumable batch runs with status, retry and reset

**What to build:** Make the pipeline safe to run over hundreds of Videos:
- `mp add --file urls.txt` adds many Videos at once.
- `mp run --limit N` processes a batch.
- `mp status` shows counts per stage and status, plus the last errors.
- `mp retry <key> [--stage]` and `mp reset <stage> [--failed-only]` re-run work.
- `mp report` writes `reports/report.csv`.

One Video failing never stops the others. Ctrl+C finishes the current entity and exits cleanly. Re-running continues exactly where it stopped. A Stage Runner owns ordering, prerequisites and failure isolation, and the stages from ticket 02 move onto it.

**Blocked by:** 02

**Status:** done

**Read first:** `spec.md` modules 1, 2, 15 and the CLI surface.

- [x] The Stage Runner runs stages in dependency order, picks entities through `next_batch(stage, limit)`, and records `running → done|failed|skipped|review` with attempts and a last-error message. A failed entity doesn't block other entities, only its own later stages.
- [x] Interruption safety: a test simulates an exception mid-batch and a cancel signal. Re-running processes only the unfinished entities, and no recipe is uploaded twice.
- [x] `mp status` prints a per-stage table (rich), the totals of Videos and Recipe Parts, and the 10 most recent errors.
- [x] `mp retry` and `mp reset` are covered by pipeline-seam tests: a failed upload is retried successfully after the fake is fixed, and resetting `extract` re-runs extract → upload with `--mode update` semantics.
- [x] `reports/report.csv` has one row per Recipe Part: item_key, video URL, platform, status per stage, failure reason, Mealie slug and URL, created foods count, tags. The columns are documented in the report header or README.
- [x] `mp add --file` ignores blank lines and `#` comments and reports duplicates and unsupported URLs without failing.

**Manual check on the laptop (user):** add 5 URLs from a file, run with `--limit 2` twice, then check that `mp status` and `reports/report.csv` reflect it.

## Comments

### Built (2026-10-26)

- **Stage Runner** (`Pipeline.run`, from ticket 02) now owns the failure isolation: *any* exception from one entity is recorded as `failed` (unexpected ones are labelled `unexpected <Type>: ...`) and the batch carries on; a Claude usage limit still stops the run and leaves the item `pending`. A failed entity only blocks its own later stages. An entity left `running` by a crash is picked up again.
- **Interruption:** `run(should_stop=...)` is polled between entities. `mp run` installs a Ctrl+C handler that sets it (the item in progress finishes; a second Ctrl+C aborts). Tested with a stop signal mid-batch: the re-run uploads nothing twice and calls the LLM only for unfinished items.
- **`mp status`** (rich): stage x status table, Video and Recipe Part totals, the 10 most recent errors.
- **`mp retry <key> [--stage]`**: key is an item key or a Video Key. Without `--stage` it restarts at the earliest failed stage, so a failed upload does not repeat the paid extraction.
- **`mp reset <stage> [--failed-only]`** forgets that stage and every later one for all items. **`mp run --mode update`** then PATCHes the recipe that is already in Mealie (same slug) instead of skipping it; the default `--mode skip` leaves it alone.
- **`mp report`** writes `reports/report.csv` (columns documented in the README and in `reports.py`).
- **`mp add --file`**: blank lines and `#` comments ignored; duplicates and unsupported URLs are reported with a summary line and no longer make the command fail (exit code 0).

### Notes

- `--limit N` applies per stage, so `--limit 2` takes at most 2 Videos through each stage per run.
- The real Ctrl+C path (signal handler) is not unit-tested; the stop signal it sets is.

### Manual verification on the laptop (user)

1. Put 5 YouTube recipe URLs in `urls.txt` (add a `#` comment, a blank line, one duplicate and one non-YouTube URL).
2. `uv run mp add --file urls.txt` should report 5 added, 1 already known, 1 unsupported.
3. `uv run mp run --limit 2`, then `uv run mp status` (2 recipes through every stage, 3 Videos waiting). Run `--limit 2` again, then once more; all 5 end up in Mealie.
4. `uv run mp report`, open `reports/report.csv` in Excel: 5 rows, links and tags filled.
5. Press Ctrl+C during a run: it should say it is finishing the current item and stop; `mp run` continues.
6. If one fails: `uv run mp retry <item_key>` then `uv run mp run`.
7. Try `uv run mp reset extract` then `uv run mp run --mode update`: recipes are updated in place, none duplicated.

### State Store opened in WAL mode (2026-10-26)

`StateStore` now sets `journal_mode=WAL` and a 60 s lock wait (`BUSY_TIMEOUT_SECONDS`) so `mp run --stages find` and an import run can use `pipeline.db` at the same time (find works on `pending` requests, the import on `found` ones). New files `pipeline.db-wal` / `-shm` appear next to the database (git-ignored). Back up `pipeline.db` before the first run with this code: the file is converted once and older code cannot read it. Two stores writing at once are tested in `tests/test_store.py`.
