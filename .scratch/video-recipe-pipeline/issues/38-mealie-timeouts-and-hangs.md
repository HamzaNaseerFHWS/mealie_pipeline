# 38: A silent Mealie must not hang a whole run

**What to build:** Twice a run produced no output for hours because Mealie did not answer (once the Mealie PC was off; classify starts by listing all recipes from Mealie and waited far too long). Fix it:

1. `MEALIE__TIMEOUT_SECONDS` defaults to 60. It currently has to be set by hand in every shell. Put the default in settings and in `.env.example`.
2. An overall deadline for the calls that start a run (list recipes, foods, tags), with a clear message (`cannot reach Mealie at <url> after <n> s`) and exit code 3. The long driver scripts already wait and retry on that message.
3. Steps that do not need Mealie (metadata, classify, scrape, outline, extract) keep running when Mealie is down; only the Mealie-dependent steps (existing-link check, parse, tag, upload) wait. If that is too big a change, at least classify must not need the full recipe list.
4. `mp doctor` reports Mealie's response time.

**Blocked by:** None

**Status:** done

**Read first:** `adapters/mealie_http.py` (`_request`, `_items`), `pipeline.py` (`_already_in_mealie`, `_link_set`, `_classify`), `settings.py`.

- [x] Test with a fake Mealie server that never answers: the run exits with the message and code 3 within the deadline.
- [x] Test that classify and extract run with Mealie down (if item 3 is done).
- [x] The 60 s default is in effect without any env var.

**Manual check (user):** turn the Mealie PC's Tailscale off and run `mp run --list ...`; it ends with the message instead of hanging.

## Comments

**Built**
- `mealie.timeout_seconds` defaults to 60 (in `settings.py` and `config/settings.yaml`), and `.env.example` lists `MEALIE__TIMEOUT_SECONDS=60`. A new `mealie.deadline_seconds` (default 120) caps one call, retries and backoff included. A call Mealie never answers ends in `cannot reach Mealie at <url> after <n> s: is Tailscale connected?`.
- `mp run` exits with **code 3** and that message whenever Mealie did not answer during the run.
- The first missed call marks Mealie as down for the rest of the run, so nothing waits on it twice. With Mealie down:
  - metadata, classify, scrape, outline and extract keep running;
  - classify skips its "already in Mealie" shortcut;
  - linkcheck is recorded as "not checked", and upload repeats that check;
  - extract offers the tag names from the last time Mealie answered (`data/mealie_tags.json`). If Mealie has never answered, extract waits too;
  - parse, tag, verify and upload wait. Their items stay `pending` (never `failed`) and finish on the next run.
- `mp doctor` shows Mealie's response time ("answered in 0.12 s") and warns when it took more than half the timeout.

**Tests:** `tests/test_mealie_down.py` (a local port that accepts connections and never answers, plus a FakeMealie that is unreachable).

**Manual check (user):** turn off Tailscale on the Mealie PC and run `mp run --list ...`. The run should end with `cannot reach Mealie at ... after N s` and exit code 3 (`echo $LASTEXITCODE`) instead of hanging. Turn Tailscale back on and run again: the waiting items upload.
