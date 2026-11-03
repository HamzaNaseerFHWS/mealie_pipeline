# 32: Spike: does `claude -p` on the Claude Pro login work inside a container?

**What to build:** Nothing permanent: find out whether the Claude Code CLI can run non-interactively (`claude -p`) in the `pipeline` container on the user's Claude Pro subscription, keep its login across restarts, and know how long it lasts. The whole plan of running the pipeline on the Mealie PC depends on this. Record the answer in this ticket's Comments.

Find out:
1. How the login is done once (interactive `claude` login in the container, or copying the login files) and which folder must be a volume (`claude-login`) so it survives `docker compose down/up` and image rebuilds.
2. That `claude -p "say ok"` works afterwards, with **no** `--bare` and no API key.
3. Whether the login expires or asks again (check again after a day and after a week) and what the failure looks like, so the worker can pause and tell the user instead of marking items failed (see ticket 13).
4. That several parallel calls (`llm.max_parallel`) work from the container.

**Blocked by:** 31 (the image)

**Status:** ready-for-human

**Read first:** `src/mealie_pipeline/adapters/` (the `claude` adapter), `CLAUDE.md` (environment facts: Pro subscription, never `--bare`).

- [ ] Login steps written down as a short runbook in `deploy/README.md`.
- [ ] `docker compose run --rm pipeline claude -p "say ok"` answers after a full restart.
- [ ] Expiry behaviour recorded, and what the user has to do when it expires.
- [ ] If it cannot work: say so here and list the fallback (keep the pipeline on the laptop, run only the bot on the Mealie PC).

**Manual check on the Mealie PC (user):** do the login, restart the container, run the `claude -p` line again.
