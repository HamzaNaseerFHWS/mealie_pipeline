# 23: Auto Sync Cycle: new saves reach Mealie with one command

**What to build:** `mp auto` runs one unattended **Auto Sync Cycle** (spec module 17). It re-syncs every Saved List that is due, processes only the unfinished Videos up to a cap, uploads what passes the Gate, and writes a short summary. It is the command the scheduled task (ticket 24) will run, and it is safe to start by hand at any time. It adds no new stages. It wires the existing collectors, Stage Runner, Usage Governor, Existing Link Set check and Uploader together under a lock, with per-platform failure isolation.

**Blocked by:** 21

**Status:** ready-for-agent

**Read first:** `spec.md` user stories 56–63 and module 17; modules 1, 2, 3 (`ListCollector`, `Notifier`), 14 and 16. Also read tickets 04, 15 and 16 for the collectors' cursors and caps, and ticket 22 for the Existing Link Set.

- [ ] **Lock:** `work/auto.lock` with PID and start time.
  - A second `mp auto` with a live lock exits 0 with "already running" and changes nothing.
  - A stale lock (dead PID, or older than `auto.stale_lock_hours`) is taken over and logged.
  - Pipeline-seam tests cover both cases.
- [ ] **Due lists** (pure, table-tested): a list is due when `now - last_synced >= auto.check_every[platform]`. Defaults: YouTube 6 h, Instagram 24 h, Facebook 24 h, in `config/settings.yaml`. A list that was never synced is always due, and `--force-sync` makes every list due.
- [ ] **Incremental early stop** (pure, table-tested): for newest-first collectors (Instagram, Facebook), enumeration stops after `auto.known_streak` (default 10) consecutive already-known Video Keys. The rule is applied to the iterator the collector yields, so collectors don't change. YouTube lists are listed in full, and only the set difference is new. Pipeline-seam test: a fake Instagram collector yields 4 new then 30 known Videos. The cycle stores 4 new Videos and stops pulling after 10 known ones (the fake records how many it served).
- [ ] **Processing cap:** at most `auto.max_new_per_cycle` (default 30) Videos enter `classify` per cycle, oldest-collected first. Unfinished items from earlier cycles (failed, paused on a usage limit, Mealie down) are resumed before new ones and count toward the cap. Pipeline-seam test with 45 new Videos: 30 are processed, then 15 on the next cycle, and nothing is processed twice.
- [ ] **Failure isolation** (pipeline-seam tests, one per case):
  - (a) The fake Instagram collector raises `NeedsHumanLogin`. That platform is marked `needs_login` in `mp lists` and in the summary, and the YouTube lists are still synced and processed.
  - (b) `FakeMealie` is unreachable. Collection and every stage up to `verify` run, `upload` is left pending, and the next cycle with Mealie back uploads them.
  - (c) The LLM raises `UsageLimited`. The cycle stops AI work, records the items as pending and exits cleanly, without sleeping until the reset. Non-AI stages still run in this cycle.
- [ ] **Removal is never propagated:** a Video missing from a re-synced list is marked `unlisted` for that list. Its Stage Records and its recipe in `FakeMealie` are unchanged (test).
- [ ] **Summary:**
  - `reports/auto/<YYYYMMDD-HHMM>.md` lists, for each list, synced/skipped and why, then new Videos, uploaded recipes with Mealie links, Review Queue additions, and items needing the user.
  - `reports/auto/history.csv` gets one row per cycle, with columns `started, finished, lists_synced, new_videos, uploaded, review, skipped_existing, errors, needs_user`.
  - A pipeline-seam test asserts both files after a mixed cycle.
- [ ] **Notifier port:** a fake for tests, plus a real Windows toast implementation. Without a Windows desktop session it falls back to doing nothing, and that never fails the cycle.
  - It is called when uploads happened (if `auto.notify_on_upload`), on `needs_login`, on new Review Queue items, and when Mealie has been unreachable for 2 or more cycles in a row.
  - It is called at most once per cycle, with one combined message.
  - Tested with the fake.
- [ ] **`mp auto --dry-run`** behaves like `mp run --dry-run`: payloads go to `work/` and Mealie isn't touched.
- [ ] `mp status` shows the last cycle's time and outcome, and when each list is next due.

**Manual check on the laptop (user):**
1. With the lists from the full run registered, save one new recipe Video to a YouTube playlist and one to Instagram.
2. Run `uv run mp auto --force-sync`.
3. Check that both appear in Mealie, that `reports/auto/` has a summary with their links, and that a toast appeared.
4. Run `uv run mp auto` again right away. It should do nothing, because no list is due.
5. Start two `mp auto` in two terminals. The second should say "already running".
