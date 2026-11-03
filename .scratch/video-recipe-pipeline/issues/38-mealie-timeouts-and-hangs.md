# 38: A silent Mealie must not hang a whole run

**What to build:** Twice a run produced no output for hours because Mealie did not answer (once the Mealie PC was off; classify starts by listing all recipes from Mealie and waited far too long). Fix it:

1. `MEALIE__TIMEOUT_SECONDS` defaults to 60. It currently has to be set by hand in every shell. Put the default in settings and in `.env.example`.
2. An overall deadline for the calls that start a run (list recipes, foods, tags), with a clear message (`cannot reach Mealie at <url> after <n> s`) and exit code 3. The long driver scripts already wait and retry on that message.
3. Steps that do not need Mealie (metadata, classify, scrape, outline, extract) keep running when Mealie is down; only the Mealie-dependent steps (existing-link check, parse, tag, upload) wait. If that is too big a change, at least classify must not need the full recipe list.
4. `mp doctor` reports Mealie's response time.

**Blocked by:** None

**Status:** in-progress

**Read first:** `adapters/mealie_http.py` (`_request`, `_items`), `pipeline.py` (`_already_in_mealie`, `_link_set`, `_classify`), `settings.py`.

- [ ] Test with a fake Mealie server that never answers: the run exits with the message and code 3 within the deadline.
- [ ] Test that classify and extract run with Mealie down (if item 3 is done).
- [ ] The 60 s default is in effect without any env var.

**Manual check (user):** turn the Mealie PC's Tailscale off and run `mp run --list ...`; it ends with the message instead of hanging.
