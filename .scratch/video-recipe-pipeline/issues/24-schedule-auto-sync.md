# 24: Schedule Auto Sync with Windows Task Scheduler

**What to build:** `mp schedule install|remove|status` registers, removes and inspects one Windows Task Scheduler task, `mealie_pipeline auto sync`. The task runs `uv run mp auto --workspace <ws>` on the schedule from `auto.schedule` (default every 6 h), so new saves reach Mealie without the user doing anything (spec module 17, *Scheduling*).

**Blocked by:** 23

**Status:** ready-for-agent

**Read first:** `spec.md` user stories 58 and 61, module 17 and the `Scheduler` port in module 3; `README.md` / `RUNBOOK.md` from ticket 21.

- [ ] **Task spec builder** (pure, table-tested): settings plus the workspace path give the exact task definition. That is either the `schtasks.exe` argument list or the task XML, whichever the implementation picks. Write the choice in the Comments.
  - The action runs `uv` with an absolute path, the working directory is the repo, and `--workspace` is absolute.
  - The trigger is every N hours, or at fixed times of day, from `auto.schedule`.
  - "Run only when user is logged on", because the Chrome profile, `claude` login and Tailscale are per-user.
  - "Start the task as soon as possible after a scheduled start is missed".
  - "If the task is already running: do not start a new instance".
  - No wake-from-sleep, and a time limit of `auto.max_cycle_hours` (default 4).
  - Paths with spaces and non-ASCII user names are covered by the table.
- [ ] **`Scheduler` port:** the real implementation calls `schtasks.exe` through `subprocess` with an argument list and UTF-8 output, never a shell string. The fake keeps tasks in memory. The real one has a contract test against a stub `schtasks` executable placed first on PATH (same approach as the stub `claude` in ticket 13). The test asserts the exact arguments for install, remove and query.
- [ ] **`mp schedule install`** is idempotent. Running it twice leaves one task, updated to the current settings. It prints the next run time.
- [ ] **`mp schedule remove`** removes the task, and reports "not installed" (exit 0) when there is nothing to remove.
- [ ] **`mp schedule status`** shows installed or not, the schedule, last run time and result, next run time, and the last cycle summary path from ticket 23.
- [ ] Before installing, `mp doctor` runs. Install refuses, with a clear message, if `uv`, the `claude` login or the Mealie token is missing (`--force` overrides). A pipeline-seam test with fakes covers this.
- [ ] Output from the scheduled run (stdout/stderr) goes to `reports/auto/last-run.log`, rotated to keep the last 10, so a silent failure can be diagnosed.
- [ ] `RUNBOOK.md` gets a section *Keeping Mealie in sync*. It covers how to install, check, pause (`mp schedule remove`) and resume. It also covers what the toasts mean, re-logging a platform after `needs_login`, and the fact that unsaving a Video never deletes its recipe.

**Hand-off to the user (ready-for-human after the code is done), only after wayfinder 19 questions 7–10 are answered:**
1. Run `uv run mp schedule install`.
2. Open Task Scheduler and confirm the task `mealie_pipeline auto sync` exists with the agreed schedule.
3. Run it once with *Run* in Task Scheduler and check `reports/auto/` for the summary.
4. Leave it on for a few days and check `reports/auto/history.csv`.
