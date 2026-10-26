# 29: Run the slow stages with several workers

**What to build:** `mp run --workers N` (default from `run.workers` in `config/settings.yaml`, 1 = today's behaviour) runs the slow, independent stages for N items at the same time, so a batch of 50 names takes minutes instead of the better part of an hour. Real numbers from the first import (ticket 28): `find` costs about 25 s per name (search plus fetching up to 5 candidate pages), `extract` about 30 to 60 s per item (one `claude -p` call), and a batch of 50 took about 35 minutes with one worker.

**Which stages run in parallel, and which never do**
- **Parallel:** `find` (per request), `scrape` and `extract` (per item). They only read the web or call `claude`, and they write one row each.
- **Serial, always:** `parse` (it can create Foods and Units in Mealie, so two workers could create the same one), `tag`, `verify` and `upload` (Mealie writes, the Catalog, the Existing Link Set), and every write to `report`/`requests.csv`/`request_choices.csv`. These run on the main thread after the parallel part, per stage, as today.

**How it works**
- **Claiming:** the State Store hands out work with an atomic claim (`UPDATE ... SET status='running' WHERE status='pending'` and checking the row count), so no item is taken twice, also by two separate `mp run` processes. `running` already exists as a stage status. A crashed run leaves `running` rows behind: the next run resets rows that have been `running` for more than `run.stale_minutes` (default 30) back to `pending`.
- **Politeness is global, not per worker:** the ≥ 3 s gap between two queries to one search source (`find.search_delay_seconds`) and the per-domain fetch delay (ticket 06) are enforced by a shared limiter, so 5 workers do not hit `ddgs` or one site 5 times as often.
- **Claude calls are capped separately:** `claude.max_parallel` (default 2, never more than `--workers`) limits simultaneous `claude -p` processes, because they share one Pro quota. A `UsageLimited` from any worker stops all workers from starting new calls, lets the running ones finish and ends the run with the usual message (ticket 13 makes this a pause). The items that hit the limit stay `pending`, not `failed`.
- **Failures are per item:** one failing page or call marks that item `failed` and the others carry on.
- **Ctrl+C:** no new claims, in-flight items finish (or are put back to `pending` after a second Ctrl+C), reports are written.
- **Same result as one worker:** the outcome for each item does not depend on `--workers`; the run output and reports list items in a stable order (by request id / item key), not in completion order.
- **State Store:** opened in WAL mode with a 60 s lock wait since the ticket 03 follow-up, so workers can share the file. Each worker uses its own connection; no connection crosses threads.
- Do **not** use subagents or extra Claude sessions for this. A trial with 10 subagents searching in parallel was fast (about 40 s for 10 names) but used about 36,000 tokens per name and picked weaker pages (it did not open or score them). This ticket keeps the built-in page checks and costs no extra tokens.

**Blocked by:** None (tickets 03, 27 and 28 are done)

**Status:** in-progress

**Read first:** `src/mealie_pipeline/pipeline.py` (stage loop), `request_finder.py`, `store.py`, `scrape.py`; ticket 03's and 28's Comments; `docs/adr/`.

- [ ] `StateStore.claim(...)` is atomic: with 20 pending items and 4 threads (each with its own connection) every item is claimed exactly once; a second claim of the same item returns nothing. Tested.
- [ ] Stale `running` rows are reset to `pending` after `run.stale_minutes`, and only those. Tested with an injected clock.
- [ ] A shared rate limiter enforces the minimum gap per search source and per domain across all workers (injected clock; 4 workers, 8 queries, gaps never below the setting). Tested.
- [ ] Pipeline-seam test with the fakes: `--workers 4` over 20 requests gives the same statuses, chosen URLs, payloads and report rows as `--workers 1`, and `parse`/`upload` never run concurrently (the fake Mealie asserts it).
- [ ] One failing item does not stop the others; the failed one has its error recorded and the rest finish.
- [ ] `UsageLimited` from the fake LLM stops new calls, lets in-flight ones finish, leaves the affected items `pending` and ends the run with the usage-limit message.
- [ ] `claude.max_parallel` is respected: the fake LLM records its peak concurrency and it never exceeds the setting.
- [ ] Ctrl+C (simulated) writes the reports and leaves no item stuck in `running` after the next run starts.
- [ ] `run.workers`, `run.stale_minutes` and `claude.max_parallel` are in `config/settings.yaml` with comments; `--workers` overrides `run.workers`.
- [ ] `mp doctor`/README mention nothing new; `README.md` gets two lines about `--workers`.

**Manual check on the laptop (user):** with the 16 `needs_choice` requests still waiting, run `uv run mp run --stages find --limit 10 --workers 1`, note the time, then `--limit 10 --workers 4` on the next 10. Expect roughly 3 to 4 times faster, similar found/needs_choice proportions, no `database is locked` or duplicate search lines in the output, and no request left in `running` (`uv run mp requests`). Then a 20-item `mp run --workers 3` and open two of the imported recipes in Mealie.
